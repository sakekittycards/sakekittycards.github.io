"""make_offer() — the shared graded buy-offer engine.

The single callable the messaging layer (IG auto-responder / FB review queue)
hits. Takes a list of card items a seller is selling — each one EITHER a PSA
cert # OR a stated card spec from a collector list (PriceCharting / Collectr /
typed) — resolves identity, prices each card multi-source, applies Nick's graded
buy tiers, flags rejects + low-confidence rows, and renders the branded BUY OFFER
PDF.

Item shapes accepted (a list of dicts):
  {"cert": "96312970"}                              # resolve identity via PSA
  {"name","set","number","grade","year"?}           # stated (collector list)
  {... , "market": 930}                             # caller-supplied value override
  {... , "pc_id": 614012}                           # known PriceCharting productId

Returns an OfferResult dict:
  {
    "rows":      [priced rows that made the offer],
    "rejected":  [under-$100 policy rejects],
    "review":    [need a human: missing grade, low confidence, no price found],
    "totals":    {"market","cash","credit"},
    "auto_ok":   bool   # safe to auto-send? (all rows priced, none in review)
    "deal_rating":     1-10 int|None  # Nick-facing BUY quality (10=amazing, 1=pass) — INTERNAL
    "deal_label":      "Amazing".."Pass"|None
    "liquidity_rating":"S1".."S9"|None # value-weighted flip velocity
    "pdf_path", "html_path": str|None,
    "summary":   one-line text for the chat reply,
  }
  deal_rating/deal_label/liquidity_rating are INTERNAL (Nick's review only) — never put
  them in the seller-facing reply or on the offer PDF.

Pricing per card (multi-source MAX, per feedback_multi_source_max_pricing):
  market = max(eBay PSA last-sold, PriceCharting per-grade, caller override)
Confidence is HIGH when eBay + PC agree within ~35%, MEDIUM on a single source,
LOW when they diverge >2x or only a fallback exists.

CLI:  python _offer_engine.py certs 96312970 83631916 ...
      python _offer_engine.py demo          # reproduce the 8-card sample offer
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parents[1]

# ── shared data + helpers reused from the existing pipeline ──────────────────
PCG = json.loads((SITE / "assets" / "pc-graded.json").read_text(encoding="utf-8"))
FALLBACK = json.loads((SITE / "assets" / "all-cards-fallback.json").read_text(encoding="utf-8"))
from _apply_max_price_formula import fuzzy_resolve_pid           # productId resolver
from _graded_offer_pdf import rate, render                       # tiers + PDF builder

# PriceCharting / pc-graded.json column for each grade.
# LOCKED MAP (CLAUDE.md): 0 loose · 1 PSA8 · 2 PSA9 · 3 PSA9.5/BGS9.5 · 4 PSA10 · 5 BGS10.
# NB: _graded_offer_final.py had PSA10=5 (that's the BGS-10 column) — a bug; 4 is correct.
PC_COL = {"PSA 8": 1, "PSA 9": 2, "PSA 9.5": 3, "PSA 10": 4, "BGS 9.5": 3, "BGS 10": 5,
          "CGC 9": 2, "CGC 9.5": 3, "CGC 10": 4}

ILLIQUID_FLOOR = 150   # graded under this get flagged for review (Nick: skip illiquid low-cost)
LP_MULT = 0.85         # raw default when condition unknown (Nick 2026-06-10, conservative = LP)
COND_MULT = {"NM": 1.0, "LP": 0.85, "MP": 0.70, "HP": 0.50, "DMG": 0.30}  # site COND_MULT


def raw_rate(mk, kind="raw"):
    """Value-tier buy rate (cash, store credit) — matches trade-in.html RATES + tcgenie id-54."""
    if kind == "sealed":                       # sealed = premium ladder
        if mk < 100:  return 0.75, 0.85
        if mk < 500:  return 0.78, 0.88
        if mk < 1000: return 0.81, 0.91
        return 0.85, 0.95
    if mk < 100:  return 0.65, 0.75            # singles
    if mk < 500:  return 0.75, 0.85
    if mk < 1000: return 0.80, 0.90
    return 0.85, 0.95


def gnorm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _apply_qty(row, spec):
    """Scale a priced row by owned quantity (Collectr lists stack copies). Tier/status
    are decided on the per-unit value before this runs, so a 3× common stays a common."""
    try: q = int(float(spec.get("qty") or 1))
    except (TypeError, ValueError): q = 1
    if q > 1 and row.get("market") is not None:
        row["qty"] = q
        for k in ("market", "cash", "credit"):
            if row.get(k) is not None:
                row[k] = round(row[k] * q, 2)
    return row


# ── card-type routing (Nick 2026-06-10) ──────────────────────────────────────
# graded → eBay last-sold method (with confidence); raw + sealed → tcgsearch market.
_GRADE_RE = re.compile(r"\b(PSA|BGS|CGC|SGC)\b", re.I)
_SEALED_RE = re.compile(
    r"booster box|elite trainer|\betb\b|booster bundle|\bupc\b|ultra.?premium|"
    r"collection box|\btin\b|booster pack|blister|\bcase\b|premium collection", re.I)
_JUMBO_RE = re.compile(r"jumbo|oversized", re.I)


def card_type(spec):
    if (spec.get("grade") or "").strip() and _GRADE_RE.search(spec["grade"]):
        return "graded"
    # trust an explicit source flag (Collectr is_card=false) over keyword matching —
    # some sealed product names ("Poke Ball Collection [Shiny]") miss the regex.
    if spec.get("is_sealed"):
        return "sealed"
    blob = f"{spec.get('name','')} {spec.get('set','')}"
    if _SEALED_RE.search(blob):
        return "sealed"
    return "raw"


# ── pricing sources ──────────────────────────────────────────────────────────
def pc_value(name, setn, number, grade, pc_id=None):
    """PriceCharting per-grade value. Uses a known productId if supplied, else
    fuzzy-resolves from name+set+number against all-cards-fallback.json."""
    pid = pc_id or fuzzy_resolve_pid(name, setn, str(number).split("/")[0], FALLBACK)
    if pid and str(pid) in PCG:
        col = PC_COL.get((grade or "").strip())
        vals = PCG[str(pid)]
        if col is not None and col < len(vals):
            v = vals[col]
            if isinstance(v, (int, float)) and v > 0:
                return round(float(v), 2), pid
    return None, pid


def _grade_title_re(grade):
    """Boundary-anchored grade matcher: builds a pattern like
    (?<![A-Za-z])PSA\\s*#?\\s*9(?![\\d.]) so "PSA 9" won't match "PSA 9.5"
    or "PSA 9 ... 10". Falls back to a never-match if grade is malformed."""
    m = re.match(r"\s*([A-Za-z]+)\s*#?\s*([0-9]+(?:\.[0-9]+)?)\s*$", grade or "")
    if not m:
        return re.compile(r"(?!x)x")  # matches nothing
    grader = re.escape(m.group(1))
    gnum = re.escape(m.group(2))
    return re.compile(rf"(?<![A-Za-z]){grader}\s*#?\s*{gnum}(?![\d.])", re.I)


def ebay_value(items, grade, number, name):
    """Median of recent eBay sold comps tight-filtered to this card+grade.
    Requires the card NUMBER + first name token + grade in the title, drops
    BGS/CGC/SGC noise. (Same filter as _graded_offer_final.ebay_value.)"""
    grx = _grade_title_re(grade)
    num = re.sub(r"\D", "", str(number).split("/")[0])
    s0 = gnorm((name or "").split()[0]) if name else ""
    keep = []
    for it in items or []:
        t = it.get("title", ""); tn = gnorm(t)
        # Boundary-anchored grade match on the ORIGINAL title so "PSA 9" does
        # not match "PSA 9.5"; drop slab-vendor noise and multi-card lots.
        if not grx.search(t) or any(x in t.upper() for x in ("BGS", "CGC", "SGC")):
            continue
        if re.search(r"\b(lot|bundle|playset|x\s*\d)\b", t, re.I):
            continue
        if num and num not in re.sub(r"\D", "", tn):
            continue
        if s0 and s0 not in tn:
            continue
        try: p = float(it.get("totalPrice") or 0)
        except (TypeError, ValueError): p = 0
        if 1 < p < 100000:
            keep.append((it.get("endedAt", ""), p))
    keep.sort(reverse=True)
    prices = [p for _d, p in keep[:6]]
    return (round(statistics.median(prices), 2), len(keep)) if prices else (None, 0)


def ebay_keyword(name, setn, number, grade):
    num = str(number).split("/")[0]
    return f"{name} {setn} {num} {grade}".strip()


# ── identity resolution ──────────────────────────────────────────────────────
def resolve_certs(certs):
    """Resolve PSA cert #s to card specs in ONE stealth browser session.
    Returns {cert: {name,set,number,grade,year} | {"error":...}}. Lazy-imports
    Playwright so a cert-free offer never spins up a browser."""
    from playwright.sync_api import sync_playwright
    from _psa_cert_lookup import PROFILE, UA, extract
    out = {}
    PROFILE.mkdir(exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), headless=False,
            args=["--disable-blink-features=AutomationControlled", "--disable-infobars"],
            user_agent=UA, viewport={"width": 1280, "height": 1000})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://www.psacard.com/", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
        except Exception:
            pass
        for cert in certs:
            spec = {"error": "unresolved"}
            for _ in range(3):
                try:
                    page.goto(f"https://www.psacard.com/cert/{cert}",
                              wait_until="domcontentloaded", timeout=45000)
                    for _ in range(20):
                        page.wait_for_timeout(1500)
                        t = page.title().lower()
                        if "just a moment" not in t and "attention required" not in t:
                            break
                    page.wait_for_timeout(1200)
                    d = extract(page)
                    if d.get("subject") or d.get("year"):
                        spec = {
                            "name": (d.get("subject") or "").strip(),
                            "set": (d.get("brand") or "").strip(),
                            "number": (d.get("cardnum") or "").strip(),
                            "grade": _norm_grade(d.get("grade")),
                            "year": (d.get("year") or "").strip(),
                            "variety": (d.get("variety") or "").strip(),
                        }
                        break
                except Exception as e:
                    spec = {"error": str(e)[:80]}
            out[cert] = spec
        ctx.close()
    return out


def _norm_grade(g):
    """'GEM MT 10' / 'PSA 10' / '10' -> 'PSA 10'. Best-effort."""
    if not g:
        return ""
    s = str(g).upper()
    m = re.search(r"(\d+(?:\.\d)?)", s)
    if not m:
        return str(g).strip()
    n = m.group(1)
    if "BGS" in s: return f"BGS {n}"
    if "CGC" in s: return f"CGC {n}"
    return f"PSA {n}"


# ── the engine ───────────────────────────────────────────────────────────────
def price_item(spec, ebay_items=None):
    """Price one GRADED slab via the eBay last-sold method (with confidence);
    PriceCharting per-grade is a cross-check only. Returns a row dict with
    market/cash/credit, sources, confidence, status (ok | reject_under_100 | review_*)."""
    name = spec.get("name", ""); setn = spec.get("set", "")
    number = spec.get("number", ""); grade = (spec.get("grade") or "").strip()
    row = dict(name=name, set=setn, number=number, grade=grade,
               year=spec.get("year", ""), cert=spec.get("cert"),
               sources={}, confidence=None, status="ok", market=None,
               cash=None, credit=None)

    if not grade:
        row["status"] = "review_need_grade"
        return row

    ev, n = ebay_value(ebay_items, grade, number, name)   # eBay = the headline source
    pv, pid = pc_value(name, setn, number, grade, spec.get("pc_id"))   # cross-check
    override = spec.get("market")
    row["sources"] = {"ebay": ev, "ebay_n": n, "pc": pv, "override": override}

    # eBay-PRIMARY: market is the eBay sold median when we have comps; PC/override
    # only fill in when eBay returned nothing.
    if ev:
        market = ev
        row["confidence"] = "high" if n >= 3 else "medium"
        if pv and pv > 0:
            ratio = max(ev, pv) / min(ev, pv)
            if ratio > 2:                                 # eBay & PC disagree >2x
                row["confidence"] = "low"
    elif override:
        market = override
        row["confidence"] = "medium"                      # human-vetted value
    elif pv and pv > 0:
        market = pv
        row["confidence"] = "low"                         # no eBay comps — needs a look
    else:
        row["status"] = "review_no_price"
        return row

    row["market"] = round(market, 2)
    cr, dr = rate(market)
    row["cash"] = round(market * cr, 2)
    row["credit"] = round(market * dr, 2)

    if market < 100:
        row["status"] = "reject_under_100"           # policy: graded <$100 not accepted
    elif _JUMBO_RE.search(f"{name} {setn}"):
        row["status"] = "review_jumbo"               # jumbo/oversized not accepted any tier
    elif market < ILLIQUID_FLOOR:
        row["status"] = "review_low_value"           # illiquid low-cost — Nick eyeballs it
    elif row["confidence"] == "low":
        row["status"] = "review_divergent"           # low-confidence — needs a human
    return _apply_qty(row, spec)


def price_raw_sealed(spec, kind):
    """Price a RAW single or SEALED product via tcgsearch market (`ts_market`,
    set by _tcgsearch_price.tcgsearch_market) — or a caller `market`/`ts_market`
    override. Raw applies the LP condition multiplier; sealed does not."""
    name = spec.get("name", ""); setn = spec.get("set", ""); number = spec.get("number", "")
    row = dict(name=name, set=setn, number=number, grade="", type=kind, cert=None,
               sources={}, confidence="medium", status="ok",
               market=None, cash=None, credit=None,
               chip="LP" if kind == "raw" else "Sealed")
    mk = spec.get("ts_market") or spec.get("market")
    try: mk = float(mk) if mk else 0.0
    except (TypeError, ValueError): mk = 0.0
    row["sources"] = {"tcgsearch": spec.get("ts_market"), "override": spec.get("market")}
    if mk <= 0:
        row["status"] = "review_no_price"
        return row
    if _JUMBO_RE.search(f"{name} {setn}"):
        row["status"] = "review_jumbo"               # jumbo/oversized not accepted any tier
        row["market"] = round(mk, 2)
        return row
    # raw: use the stated condition multiplier if the list gave one (e.g. Collectr),
    # else default to LP (conservative). sealed: no condition discount.
    cond_name = (spec.get("condition") or "").upper()
    if kind == "sealed":
        cond, cond_name = 1.0, ""
    elif cond_name in COND_MULT:
        cond = COND_MULT[cond_name]
    else:
        cond, cond_name = LP_MULT, "LP"
    adj = mk * cond
    cr, dr = raw_rate(adj, kind)
    row["market"] = round(mk, 2)                      # show true market
    row["adj_market"] = round(adj, 2)
    row["condition"] = cond_name
    row["cash"] = round(adj * cr, 2)
    row["credit"] = round(adj * dr, 2)
    if kind == "raw":
        row["chip"] = cond_name
        verb = "assumed" if cond_name == "LP" and not spec.get("condition") else "stated"
        row["idnote"] = f"{cond_name} {verb} · confirmed on inspection"
    return _apply_qty(row, spec)


def make_offer(items, *, date=None, label=None, out_stem="SakeKitty_GradedBuyOffer",
               use_ebay=True, build_pdf=True, offer_mult=1.0, include_all=False, rating=None):
    """Main entry. items: list of dicts (cert OR stated spec). See module docstring.
    offer_mult scales the final cash+credit on every row (e.g. 0.95 = "offer 5% less than
    normal") — market is untouched; tiers apply first, then the multiplier.
    include_all=True: price + INCLUDE every item that has a value (no under-$100 graded
    reject, no low-value/illiquid hold-out) — for a whole-collection buy where Nick wants
    a price on everything. Only truly unpriceable rows (no source at all) stay in review."""
    from _graded_offer_pdf import DATE
    date = date or DATE

    # 1) resolve cert items to specs — but ONLY hit PSA when identity is missing.
    #    A collector list already states name+grade; the cert is just display metadata.
    def needs_lookup(it):
        return bool(it.get("cert")) and not (it.get("name") and it.get("grade"))
    certs = [str(it["cert"]).strip() for it in items if needs_lookup(it)]
    resolved = resolve_certs(certs) if certs else {}

    specs = []
    for it in items:
        if needs_lookup(it):
            r = resolved.get(str(it["cert"]).strip(), {})
            if "error" in r:
                specs.append(dict(it, status="review_cert_failed",
                                  name=it.get("name") or f"cert {it['cert']}",
                                  grade=it.get("grade", "")))
                continue
            spec = dict(r); spec["cert"] = it["cert"]
            # let caller fields (e.g. a cleaner name) override raw PSA text
            for k in ("name", "set", "number", "grade", "year", "market", "pc_id"):
                if it.get(k): spec[k] = it[k]
            specs.append(spec)
        else:
            specs.append(dict(it))

    # 2) classify each spec by type (graded / raw / sealed)
    for s in specs:
        s["_type"] = "graded" if s.get("status") else card_type(s)

    graded = [s for s in specs if s["_type"] == "graded" and not s.get("status")]
    rawsealed = [s for s in specs if s["_type"] in ("raw", "sealed")]

    # 3a) GRADED → eBay last-sold (one scrape pass), then price_item
    ebay_by_kw = {}
    if use_ebay and graded:
        kws = list(dict.fromkeys(
            k for k in (ebay_keyword(s.get("name", ""), s.get("set", ""),
                                     s.get("number", ""), s["grade"]) for s in graded) if k.strip()))
        if kws:
            try:
                from _ebay_chrome import fetch_or_cache
                ebay_by_kw = fetch_or_cache({k: k for k in kws})
            except SystemExit as e:
                print("[engine] eBay skipped:", e)            # no proxy → PC fallback
            except Exception as e:
                print("[engine] eBay error:", e)

    # 3b) RAW + SEALED → tcgsearch market (one Chrome session), unless caller pre-supplied it
    if use_ebay and rawsealed and any(not (s.get("ts_market") or s.get("market")) for s in rawsealed):
        try:
            from _tcgsearch_price import tcgsearch_market
            tcgsearch_market([s for s in rawsealed if not (s.get("ts_market") or s.get("market"))])
        except SystemExit as e:
            print("[engine] tcgsearch skipped:", e)
        except Exception as e:
            print("[engine] tcgsearch error:", e)

    # 4) price every spec by its route
    rows = []
    for s in specs:
        if s.get("status"):                                  # cert failed earlier
            rows.append(dict(s, market=None, cash=None, credit=None,
                             sources={}, confidence="low", type="graded"))
        elif s["_type"] == "graded":
            kw = ebay_keyword(s.get("name", ""), s.get("set", ""), s.get("number", ""), s.get("grade", ""))
            r = price_item(s, ebay_by_kw.get(kw)); r["type"] = "graded"
            rows.append(r)
        else:
            rows.append(price_raw_sealed(s, s["_type"]))

    # apply the "offer N% less than normal" multiplier to cash + credit (market stays true)
    if offer_mult and offer_mult != 1.0:
        for r in rows:
            for k in ("cash", "credit"):
                if r.get(k) is not None:
                    r[k] = round(r[k] * offer_mult, 2)

    if include_all:
        # accept anything with a usable price; only no-price rows stay in review.
        priced = lambda r: r.get("market") is not None and r.get("cash") is not None
        accepted = [r for r in rows if priced(r)]
        rejected = []
        review = [r for r in rows if not priced(r)]
    else:
        accepted = [r for r in rows if r["status"] == "ok"]
        rejected = [r for r in rows if r["status"] == "reject_under_100"]
        review = [r for r in rows if r["status"].startswith("review")]

    totals = {"market": round(sum(r["market"] for r in accepted), 2),
              "cash": round(sum(r["cash"] for r in accepted), 2),
              "credit": round(sum(r["credit"] for r in accepted), 2)}

    # 5) build the combined offer PDF — sections ordered Graded / Raw / Sealed
    html_path = pdf_path = None
    if build_pdf and accepted:
        order = [("graded", "Graded Slabs"), ("raw", "Raw Singles"), ("sealed", "Sealed")]
        sections = []
        for key, title in order:
            secrows = [r for r in accepted if r.get("type", "graded") == key]
            if secrows:
                sections.append({"title": title, "rows": secrows})
        # single-type offer keeps the clean no-subhead look
        data = sections[0]["rows"] if len(sections) == 1 else sections
        html_path, pdf_path = render(data, date=date, label=label, out_stem=out_stem, rating=rating)

    auto_ok = bool(accepted) and not review and not rejected
    summary = _summary(accepted, rejected, review, totals)

    # Nick-facing 1-10 BUY-QUALITY rating (INTERNAL — never on the seller reply/PDF). Blends how far
    # below market the cash offer sits with a liquidity estimate. When the caller already computed an
    # accurate liquidity (the Collectr flow passes `rating`), reuse it; otherwise estimate from the
    # priced rows (velocity signals we don't have here fall back to liquidity_score's conservative
    # defaults, so the number leans on the buy-margin we DO know). Wrapped so a rating hiccup can
    # never break an offer.
    deal_rating = deal_label_txt = liquidity_rating = None
    try:
        from _collectr_offer import liquidity_score, deal_score, deal_label
        if rating is not None:
            liq = rating
        elif accepted:
            _lq_raw = [dict(qty=r.get("qty", 1), market=r.get("market"), ts_market=r.get("market"),
                            is_sealed=(r.get("type") == "sealed"),
                            _ts_src=("tcgsearch" if r.get("market") else None))
                       for r in accepted if r.get("type") in ("raw", "sealed")]
            _lq_grd = [dict(qty=r.get("qty", 1), market=r.get("market"))
                       for r in accepted if r.get("type") == "graded"]
            liq = liquidity_score(_lq_raw, _lq_grd)
        else:
            liq = None
        if liq is not None:
            deal_rating = deal_score(totals, liq)
            deal_label_txt = deal_label(deal_rating)
            liquidity_rating = f"S{liq}"
    except Exception as e:
        print("[engine] deal-rating skipped:", e)

    return {"rows": rows, "accepted": accepted, "rejected": rejected, "review": review,
            "totals": totals, "auto_ok": auto_ok,
            "liquidity_rating": liquidity_rating,
            "deal_rating": deal_rating, "deal_label": deal_label_txt,
            "html_path": str(html_path) if html_path else None,
            "pdf_path": str(pdf_path) if pdf_path else None, "summary": summary}


def _summary(accepted, rejected, review, totals):
    parts = []
    if accepted:
        ng = sum(1 for r in accepted if r.get("type", "graded") == "graded")
        nr = sum(1 for r in accepted if r.get("type") == "raw")
        ns = sum(1 for r in accepted if r.get("type") == "sealed")
        mix = ", ".join(f"{c} {lbl}" for c, lbl in [(ng, "graded"), (nr, "raw"), (ns, "sealed")] if c)
        parts.append(f"{len(accepted)} item(s) [{mix}]: ${totals['cash']:,.2f} cash "
                     f"or ${totals['credit']:,.2f} store credit on ${totals['market']:,.2f} market")
    if rejected:
        parts.append(f"{len(rejected)} under-$100 (not accepted)")
    if review:
        why = ", ".join(sorted({r['status'].replace('review_', '') for r in review}))
        parts.append(f"{len(review)} need review ({why})")
    return " | ".join(parts) if parts else "no cards"


# ── CLI ──────────────────────────────────────────────────────────────────────
def _demo_items():
    # the verified 8-card lot, as STATED specs (no cert lookup / scrape needed)
    base = [
     ("Greninja ex (SIR)", "Twilight Masquerade", "214/167", "PSA 10", "2024", 930, "96312970"),
     ("Mew ex", "151 Ultra-Premium Coll. (SVP)", "053", "PSA 10", "2023", 900, "83631916"),
     ("Rayquaza GX (Full Art)", "Celestial Storm / Hidden Fates P.C.", "177a/168", "PSA 10", "2018", 875, "116488408"),
     ("Mewtwo", "151 Ultra-Premium Coll. (SVP)", "052", "PSA 10", "2023", 700, "94690245"),
     ("Mega Lucario ex (SIR)", "Mega Evolution", "179/132", "PSA 10", "2025", 540, "144574835"),
     ("Pikachu (Full Art Secret)", "Crown Zenith", "160/159", "PSA 10", "2023", 320, "106087735"),
     ("Pikachu (Full Art Secret)", "Crown Zenith", "160/159", "PSA 10", "2023", 320, "109419989"),
     ("Moltres & Zapdos & Articuno GX", "Hidden Fates ETB Promo", "SM210", "PSA 9", "2019", 170, "109438260"),
    ]
    return [dict(name=n, set=s, number=num, grade=g, year=y, market=mk, cert=c)
            for (n, s, num, g, y, mk, c) in base]


def main(argv):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: _offer_engine.py demo | certs <cert> [<cert> ...]"); return
    if argv[0] == "demo":
        res = make_offer(_demo_items(), use_ebay=False)   # use vetted overrides
    elif argv[0] == "certs":
        res = make_offer([{"cert": c} for c in argv[1:]])
    else:
        print("unknown mode:", argv[0]); return
    print("\n" + res["summary"])
    print("auto_ok:", res["auto_ok"])
    for r in res["rows"]:
        src = r.get("sources", {})
        print(f"  [{r['status']:18}] {str(r.get('name',''))[:26]:26} {r.get('grade',''):7} "
              f"mkt={('$%.2f' % r['market']) if r.get('market') else '—':>9} "
              f"ebay={src.get('ebay')} pc={src.get('pc')} conf={r.get('confidence')}")
    if res["pdf_path"]:
        print("PDF:", res["pdf_path"])


if __name__ == "__main__":
    main(sys.argv[1:])
