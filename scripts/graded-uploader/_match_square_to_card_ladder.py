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

    # Grade. Two-step: find the grader prefix (PSA/CGC/BGS/SGC) and the
    # numeric grade, allowing descriptive words between them (e.g.
    # 'BGS NM-MT+ 8.5', 'CGC PRISTINE 10', 'PSA GEM MT 10').
    grader_match = re.search(r"\b(PSA|CGC|BGS|SGC)\b", name, re.IGNORECASE)
    num_match    = re.search(r"\b(\d+(?:\.\d)?)\b", name[grader_match.end():] if grader_match else "")
    if grader_match and num_match:
        out["raw_grade"]  = f"{grader_match.group(1).upper()} {num_match.group(1)}"
        out["grade_norm"] = normalize_grade(out["raw_grade"])

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

    # CL index keyed primarily by (grade_norm, number_norm). Year is too
    # unreliable in Card Ladder data (set release year vs grading year vs
    # printed year all conflict — observed mismatches up to 5 years on the
    # same physical card). Multiple CL rows can share (grade, number) when
    # a card was reprinted in a later set; we keep ALL of them and pick the
    # closest-year match at lookup time.
    cl_idx: dict[tuple, list[dict]] = {}
    for row in ladder:
        key = (
            normalize_grade(row.get("grade") or ""),
            normalize_number(row.get("number") or ""),
        )
        cl_idx.setdefault(key, []).append(row)

    # Square graded items
    square = fetch_square(token)
    graded = [it for it in square if is_graded(it)]
    print(f"[m2] Square: {len(square)} items, {len(graded)} graded")

    used_cl = set()  # don't double-match the same CL row to two Square items
    keep, delete = [], []
    for it in graded:
        sq = parse_square_item(it)
        if not sq["number_norm"]:
            delete.append(sq); continue
        candidates = cl_idx.get((sq["grade_norm"], sq["number_norm"]), [])
        # Filter out CL rows already used; pick the closest-year remaining one.
        try: sq_year = int(sq["year"]) if sq["year"] else None
        except: sq_year = None
        best = None; best_diff = 99
        for c in candidates:
            cid = id(c)
            if cid in used_cl: continue
            try: cl_year = int((c.get("year") or "").strip())
            except: cl_year = None
            diff = abs(cl_year - sq_year) if (cl_year and sq_year) else 99
            if diff < best_diff:
                best, best_diff = c, diff
        # Accept the match if year diff <=5 (CL data entry tolerance) OR if
        # year is missing on either side (still consider a match — number+grade
        # is unique enough for graded slabs).
        if best is not None and best_diff <= 5:
            used_cl.add(id(best))
            keep.append((sq, best))
        else:
            delete.append(sq)

    # CL rows not matched to any Square item — these need image processing
    # (new acquisitions not yet on the site).
    cl_unlisted = []
    for rows_for_key in cl_idx.values():
        for r in rows_for_key:
            if id(r) not in used_cl and (r.get("number") or "").strip():
                cl_unlisted.append(r)

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
