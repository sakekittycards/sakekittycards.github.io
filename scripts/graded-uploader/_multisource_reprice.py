"""
True multi-source max reprice: for each owned cert, pull base price from
THREE sources, take the highest, apply the aggressive CL formula, and push
to Square. Honors manual-override rows (Moltres etc.).

Sources:
  1. Card Ladder Current Value  (from Collection - Card Ladder (N).csv)
  2. PriceCharting graded value (from assets/pc-graded.json, by productId)
  3. eBay recent sold trimmed-avg (via _ebay_apify Apify actor)

Policy: never LOWER an existing sticker — only push when new sticker > current.
This prevents a momentary low comp from eroding shelf prices; we wait for
sustained signal before reducing.

Outputs:
  - _multisource_report_<date>.csv  human-readable diff
  - pushes updates to Square via /admin/update-graded-price
"""
from __future__ import annotations

import csv
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# eBay sold comps come from a real Chrome browser (Playwright), not Apify —
# Apify's capped search returned wrong lows (Deoxys $198 vs ~$300 real) and
# burns a metered quota. _ebay_chrome is an API-compatible drop-in.
from _ebay_chrome import fetch_apify, fetch_or_cache as _ebay_cached
# pricing.csv carries no productId, so resolve it by fuzzy-matching the card's
# identity against all-cards-fallback.json (PriceCharting's own product list) —
# same proven matcher the max-formula script uses.
from _apply_max_price_formula import fuzzy_resolve_pid

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PRICING_CSV = HERE / "pricing.csv"
CL_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder (42).csv")
PC_GRADED = REPO / "assets" / "pc-graded.json"
ALL_CARDS  = REPO / "assets" / "all-cards-fallback.json"
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"
REPORT_CSV = HERE / f"_multisource_report_{datetime.date.today().isoformat()}.csv"

# pc-graded.json values: [loose, psa8, psa9, psa9.5/bgs9.5, psa10, bgs10]
PC_COL = {
    "PSA 10": 4, "PSA 9": 2, "PSA 8": 1, "PSA 7": 0,
    "BGS 10": 5, "BGS 9.5": 3, "BGS 9": 2, "BGS 8.5": 1,
    "CGC 10 Pristine": 4, "CGC 10": 4, "CGC 9.5": 3, "CGC 9": 2,
    "PRISTINE 10": 4, "MINT 9": 2, "MINT 10": 4,
    "GEM MT 10": 4, "GEMMT 10": 4, "GEM MINT 10": 4, "MT 10": 4,
    "NM-MT 8": 1, "NM-MT+ 8.5": 1, "NM 7": 0,
}


def get_token() -> str | None:
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t: return t.strip()
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def markup(base: float) -> float:
    """Net 10% profit when buying at 90% of base value:
      cost          = base * 0.90       (we buy at 90% of base value)
      sell price P  -> net = 0.97*P - 6 (after 3% fees + $6 shipping)
      profit goal:   net - cost = 0.10 * cost  (10% net profit on cost)
      -> P = (0.99 * base + 6) / 0.97
    """
    return (base * 0.99 + 6) / 0.97


def snap_clean(price: float) -> int:
    if price <= 0: return 0
    b = int(round(price))
    cands = [n for n in range(max(1, b - 6), b + 7) if n % 5 == 0]
    cands.sort(key=lambda n: (abs(n - price), -n))
    return cands[0]


def normalize_grade(g: str) -> str:
    g = (g or "").strip().upper()
    m = re.match(r"(PSA|CGC|BGS|SGC)\s*\.?\s*([0-9]+(?:\.[0-9])?)\s*(PRISTINE)?", g)
    if m:
        grader, num, prist = m.group(1), m.group(2), m.group(3)
        if grader == "CGC" and (prist or num == "10"):
            return "CGC 10 Pristine"
        return f"{grader} {num}"
    if "GEMMT 10" in g or "GEM MT 10" in g: return "PSA 10"
    return g


# CL's internal set-name prefixes that don't appear in eBay titles
# (e.g. "Obf En-Obsidian Flames" -> "Obsidian Flames").
CL_SET_PREFIXES = re.compile(
    r"\b(?:Obf|Wht|Sv\d+(?:pt\d+|[a-z]+)?|Pre|Meg|Asc|Blk|Paf|Svp|Sv\da?|Wsv|Bsv)"
    r"\s+(?:En|Jp|Sc)\s*-\s*", re.I
)


