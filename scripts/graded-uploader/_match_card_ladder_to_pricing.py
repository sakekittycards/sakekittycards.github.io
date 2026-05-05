"""
Cross-reference _card_ladder_prices.csv against pricing.csv (already-processed
cards with finished/ images) so we only re-process the truly NEW scans, not
re-do image work the user has already done.

For each row in _card_ladder_prices.csv (the priced Card Ladder collection):
  1. Build a normalized name|year|set|grade key
  2. Look for a match in pricing.csv (uses the same normalization)
  3. If matched: write the Card Ladder price into pricing.csv `your_price`
     column WITHOUT the [uploaded] prefix so upload_to_square.py picks it up.
     Reuses the existing finished/ images (no re-processing).
  4. If unmatched: flag for image processing (needs to come from inbox/ or
     a fresh scan).

Outputs:
  - pricing.csv updated in place (your_price column rewritten)
  - _ladder_match_report.txt with the matched/unmatched breakdown

Usage:
  python _match_card_ladder_to_pricing.py             # actually rewrites pricing.csv
  python _match_card_ladder_to_pricing.py --dry-run   # preview only
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICING_CSV   = HERE / "pricing.csv"
LADDER_CSV    = HERE / "_card_ladder_prices.csv"
REPORT_PATH   = HERE / "_ladder_match_report.txt"


_NAME_STOP_WORDS = {"with", "the", "a", "an", "of", "and", "or", "in", "on"}

def normalize_name(s: str) -> str:
    """Lowercase, drop non-alphanumeric so 'Charizard EX' == 'charizardex'."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

def name_tokens(s: str) -> set[str]:
    """Token set for fuzzy matching — split on non-alphanumeric, lowercase,
    drop common stop words. So 'Pikachu with Grey Felt Hat' ==
    'Pikachu Grey Felt Hat' and 'FA Charizard V' == 'Charizard V FA' (order
    doesn't matter, set equality wins)."""
    toks = {t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t}
    return {t for t in toks if len(t) > 1 and t not in _NAME_STOP_WORDS}

def names_match(a_tokens: set[str], b_tokens: set[str]) -> bool:
    """True iff the smaller token set is mostly contained in the larger.
    Allows one missing/extra token to absorb minor descriptive differences
    like Promo / Holo / Stamped / Rainbow / Secret."""
    if not a_tokens or not b_tokens:
        return False
    if a_tokens == b_tokens:
        return True
    smaller, larger = (a_tokens, b_tokens) if len(a_tokens) <= len(b_tokens) else (b_tokens, a_tokens)
    missing = smaller - larger
    return len(missing) <= 1


