"""
Match Square graded items DIRECTLY to Card Ladder rows by (year, grade, number).

Why this exists: matching CL -> pricing.csv via name+set was missing real
cards because of abbreviation drift (CL 'SV Black Star Promos' vs pricing.csv
'Scarlet & Violet Black Star Promos'). (Year, grade, card number) is much more
discriminating — Pokemon cards within the same set never share a number, and
year + grade narrow it further.

Inputs:
  - Square inventory (live via /admin/inspect)
  - _card_ladder_prices.csv (output of _apply_card_ladder_prices.py)
  - pricing.csv (used to resolve cert numbers from Square item descriptions)

Outputs:
  - _square_match_report.txt: KEEP (price-update) vs DELETE (sold inventory)
  - On --apply: updates pricing.csv your_price for matched rows AND prints
    a final action manifest the executor script can consume.

Run with --dry-run to preview.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICING_CSV  = HERE / "pricing.csv"
LADDER_CSV   = HERE / "_card_ladder_prices.csv"
REPORT_PATH  = HERE / "_square_match_report.txt"
WORKER_BASE  = "https://sakekitty-square.nwilliams23999.workers.dev"


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
    except Exception: return None


def fetch_square(token: str) -> list[dict]:
    req = urllib.request.Request(
        f"{WORKER_BASE}/admin/inspect?types=ITEM",
        headers={"X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("objects", [])


def is_graded(it: dict) -> bool:
    data = it.get("item_data") or {}
    name = (data.get("name") or "").lower()
    desc = (data.get("description") or "").lower()
    if "cert #" in desc: return True
    return any(k in name for k in (" psa ", " cgc ", " bgs ", " sgc ")) \
        or name.startswith(("psa ", "cgc ", "bgs ", "sgc "))


def normalize_grade(s: str) -> str:
    s = (s or "").upper()
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    num = nums[0] if nums else ""
    grader = ""
    if "BGS" in s: grader = "BGS"
    elif "CGC" in s: grader = "CGC"
    elif "SGC" in s: grader = "SGC"
    elif "PSA" in s or "GEM" in s or "MT" in s: grader = "PSA"
    return f"{grader}{num}"


def normalize_number(s: str) -> str:
    """Strip whitespace/case, drop leading zeros within numeric pieces. Keep
    alpha prefixes (GG12 stays GG12, 087 -> 87, 199 -> 199, GG070 -> GG70)."""
    s = (s or "").strip().upper()
    # Split into alpha prefix + digit suffix; strip leading zeros from digits
    m = re.match(r"^([A-Z]*)(\d+)$", s)
    if m:
        return f"{m.group(1)}{int(m.group(2))}"
    # Keep slash format ("170/198" stays as-is, normalize whitespace only)
    return re.sub(r"\s+", "", s)


def parse_square_item(it: dict) -> dict:
    """Extract {cert, name, year, grade_norm, number_norm} from a Square item."""
    data = it.get("item_data") or {}
    name = data.get("name", "")
    desc = data.get("description", "")
    out = {"id": it.get("id"), "name": name, "cert": None, "year": "", "grade_norm": "",
           "number_norm": "", "raw_grade": ""}

    # Cert from description
    m = re.search(r"Cert #:\s*(\d+)", desc)
    if m: out["cert"] = m.group(1)

    # Year (4-digit)
    m = re.search(r"\b(19\d{2}|20\d{2})\b", name)
    if m: out["year"] = m.group(1)

    # Grade (PSA 10, CGC 10, BGS 9.5, etc.)
    m = re.search(r"(PSA|CGC|BGS|SGC|PRISTINE|GEMMT|GEM\s*MT|NM-MT)\s*(\d+(?:\.\d)?)", name, re.IGNORECASE)
    if m:
        out["raw_grade"] = m.group(0)
        out["grade_norm"] = normalize_grade(m.group(0))

    # Card number — '#NN' suffix anywhere
    m = re.search(r"#([A-Za-z]*\d+(?:/\d+)?)", name)
    if m: out["number_norm"] = normalize_number(m.group(1))

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply",   action="store_true",
                    help="Write pricing.csv your_price for matched cards")
    args = ap.parse_args()

    token = get_token()
    if not token: print("[m2] SK_ADMIN_TOKEN not set"); return 1

    if not LADDER_CSV.exists(): print(f"[m2] {LADDER_CSV} not found"); return 1
    ladder = list(csv.DictReader(LADDER_CSV.open("r", encoding="utf-8")))
    print(f"[m2] {len(ladder)} CL priced rows")

    # CL index keyed by (year, grade_norm, number_norm)
    cl_idx: dict[tuple, dict] = {}
    for row in ladder:
        key = (
            (row.get("year") or "").strip(),
            normalize_grade(row.get("grade") or ""),
            normalize_number(row.get("number") or ""),
        )
        cl_idx.setdefault(key, row)

    # Square graded items
    square = fetch_square(token)
    graded = [it for it in square if is_graded(it)]
    print(f"[m2] Square: {len(square)} items, {len(graded)} graded")

    keep, delete = [], []
    for it in graded:
        sq = parse_square_item(it)
        key = (sq["year"], sq["grade_norm"], sq["number_norm"])
        cl_row = cl_idx.get(key)
        if cl_row and sq["number_norm"]:
            keep.append((sq, cl_row))
        else:
            delete.append(sq)

    # Also surface CL rows that aren't on Square (need image processing later)
    matched_keys = {(it[0]["year"], it[0]["grade_norm"], it[0]["number_norm"]) for it in keep}
    cl_unlisted = []
    for k, row in cl_idx.items():
        if k not in matched_keys and k[0] and k[2]:  # require year + number
            cl_unlisted.append(row)

    print(f"[m2]   keep on Square + price-update: {len(keep)}")
    print(f"[m2]   delete from Square (not in CL): {len(delete)}")
    print(f"[m2]   CL rows NOT on Square (need image processing later): {len(cl_unlisted)}")

    # Report
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        f.write(f"Square <-> Card Ladder match (key: year, grade, number)\n")
        f.write("=" * 72 + "\n\n")
        f.write(f"=== KEEP & UPDATE PRICE ({len(keep)}) ===\n")
        for sq, cl in keep:
            f.write(f"  cert {sq['cert'] or '?'}  ${cl['final_price']:>5}  {sq['name'][:80]}\n")
        f.write(f"\n=== DELETE FROM SQUARE ({len(delete)}) ===\n")
        for sq in delete:
            f.write(f"  cert {sq['cert'] or '?'}  yr={sq['year']} grade={sq['grade_norm']} num={sq['number_norm']}  {sq['name'][:80]}\n")
        f.write(f"\n=== CL NOT ON SQUARE ({len(cl_unlisted)}) — NEEDS IMAGE PROCESSING ===\n")
        for r in cl_unlisted:
            name = r.get("card_name") or r.get("card_full") or "?"
            f.write(f"  ${r['final_price']:>5}  {name[:30]:<30} {r.get('year',''):<5} {r.get('set','')[:35]:<35} #{r.get('number','?')} ({r.get('grade','')})\n")
    print(f"[m2] report written to {REPORT_PATH}")

    if args.apply:
        # Update pricing.csv your_price for matched rows (by cert)
        if not PRICING_CSV.exists(): print(f"[m2] {PRICING_CSV} not found"); return 1
        rows = list(csv.DictReader(PRICING_CSV.open("r", encoding="utf-8")))
        fields = list(rows[0].keys()) if rows else []
        pricing_by_cert = {(r.get("cert") or "").strip(): r for r in rows}
        n_updated = 0
        for sq, cl in keep:
            cert = sq.get("cert")
            if not cert: continue
            pr = pricing_by_cert.get(cert)
            if pr:
                pr["your_price"] = cl["final_price"]
                n_updated += 1
        with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows: w.writerow(r)
        print(f"[m2] pricing.csv updated — {n_updated} rows have new prices")

    if args.dry_run:
        print("[m2] DRY RUN — no Square changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