def _clean_set(s: str) -> str:
    s = re.sub(r"^Pokemon\s+(Japanese\s+)?", "", s, flags=re.I)
    s = CL_SET_PREFIXES.sub("", s)
    return " ".join(s.replace(":", " ").split())


def _clean_subject(s: str) -> str:
    # Expand CL's "Fa /" prefix -> "Full Art" (matches eBay seller convention)
    s = re.sub(r"^(FA|Fa|Full\s*Art)\s*/\s*", "Full Art ", s)
    # Strip CL's "-Holo", "-Rev.foil", "-Reverse", "-Secret" shorthand suffixes
    s = re.sub(r"-(Holo|Rev\.?\s*foil|Reverse|Secret)\b", "", s, flags=re.I)
    return " ".join(s.replace("/", " ").replace(":", "").split())


def _clean_variation(v: str) -> str:
    # Drop set-name duplicates that CL sometimes puts in Variation
    if not v: return ""
    v = v.replace(":", " ")
    if re.match(r"^(Vmax|Sword|Shield|Scarlet|Violet|Sun|Moon)\s*", v, re.I):
        if any(t in v for t in ("Climax", "Voltage", "Skies", "Strike", "Bolt", "Flare")):
            return ""
    return " ".join(v.split())


def _short_number(n: str) -> str:
    # "202/165" -> "202"; "062/SV-P" -> "062"
    n = (n or "").strip().lstrip("#")
    return n.split("/", 1)[0] if "/" in n else n


def _grade_for_query(g: str) -> str:
    g = (g or "").strip()
    if re.match(r"^CGC\s*10\s*Pristine$", g, re.I):
        return "CGC Pristine 10"
    return g


def build_ebay_keyword_from_cl(cl_row: dict, grade: str) -> str:
    """Build an eBay sold-listings query from CL fields, mirroring how a real
    collector would search eBay. v2 (2026-05-18): pulls Year + Subject +
    Variation + Number + Set + Grade so the query disambiguates Art Rare vs
    regular vs SIR vs FA Secret.

    NEVER from pricing.csv.name — that field carries forward pokemontcg.io
    misidentifications. CL is the truth source for graded card identity.
    """
    parts: list[str] = []
    year = (cl_row.get("Year") or "").strip()
    if year:
        parts.append(year)
    subj = _clean_subject(cl_row.get("Subject") or "")
    if subj:
        parts.append(subj)
    var = _clean_variation(cl_row.get("Variation") or "")
    if var:
        parts.append(var)
    num = _short_number(cl_row.get("Number") or "")
    if num:
        parts.append(f"#{num}")
    set_clean = _clean_set(cl_row.get("Set") or "")
    if set_clean:
        parts.append(set_clean)
    # Grade comes last so eBay's relevance ranking weights the card name first
    g = _grade_for_query(grade or cl_row.get("Condition") or "")
    if g:
        parts.append(g)
    return " ".join(parts)


def ebay_sold_url(keyword: str) -> str:
    """Build a clickable eBay sold-listings URL for manual validation."""
    import urllib.parse
    return (f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(keyword)}"
            f"&LH_Sold=1&LH_Complete=1&_ipg=120")


def grade_matches_title(title: str, grade: str) -> bool:
    """LOOSE grade check (compat, retained for callers).
    For strict pricing we use title_passes() below.
    Handles both seller orderings: 'CGC PRISTINE 10' (eBay seller-style) AND
    'CGC 10 Pristine' (CL-style)."""
    t = (title or "").upper().replace(".", "").replace(" ", "")
    g = grade.upper().replace(".", "").replace(" ", "")
    if g in t: return True
    if g == "PSA10" and ("GEMMT10" in t or "GEMMINT10" in t): return True
    # CGC Pristine 10 written either order
    g_has_cgc_pristine = ("CGC" in g and "PRISTINE" in g and "10" in g)
    t_has_cgc_pristine = ("CGC" in t and "PRISTINE" in t and "10" in t)
    if g_has_cgc_pristine and t_has_cgc_pristine: return True
    return False


# Competing-slab noise that pollutes PSA-grade averages (2026-05-22).
# These appear in titles like "Beckett BGS 9 ... Regrade to PSA 10" — the
# sold price reflects the BGS slab, not a real PSA 10 comp.
_NOISE_TITLE_WORDS = ("BGS", "CGC", "SGC", "REGRADE", " RAW ", "UNGRADED", "AUTHENTIC ONLY")