def normalize_set(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def normalize_grade(s: str) -> str:
    """Card Ladder gives 'PSA 10'; pricing.csv has 'GEMMT 10' / 'GEM MT 10' /
    'PSA 10' / etc. Normalize to (grader letters, numeric grade) tuple-like
    string so PSA10 == GEMMT10 (both PSA gem mint 10)."""
    s = (s or "").upper()
    # Pull the numeric grade (10, 9, 9.5, 8.5, etc.)
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    num = nums[0] if nums else ""
    # Detect grader prefix
    grader = ""
    if "BGS" in s: grader = "BGS"
    elif "CGC" in s: grader = "CGC"
    elif "SGC" in s: grader = "SGC"
    elif "PSA" in s or "GEM" in s or "MT" in s: grader = "PSA"
    return f"{grader}{num}"


def card_ladder_player_to_match(row: dict) -> str:
    """Build a name from Card Ladder's Card column when Player is empty
    (e.g. some rows have only the full name 'Mega Charizard X' in Card)."""
    if (row.get("card_name") or "").strip():
        return row["card_name"]
    full = (row.get("card_full") or "").strip()
    # 'Card' column is like '2023 Crown Zenith Galarian Gallery Deoxys #GG12 PSA 10'
    # Strip year prefix, set, '#NN' suffix, grade — leave just the player name.
    s = re.sub(r"^\d{4}\s+", "", full)
    s = re.sub(r"\s*#\S+.*$", "", s)
    return s.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not PRICING_CSV.exists():
        print(f"[match] {PRICING_CSV} not found"); return 1
    if not LADDER_CSV.exists():
        print(f"[match] {LADDER_CSV} not found — run _apply_card_ladder_prices.py first"); return 1

    # Load Card Ladder priced rows
    ladder = list(csv.DictReader(LADDER_CSV.open("r", encoding="utf-8")))
    print(f"[match] {len(ladder)} priced Card Ladder rows")

    # Load existing pricing.csv
    pricing_rows = list(csv.DictReader(PRICING_CSV.open("r", encoding="utf-8")))
    pricing_fields = list(pricing_rows[0].keys()) if pricing_rows else []
    print(f"[match] {len(pricing_rows)} existing pricing.csv rows")

    # Pre-compute pricing.csv normalized fields once
    pricing_norm = []
    used_pricing = set()  # don't match the same pricing row to two CL rows
    for r in pricing_rows:
        pricing_norm.append({
            "row":    r,
            "name":   normalize_name(r.get("name", "")),
            "tokens": name_tokens(r.get("name", "")),
            "year":   (r.get("year", "") or "").strip(),
            "set":    normalize_set(r.get("set", "")),
            "grade":  normalize_grade(r.get("grade", "")),
        })

    def find_match(cl_name: str, cl_tokens: set[str], cl_year: str, cl_set: str, cl_grade: str):
        """Multi-pass match. Each pass requires same grade.
        Pass 1: exact name + exact year + exact set
        Pass 2: exact name + year +-2 + set substring (either direction)
        Pass 3: name TOKEN-SET match + year +-2 + set substring
        Pass 4: name substring + year +-2 + set substring (last-ditch)
        """
        try:
            cl_year_int = int(cl_year)
        except Exception:
            cl_year_int = -1
        def year_close(p_year):
            try: return abs(int(p_year) - cl_year_int) <= 2
            except: return False
        def set_overlap(p_set):
            return bool(cl_set and p_set and (cl_set in p_set or p_set in cl_set))
        # Pass 1
        for i, p in enumerate(pricing_norm):
            if i in used_pricing: continue
            if p["grade"] != cl_grade: continue
            if p["name"] != cl_name: continue
            if p["year"] != cl_year: continue
            if p["set"] != cl_set:   continue
            used_pricing.add(i); return p["row"]
        # Pass 2: exact name, year fuzzy, set substring
        for i, p in enumerate(pricing_norm):
            if i in used_pricing: continue
            if p["grade"] != cl_grade: continue
            if p["name"] != cl_name: continue
            if not year_close(p["year"]): continue
            if set_overlap(p["set"]):
                used_pricing.add(i); return p["row"]
        # Pass 3: token-set name match (handles 'FA Charizard V' vs 'Charizard V FA')
        for i, p in enumerate(pricing_norm):
            if i in used_pricing: continue
            if p["grade"] != cl_grade: continue
            if not names_match(p["tokens"], cl_tokens): continue
            if not year_close(p["year"]): continue
            if set_overlap(p["set"]):
                used_pricing.add(i); return p["row"]
        # Pass 4: name substring last-ditch
        for i, p in enumerate(pricing_norm):
            if i in used_pricing: continue
            if p["grade"] != cl_grade: continue
            if not (cl_name in p["name"] or p["name"] in cl_name): continue
            if not year_close(p["year"]): continue
            if set_overlap(p["set"]):
                used_pricing.add(i); return p["row"]
        return None

    # Build cert-index for direct matching when Card Ladder has Slab Serial #.
    # Strip leading zeros — pricing.csv stores BGS certs zero-padded
    # (e.g., 0014250139) but Card Ladder strips them (14250139).
    def cert_key(s: str) -> str:
        return (s or "").strip().lstrip("0")

    cert_index: dict[str, int] = {}
    for i, p in enumerate(pricing_norm):
        ck = cert_key(p["row"].get("cert", ""))
        if ck:
            cert_index[ck] = i

    matched = []
    unmatched = []
    for lrow in ladder:
        # Pass 0: direct cert match (most reliable when CL has Slab Serial #)
        cl_cert = cert_key(lrow.get("cert", ""))
        if cl_cert and cl_cert in cert_index:
            i = cert_index[cl_cert]
            if i not in used_pricing:
                used_pricing.add(i)
                hit = pricing_norm[i]["row"]
                matched.append((lrow, hit))
                hit["your_price"] = lrow["final_price"]
                continue

        cl_name_raw = card_ladder_player_to_match(lrow)
        cl_name   = normalize_name(cl_name_raw)
        cl_tokens = name_tokens(cl_name_raw)
        cl_year   = (lrow.get("year") or "").strip()
        cl_set    = normalize_set(lrow.get("set") or "")
        cl_grade  = normalize_grade(lrow.get("grade") or "")
        hit = find_match(cl_name, cl_tokens, cl_year, cl_set, cl_grade)
        if hit:
            matched.append((lrow, hit))
            hit["your_price"] = lrow["final_price"]
        else:
            unmatched.append((lrow, f"cert={cl_cert} {cl_name}|{cl_year}|{cl_set}|{cl_grade}"))

    print(f"[match]   matched (will reuse existing images): {len(matched)}")
    print(f"[match]   unmatched (need fresh scan/process): {len(unmatched)}")

    # Write report
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        f.write(f"Card Ladder -> pricing.csv match report\n")
        f.write(f"=" * 70 + "\n")
        f.write(f"Card Ladder priced rows: {len(ladder)}\n")
        f.write(f"Matched (reuse existing processed images): {len(matched)}\n")
        f.write(f"Unmatched (need new scan or image processing): {len(unmatched)}\n\n")

        f.write("=== MATCHED (will be uploaded with existing images, new price) ===\n")
        for lrow, prow in matched:
            f.write(f"  ${lrow['final_price']:>5}  {prow.get('name','?'):<25} {prow.get('year','?'):<5} {prow.get('set','?')[:35]:<35} cert {prow.get('cert','?')}\n")

        f.write("\n=== UNMATCHED Card Ladder rows (need image processing) ===\n")
        for lrow, key in unmatched:
            name = card_ladder_player_to_match(lrow)
            f.write(f"  ${lrow['final_price']:>5}  {name:<25} {lrow.get('year',''):<5} {lrow.get('set','')[:35]:<35} ({lrow.get('grade','')})  key={key}\n")

    print(f"[match] report written to {REPORT_PATH}")

    if args.dry_run:
        print("[match] DRY RUN — pricing.csv NOT modified")
        return 0

    # Rewrite pricing.csv with updated your_price values
    with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=pricing_fields)
        writer.writeheader()
        for r in pricing_rows:
            writer.writerow(r)
    print(f"[match] pricing.csv updated — {len(matched)} rows have new prices")
    print(f"[match] next: run upload_to_square.py to push to Square")
    return 0


if __name__ == "__main__":
    sys.exit(main())
