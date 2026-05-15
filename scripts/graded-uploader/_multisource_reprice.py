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

from _ebay_apify import fetch_apify

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PRICING_CSV = HERE / "pricing.csv"
CL_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder (17).csv")
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
    if base < 200: return base * 1.15 + 3
    if base < 1000: return base * 1.10 + 10
    return base * 1.08


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


def build_ebay_keyword_from_cl(cl_row: dict, grade: str) -> str:
    """Build a focused eBay query from CL fields (Subject + Number + Set).
    NEVER from pricing.csv.name — that field carries forward pokemontcg.io
    misidentifications (e.g. cert 113090244 -> 'Sandile', actually a Rowlet/
    Exeggutor GX). Bad name = wrong eBay results = inflated avg = catastrophe.
    """
    subject = (cl_row.get("Subject") or "").strip()
    # Strip CL's "-Holo", "-Rev.foil", "-Reverse", "-Secret" shorthand suffixes
    subject = re.sub(r"-(Holo|Rev\.?\s*foil|Reverse|Secret)\b", "",
                     subject, flags=re.I).strip()
    number = (cl_row.get("Number") or "").strip()
    set_field = (cl_row.get("Set") or "").strip()
    set_clean = re.sub(r"^Pokemon\s+(Japanese\s+)?", "", set_field, flags=re.I).strip()
    set_short = " ".join(set_clean.split()[:3])
    parts = [grade, subject]
    if number:
        parts.append(f"#{number}" if not number.startswith("#") else number)
    if set_short:
        parts.append(set_short)
    return " ".join(p for p in parts if p)


def grade_matches_title(title: str, grade: str) -> bool:
    t = (title or "").upper().replace(".", "").replace(" ", "")
    g = grade.upper().replace(".", "").replace(" ", "")
    if g in t: return True
    if g == "PSA10" and ("GEMMT10" in t or "GEMMINT10" in t): return True
    if g.startswith("CGC10") and "CGC10" in t and "PRISTINE" in t: return True
    return False


def trimmed_avg(values: list[float], drop_pct: float = 0.1) -> float | None:
    if not values: return None
    vs = sorted(values)
    if len(vs) <= 3: return sum(vs) / len(vs)
    k = max(1, int(len(vs) * drop_pct))
    trimmed = vs[k:-k] if len(vs) > 2 * k else vs
    return sum(trimmed) / len(trimmed)


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

    print(f"[ms] Loaded: {len(cl_map)} CL rows, {len(pricing_rows)} pricing rows, {len(pc_index):,} PC entries")

    # First pass: build per-cert PC price + ebay keyword list
    cards: list[dict] = []
    keywords: list[str] = []
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
        # Try PC lookup
        pc_value = None
        try: pid = int(str(row.get("productId") or "0").strip() or "0")
        except ValueError: pid = 0
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

    # Fetch eBay sold via Apify in batches
    print(f"[ms] Fetching eBay sold for {len(keywords)} keywords (~5-15 min) ...")
    ebay_results = fetch_apify(keywords) if keywords else {}
    print(f"[ms] eBay results: {len(ebay_results)} keywords returned data")

    # Build final pricing
    token = get_token()
    if not token:
        print("[ms] WARNING: SK_ADMIN_TOKEN not set — will not push updates, just report.")

    report = []
    updates: list[tuple[str, int, dict]] = []
    for c in cards:
        cert = c["cert"]
        row = c["row"]
        if c.get("skip"):
            report.append({
                "cert": cert, "name": row.get("name", ""),
                "current": parse_current_price(row.get("your_price", "")),
                "cl_cv": "", "pc": "", "ebay_avg": "",
                "ebay_count": 0, "ebay_reject": "", "ebay_kw": "",
                "winner": "", "base": "", "new_price": "",
                "action": "skip",
                "reason": c.get("reason", "manual override"),
            })
            continue
        cl_cv = c["cl_cv"]
        pc_val = c["pc_value"]
        # eBay average — with mandatory guards (per 2026-05-12 incident)
        kw = c["ebay_kw"]
        ebay_items = ebay_results.get(kw, [])
        grade = normalize_grade(row.get("grade", ""))
        ebay_prices = []
        for it in ebay_items:
            title = it.get("title", "")
            if not grade_matches_title(title, grade): continue
            try: p = float(it.get("totalPrice") or it.get("soldPrice") or 0)
            except (TypeError, ValueError): continue
            if 1 < p < 100000: ebay_prices.append(p)

        ebay_count = len(ebay_prices)
        ebay_avg = None
        ebay_reject = ""
        # Guard 1: minimum sample size (need >=3 grade-matched comps)
        if ebay_count < 3:
            ebay_reject = f"need>=3 (got {ebay_count})"
        else:
            raw_avg = trimmed_avg(ebay_prices)
            # Guard 2: outlier filter — reject if eBay avg > 2x CL CV
            if raw_avg and cl_cv > 0 and raw_avg > 2 * cl_cv:
                ebay_reject = f"avg ${raw_avg:.0f} > 2x CL ${cl_cv:.0f}"
            else:
                ebay_avg = raw_avg

        # Pick max
        sources = [("CL", cl_cv)]
        if pc_val: sources.append(("PC", pc_val))
        if ebay_avg: sources.append(("EBAY", ebay_avg))
        winner_name, winner_val = max(sources, key=lambda x: x[1])
        new_price = snap_clean(markup(winner_val))
        cur_price = parse_current_price(row.get("your_price", "")) or 0

        # Policy: never lower an existing sticker — only push if higher.
        # Guard 3: sanity cap — don't auto-raise more than 2x in a single run.
        # Guard 4 (added 2026-05-15): tier-based raise threshold. A 2% bump on
        # a $3000 sticker reads as "chasing the market" to buyers even though
        # the dollars are noise. Require a meaningful move at higher tiers
        # before pushing a raise.
        #   under $200   -> raise on any formula bump
        #   $200..$999   -> need formula > current * 1.05
        #   $1000+       -> need formula > current * 1.10
        if cur_price > 0 and new_price > 2 * cur_price:
            action = "skip-sanity-cap-2x"
        elif new_price > cur_price:
            if cur_price >= 1000:
                threshold = cur_price * 1.10
            elif cur_price >= 200:
                threshold = cur_price * 1.05
            else:
                threshold = cur_price  # any raise OK in tier 1
            if new_price > threshold:
                action = "raise"
                updates.append((cert, new_price, c))
            else:
                action = "skip-below-tier-threshold"
        elif new_price == cur_price:
            action = "no-change"
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
            "winner":  winner_name,
            "base":    f"{winner_val:.2f}",
            "new_price": new_price,
            "action":  action,
            "reason":  "",
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