# Per-cert eBay comp exclusions. subject+number+grade can't tell apart a
# DIFFERENT/more-valuable variant that shares the same subject and number, so
# those comps pollute the sold average. List the variant tokens (UPPER) that
# disqualify a comp for THIS specific card. (Card-specific on purpose — a
# blanket "reject SHADOWLESS" would wrongly drop comps for a card that IS
# shadowless.)
VARIANT_EXCLUDE: dict[str, tuple[str, ...]] = {
    # Venusaur #15 Base Set, UNLIMITED — drop Shadowless / 1st-ed (sell ~2-3x).
    "65570347": ("SHADOWLESS", "1ST ED", "FIRST ED"),
    # Moltres #146 Vending Series II — drop the other #146 Moltres variants:
    # Bandai Carddass "Prism", Gym "Rocket's", and the Red/Green Gift Set Holo
    # (the Gift Set sells ~3-4x and was dragging the mean to $1700+).
    "84566703": ("CARDDASS", "PRISM", "ROCKET", "GYM", "GIFT SET", "RED/GREEN", "RED GREEN"),
    # Zapdos #16 Base Set, UNLIMITED — drop Fossil-set Zapdos (its cert # can
    # contain "16" and slip the number filter), 1st-ed, and foreign printings.
    "139036804": ("FOSSIL", "1ST ED", "FIRST ED", "PORTUGUESE"),
}


def title_passes(title: str, subject: str, number: str, grade: str) -> bool:
    """STRICT eBay listing filter.
    A listing's title must:
      1. Match the grade (with CGC/PSA equivalencies)
      2. Contain the first significant word of the cleaned subject (>=4 chars)
      3. Contain the short number (2+ digits)
      4. NOT contain competing-slab noise (BGS/CGC/Regrade) — these pollute
         PSA averages with non-PSA sale prices.
    """
    if not grade_matches_title(title, grade):
        return False
    t_up = title.upper()
    # Reject competing-slab noise BEFORE other checks
    for noise in _NOISE_TITLE_WORDS:
        if noise in t_up:
            return False
    t = t_up.replace(".", "").replace("-", " ")
    subj_word = (_clean_subject(subject).split() or [""])[0].upper()
    if len(subj_word) >= 4 and subj_word not in t:
        return False
    n_short = _short_number(number)
    if n_short and len(n_short) >= 2 and n_short not in t:
        return False
    return True


def trimmed_avg(values: list[float], drop_pct: float = 0.1) -> float | None:
    """DEPRECATED — kept for backward callers. New median-of-last-5 path uses
    median_last5_by_date() below."""
    if not values: return None
    vs = sorted(values)
    if len(vs) <= 3: return sum(vs) / len(vs)
    k = max(1, int(len(vs) * drop_pct))
    trimmed = vs[k:-k] if len(vs) > 2 * k else vs
    return sum(trimmed) / len(trimmed)


def best_recent_avg(items_with_dates: list[tuple[float, str]]) -> float | None:
    """eBay base = the HIGHEST of mean-of-last-3, mean-of-last-5, and
    mean-of-last-10 sold (by endedAt date, most recent first). Per Nick
    2026-05-27 (replaced the prior median-of-5).

    Why max-of-windows: the last-3 mean captures a rising market, the last-10
    mean smooths a quiet stretch; taking the highest biases toward the top of
    the legitimate recent range — right for a retail sticker and consistent
    with the max-of-sources policy. The strict title filter upstream
    (subject + number + grade, BGS/CGC noise rejected) is what keeps a
    wrong-card or competing-slab comp out of these means, and the 2x sanity cap
    + tier threshold still gate any actual push.

    Input: list of (price, endedAt_iso_string) tuples. Windows shorter than the
    available comp count just average what's there (e.g. 4 comps -> last-5 and
    last-10 both average all 4).
    """
    if not items_with_dates:
        return None
    items_with_dates.sort(key=lambda x: x[1] or "", reverse=True)
    prices = [p for p, _ in items_with_dates if p and p > 0]
    if not prices:
        return None
    means = []
    for n in (3, 5, 10):
        window = prices[:n]
        if window:
            means.append(sum(window) / len(window))
    return round(max(means), 2) if means else None


def parse_current_price(raw: str) -> float | None:
    if not raw: return None
    s = raw.strip()
    if s.startswith("[uploaded]"): s = s[len("[uploaded]"):]
    s = s.lstrip("$").replace(",", "").strip()
    try: return float(s) if s else None
    except ValueError: return None


