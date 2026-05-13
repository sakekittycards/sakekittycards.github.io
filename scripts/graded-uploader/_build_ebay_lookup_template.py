"""
Build a CSV template the user can fill in by hand.

For each cert in pricing.csv, produces a row with:
  cert, card, grade, sticker, cl_cv, ebay_search_url,
  lowest_ebay_listing, notes

The user opens each `ebay_search_url`, copies the lowest BIN listing price
into `lowest_ebay_listing`, optionally adds context to `notes`, then saves
the file. Companion script `_apply_ebay_overrides.py` reads it back and
adjusts stickers per the user's call.

eBay search URLs are pre-filtered: Buy It Now only, US sellers, sorted
price+shipping ascending, 60 results per page.
"""
from __future__ import annotations

import csv
import datetime
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICING_CSV = HERE / "pricing.csv"
CL_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder (10).csv")
OUT = HERE / f"_ebay_lookup_template_{datetime.date.today().isoformat()}.csv"


def load_cl(path: Path) -> dict[str, float]:
    out = {}
    if not path.exists(): return out
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cert = (row.get("Graded Cert #") or "").strip()
            try: cv = float((row.get("Current Value") or "0").replace(",", "").strip() or "0")
            except ValueError: cv = 0.0
            if cert: out[cert] = cv
    return out


def parse_price(raw: str) -> float | None:
    if not raw: return None
    s = raw.strip()
    if s.startswith("[uploaded]"): s = s[len("[uploaded]"):]
    s = s.lstrip("$").replace(",", "").strip()
    try: return float(s) if s else None
    except ValueError: return None


def normalize_grade(grade: str) -> str:
    g = (grade or "").strip().upper()
    m = re.match(r"(PSA|CGC|BGS|SGC)\s*\.?\s*([0-9]+(?:\.[0-9])?)\s*(PRISTINE)?", g)
    if m:
        grader, num, prist = m.group(1), m.group(2), m.group(3)
        if grader == "CGC" and (prist or num == "10"):
            return f"CGC {num} Pristine" if prist else f"CGC {num}"
        return f"{grader} {num}"
    if "GEMMT 10" in g or "GEM MT 10" in g: return "PSA 10"
    return g


def build_query(row: dict) -> str:
    grade = normalize_grade(row.get("grade", ""))
    name = (row.get("name") or "").strip()
    number = (row.get("number") or "").strip()
    set_field = (row.get("set") or "").strip()
    set_clean = re.sub(r"^(Pokemon\s+(Japanese\s+)?(En-|Jp-|Cn-)?)", "", set_field, flags=re.I).strip()
    set_short = " ".join(set_clean.split()[:4])
    parts = [grade, name]
    if number:
        parts.append(f"#{number}" if not number.startswith("#") else number)
    if set_short:
        parts.append(set_short)
    return " ".join(p for p in parts if p)


def ebay_search_url(query: str) -> str:
    qs = urllib.parse.urlencode({
        "_nkw":  query,
        "_sop":  15,        # price + shipping: lowest first
        "LH_BIN": 1,        # Buy It Now only
        "LH_PrefLoc": 1,    # US-based listings
        "_ipg":  60,
    })
    return f"https://www.ebay.com/sch/i.html?{qs}"


def main() -> None:
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    cl = load_cl(CL_CSV)
    with PRICING_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    for row in rows:
        cert = (row.get("cert") or "").strip()
        if not cert: continue
        sticker = parse_price(row.get("your_price", ""))
        cv = cl.get(cert, 0.0)
        grade = normalize_grade(row.get("grade", ""))
        card_desc = (f"{row.get('year','')} {row.get('set','')} {row.get('name','')} "
                     f"#{row.get('number','')}").strip()
        query = build_query(row)
        out_rows.append({
            "cert":   cert,
            "card":   card_desc,
            "grade":  grade,
            "sticker": f"{sticker:.0f}" if sticker is not None else "",
            "cl_cv":   f"{cv:.2f}" if cv else "",
            "ebay_search_url": ebay_search_url(query),
            "lowest_ebay_listing": "",   # <-- user fills in
            "notes":               "",   # <-- optional user note
        })

    # Sort by sticker descending so the biggest-ticket cards are at the top —
    # easiest to spot-check first.
    def sort_key(r):
        try: return -float(r["sticker"]) if r["sticker"] else 0
        except ValueError: return 0
    out_rows.sort(key=sort_key)

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {len(out_rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
