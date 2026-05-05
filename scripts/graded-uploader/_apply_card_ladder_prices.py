"""
Apply the user-mandated graded markup to the Card Ladder collection CSV.

Markup tiers (Card Ladder Market Price = Base):
    Base < $200:    Price = Base * 1.22 + $5
    $200..$999:     Price = Base * 1.16 + $15
    Base >= $1000:  Price = Base * 1.12

Round to nearest clean number ending in 0, 5, or 9.

Inputs:
    C:\\Users\\lunar\\Downloads\\Collection - Card Ladder.csv
        Columns: Date Purchased, Quantity, Card, Player, Year, Set, Variation,
                 Number, Category, Condition, Investment, Current Value,
                 Potential Profit, Ladder ID, Slab Serial #, Population, Notes

Output:
    scripts/graded-uploader/_card_ladder_prices.csv
        Columns: sk_code, card_name, year, set, number, grade, base_value,
                 marked_up, final_price, name_for_match

The "name_for_match" column is the lower-cased "<name>|<year>|<set>|<grade>"
key the upload pipeline can join against pricing.csv. We don't have PSA cert
numbers in Card Ladder (Slab Serial # column is empty), so this is the bridge.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
CARD_LADDER_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder.csv")
OUT_PATH = Path(__file__).resolve().parent / "_card_ladder_prices.csv"


def markup(base: float) -> float:
    """Tiered markup (user-mandated 2026-05-04 evening, replaces earlier
    1.22/1.16/1.12 schedule). Lower fees + lower base markup."""
    if base < 200:
        return base * 1.15 + 3
    if base < 1000:
        return base * 1.10 + 10
    return base * 1.08


def snap_clean(price: float) -> int:
    """Round to the nearest integer ending in 0 or 5. Ties round up."""
    if price <= 0:
        return 0
    candidates: list[int] = []
    base = int(round(price))
    for n in range(max(1, base - 6), base + 7):
        if n % 5 == 0:
            candidates.append(n)
    candidates.sort(key=lambda n: (abs(n - price), -n))
    return candidates[0]


def normalize_set(s: str) -> str:
    return (s or "").strip().lower()


def normalize_name(s: str) -> str:
    return (s or "").strip().lower()


def normalize_grade(s: str) -> str:
    # Card Ladder gives "PSA 10"; pricing.csv has "GEMMT 10" / "GEM MT 10" etc.
    # We normalize to a single canonical form for join — strip whitespace,
    # lowercase, drop non-alpha-digit so "PSA 10" matches "PSA10" matches.
    return "".join(c for c in (s or "").lower() if c.isalnum())


def main() -> None:
    if not CARD_LADDER_CSV.exists():
        print(f"Card Ladder CSV not found at {CARD_LADDER_CSV}")
        return

    rows_in: list[dict] = []
    with CARD_LADDER_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows_in.append(r)

    out_rows: list[dict] = []
    skipped = 0
    for r in rows_in:
        try:
            base = float((r.get("Current Value") or "0").replace(",", "").strip() or "0")
        except ValueError:
            skipped += 1
            continue
        if base <= 0:
            skipped += 1
            continue
        marked = markup(base)
        final = snap_clean(marked)
        out_rows.append({
            "sk_code":     (r.get("Notes") or "").strip(),
            "card_name":   (r.get("Player") or "").strip(),
            "card_full":   (r.get("Card") or "").strip(),
            "year":        (r.get("Year") or "").strip(),
            "set":         (r.get("Set") or "").strip(),
            "variation":   (r.get("Variation") or "").strip(),
            "number":      (r.get("Number") or "").strip(),
            "grade":       (r.get("Condition") or "").strip(),
            "base_value":  f"{base:.2f}",
            "marked_up":   f"{marked:.2f}",
            "final_price": str(final),
            "name_for_match": "|".join([
                normalize_name(r.get("Player") or ""),
                (r.get("Year") or "").strip(),
                normalize_set(r.get("Set") or ""),
                normalize_grade(r.get("Condition") or ""),
            ]),
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else [])
        writer.writeheader()
        for row in out_rows:
            writer.writerow(row)

    # Quick summary by tier
    t1 = sum(1 for r in out_rows if float(r["base_value"]) < 200)
    t2 = sum(1 for r in out_rows if 200 <= float(r["base_value"]) < 1000)
    t3 = sum(1 for r in out_rows if float(r["base_value"]) >= 1000)
    print(f"[ladder] read {len(rows_in)} Card Ladder rows, priced {len(out_rows)} (skipped {skipped} with no value)")
    print(f"[ladder]   tier 1 (<$200):    {t1:>4} cards")
    print(f"[ladder]   tier 2 ($200-999): {t2:>4} cards")
    print(f"[ladder]   tier 3 (>=$1000):  {t3:>4} cards")
    print(f"[ladder] wrote {OUT_PATH}")
    print()
    print("Sample (first 8 priced rows):")
    print(f"  {'NAME':<28} {'YEAR':<5} {'GRADE':<8} {'BASE':>8}  ->  {'FINAL':>6}")
    for r in out_rows[:8]:
        print(f"  {r['card_name'][:28]:<28} {r['year']:<5} {r['grade']:<8} {float(r['base_value']):>8.2f}  ->  ${r['final_price']:>5}")


if __name__ == "__main__":
    main()