def update_square(cert: str, price_cents: int, token: str) -> tuple[bool, str]:
    body = json.dumps({"cert": cert, "price_cents": price_cents}).encode()
    req = urllib.request.Request(
        f"{WORKER_BASE}/admin/update-graded-price", method="POST", data=body,
        headers={"X-Sake-Admin-Token": token, "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}"
    except Exception as e:
        return False, str(e)


def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    # Load CL CSV
    cl_map: dict[str, dict] = {}
    with CL_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cert = (row.get("Graded Cert #") or "").strip()
            if cert: cl_map[cert] = row

    # Load pricing.csv
    with PRICING_CSV.open("r", encoding="utf-8", newline="") as f:
        pricing_rows = list(csv.DictReader(f))

    # Load PC graded index
    with PC_GRADED.open("r", encoding="utf-8") as f:
        pc_index = json.load(f)

    # Load PriceCharting product list (name/set -> productId) for PC resolution
    with ALL_CARDS.open("r", encoding="utf-8") as f:
        fallback = json.load(f)

    print(f"[ms] Loaded: {len(cl_map)} CL rows, {len(pricing_rows)} pricing rows, "
          f"{len(pc_index):,} PC entries, {len(fallback):,} fallback products")

    # First pass: build per-cert PC price + ebay keyword list
    cards: list[dict] = []
    keywords: list[str] = []
    cert_to_kw: dict[str, str] = {}
    for row in pricing_rows:
        cert = (row.get("cert") or "").strip()
        if not cert: continue
        if "manual override" in (row.get("condition_note") or "").lower():
            cards.append({"cert": cert, "row": row, "skip": True})
            continue
        cl_row = cl_map.get(cert)
        if not cl_row:
            cards.append({"cert": cert, "row": row, "skip": True, "reason": "not in CL"})
            continue
        try: cl_cv = float((cl_row.get("Current Value") or "0").replace(",", ""))
        except ValueError: cl_cv = 0.0
        # PriceCharting lookup. pricing.csv has no productId, so resolve it by
        # fuzzy-matching the CL identity (cleaned Subject/Set + short Number) —
        # the same truth-source fields we build the eBay query from — against
        # all-cards-fallback, then read the per-grade column from pc-graded.json.
        pc_value = None
        pid = fuzzy_resolve_pid(
            _clean_subject(cl_row.get("Subject") or ""),
            _clean_set(cl_row.get("Set") or ""),
            _short_number(cl_row.get("Number") or ""),
            fallback,
        )
        if pid and str(pid) in pc_index:
            vals = pc_index[str(pid)]
            grade_norm = normalize_grade(row.get("grade", ""))
            col = PC_COL.get(grade_norm)
            if col is not None and col < len(vals):
                v = vals[col]
                if isinstance(v, (int, float)) and v > 0:
                    pc_value = float(v)
        kw = build_ebay_keyword_from_cl(cl_row, normalize_grade(row.get("grade", "")))
        cards.append({
            "cert": cert, "row": row, "cl_row": cl_row,
            "cl_cv": cl_cv, "pc_value": pc_value, "ebay_kw": kw, "skip": False,
        })
        keywords.append(kw)
        cert_to_kw[cert] = kw

    # Fetch eBay sold via real Chrome. A reprice ALWAYS scrapes brand-new comps
    # (Nick 2026-05-29: "data must be brand new when i ask to reprice graded") —
    # force_fresh bypasses the 72h cache. Set USE_CACHE=1 to opt back into the
    # cache (e.g. a same-session re-run while iterating on guards/exclusions).
    force_fresh = os.environ.get("USE_CACHE") != "1"
    print(f"[ms] Fetching eBay sold for {len(cert_to_kw)} certs "
          f"({'FRESH scrape' if force_fresh else 'cache OK'}) ...")
    ebay_by_cert = _ebay_cached(cert_to_kw, force_fresh=force_fresh) if cert_to_kw else {}
    print(f"[ms] eBay results: {sum(1 for v in ebay_by_cert.values() if v)} certs returned data")

    # Build final pricing
    token = get_token()
    if os.environ.get("DRY_RUN") == "1":
        token = None
        print("[ms] DRY_RUN=1 — building report only, will NOT push to Square.")
    if not token:
        print("[ms] WARNING: SK_ADMIN_TOKEN not set — will not push updates, just report.")
    # Certs to hold from auto-push (manual review), e.g. variant pollution in
    # the eBay comps (Shadowless/1st-ed/cross-set sharing a subject+number).
    hold_certs = {c.strip() for c in os.environ.get("HOLD_CERTS", "").split(",") if c.strip()}
    if hold_certs:
        print(f"[ms] HOLD_CERTS: holding {sorted(hold_certs)} from auto-push.")

    report = []
    updates: list[tuple[str, int, dict]] = []

    # ── PASS 1: compute each card's own base = max(CL, PC, eBay) ────────────
    for c in cards:
        if c.get("skip"):
            continue
        cert = c["cert"]; row = c["row"]
        cl_cv = c["cl_cv"]; pc_val = c["pc_value"]
        # eBay average — with mandatory guards (per 2026-05-12 incident).
        ebay_items = ebay_by_cert.get(cert, [])
        grade = normalize_grade(row.get("grade", ""))
        # STRICT post-filter: listings must mention grade AND subject AND number.
        subj = c["cl_row"].get("Subject", "") if c.get("cl_row") else ""
        num = c["cl_row"].get("Number", "") if c.get("cl_row") else ""
        excl = VARIANT_EXCLUDE.get(cert, ())
        ebay_priced_items: list[tuple[float, str]] = []
        for it in ebay_items:
            title = it.get("title", "")
            if not title_passes(title, subj, num, grade): continue
            # Nick 2026-05-27: don't consider Best Offer sales (settle below ask).
            if it.get("bestOffer"): continue
            # Clean comps only: drop different/more-valuable variants of the
            # same subject+number (Shadowless, Carddass Prism, etc.).
            if excl and any(x in title.upper() for x in excl): continue
            try: p = float(it.get("totalPrice") or it.get("soldPrice") or 0)
            except (TypeError, ValueError): continue
            if 1 < p < 100000:
                ebay_priced_items.append((p, it.get("endedAt", "")))

        ebay_count = len(ebay_priced_items)
        ebay_avg = None
        ebay_reject = ""
        if ebay_count < 3:
            ebay_reject = f"need>=3 (got {ebay_count})"
        else:
            ebay_avg = best_recent_avg(ebay_priced_items)

        # Winner = MAX of CL / PC / eBay (Nick 2026-05-27).
        sources = []
        if cl_cv: sources.append(("CL", cl_cv))
        if pc_val: sources.append(("PC", pc_val))
        if ebay_avg: sources.append(("EBAY", ebay_avg))
        if sources:
            winner_name, winner_val = max(sources, key=lambda x: x[1])
        else:
            winner_name, winner_val = "NONE", 0.0
        c["_ebay_avg"] = ebay_avg
        c["_ebay_count"] = ebay_count
        c["_ebay_reject"] = ebay_reject
        c["_winner_name"] = winner_name
        c["_winner_val"] = winner_val
        c["_cur_price"] = parse_current_price(row.get("your_price", "")) or 0

    # ── Equalize identical cards ────────────────────────────────────────────
    # The eBay keyword (Year + Subject + Variation + Number + Set + Grade) is a
    # card-identity key: two slabs of the SAME card in the SAME grade share it.
    # Two copies had divergent Card Ladder CVs and so priced differently — lift
    # the whole group to the max base so duplicates always match (sticky-floor:
    # equalize UP, never lower one to meet the other).
    group_max: dict[str, float] = {}     # highest source base in the group
    group_size: dict[str, int] = {}      # how many copies of this card
    group_cur_max: dict[str, float] = {} # highest CURRENT sticker in the group
    for c in cards:
        if c.get("skip"):
            continue
        kw = c["ebay_kw"]
        group_size[kw] = group_size.get(kw, 0) + 1
        group_cur_max[kw] = max(group_cur_max.get(kw, 0.0), c.get("_cur_price", 0.0) or 0.0)
        if c.get("_winner_name") == "NONE":
            continue
        group_max[kw] = max(group_max.get(kw, 0.0), c.get("_winner_val", 0.0))

    allow_lower = os.environ.get("ALLOW_LOWER") == "1"

    # ── PASS 2: equalize -> price -> decide action -> report ────────────────
    for c in cards:
        cert = c["cert"]; row = c["row"]
        if c.get("skip"):
            report.append({
                "cert": cert, "name": row.get("name", ""),
                "current": parse_current_price(row.get("your_price", "")),
                "cl_cv": "", "pc": "", "ebay_avg": "",
                "ebay_count": 0, "ebay_reject": "", "ebay_kw": "",
                "ebay_url": "",
                "winner": "", "base": "", "new_price": "",
                "action": "skip",
                "reason": c.get("reason", "manual override"),
            })
            continue
        cl_cv = c["cl_cv"]; pc_val = c["pc_value"]; kw = c["ebay_kw"]
        ebay_avg = c["_ebay_avg"]; ebay_count = c["_ebay_count"]
        ebay_reject = c["_ebay_reject"]
        winner_name = c["_winner_name"]; winner_val = c["_winner_val"]
        cur_price = c["_cur_price"]

        # Equalize identical cards. base_val = highest source base in the group;
        # for a card with duplicates the sticker is lifted to the HIGHEST of the
        # group's formula price and the group's current stickers, so two copies
        # always match WITHOUT lowering either (sticky floor).
        base_val = winner_val
        equalized = False
        reason = ""
        if winner_name != "NONE":
            own_price = snap_clean(markup(winner_val))
            base_val = max(winner_val, group_max.get(kw, winner_val))
            formula_price = snap_clean(markup(base_val))
            if group_size.get(kw, 1) > 1:
                new_price = max(formula_price, int(round(group_cur_max.get(kw, 0.0))))
                if new_price != own_price:
                    equalized = True
                    reason = f"equalized to duplicate (${new_price})"
            else:
                new_price = formula_price
        else:
            new_price = 0

        # Policy: never lower an existing sticker — only push if higher.
        # Guard 3: sanity cap — don't auto-raise more than 2x in a single run.
        # Guard 4: tier-based raise threshold.
        #   under $200   -> raise on any formula bump
        #   $200..$999   -> need formula > current * 1.05
        #   $1000+       -> need formula > current * 1.10
        if cert in hold_certs:
            action = "skip-held"
        elif winner_name == "NONE":
            action = "skip-no-market-data"
        elif cur_price > 0 and new_price > 2 * cur_price:
            action = "skip-sanity-cap-2x"
        elif new_price > cur_price:
            if cur_price >= 1000:
                threshold = cur_price * 1.10
            elif cur_price >= 200:
                threshold = cur_price * 1.05
            else:
                threshold = cur_price  # any raise OK in tier 1
            # A pure-equalization raise (matching an identical card) bypasses the
            # tier threshold — identical cards must match regardless of % move.
            if new_price > threshold or equalized:
                action = "raise-equalize" if equalized and new_price <= threshold else "raise"
                updates.append((cert, new_price, c))
            else:
                action = "skip-below-tier-threshold"
        elif new_price == cur_price:
            action = "no-change"
        elif allow_lower:
            action = "lower"
            updates.append((cert, new_price, c))
        else:
            action = "skip-not-lowering"

        report.append({
            "cert": cert, "name": row.get("name", ""),
            "current": cur_price,
            "cl_cv":   f"{cl_cv:.2f}" if cl_cv else "",
            "pc":      f"{pc_val:.2f}" if pc_val else "",
            "ebay_avg":f"{ebay_avg:.2f}" if ebay_avg else "",
            "ebay_count": ebay_count,
            "ebay_reject": ebay_reject,
            "ebay_kw": kw,
            "ebay_url": ebay_sold_url(kw),
            "winner":  winner_name + ("*" if equalized else ""),
            "base":    f"{base_val:.2f}",
            "new_price": new_price,
            "action":  action,
            "reason":  reason,
        })

    # Write report
    with REPORT_CSV.open("w", encoding="utf-8", newline="") as f:
        if report:
            w = csv.DictWriter(f, fieldnames=list(report[0].keys()))
            w.writeheader()
            w.writerows(report)
    print(f"[ms] Report -> {REPORT_CSV}")

    # Summary
    actions = {}
    for r in report:
        actions[r["action"]] = actions.get(r["action"], 0) + 1
    print(f"[ms] Plan: {actions}")

    if not token or not updates:
        print(f"[ms] No updates to push (or no token).")
        return

    print(f"[ms] Pushing {len(updates)} sticker raises to Square ...")
    ok = fail = 0
    for i, (cert, new_price, c) in enumerate(updates, 1):
        cents = int(round(new_price * 100))
        success, err = update_square(cert, cents, token)
        if success:
            ok += 1
            print(f"  {i:>2}/{len(updates)} OK  cert {cert}  ${new_price}")
            # Also update pricing.csv row
            c["row"]["your_price"] = f"[uploaded]{new_price}"
        else:
            fail += 1
            print(f"  {i:>2}/{len(updates)} ERR cert {cert}  {err}")
        time.sleep(0.25)

    # Write pricing.csv back
    with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pricing_rows[0].keys()))
        w.writeheader()
        w.writerows(pricing_rows)
    print(f"[ms] pricing.csv updated. {ok} pushed, {fail} failed.")


if __name__ == "__main__":
    main()
