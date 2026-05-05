"""
Normalize the user's hand-typed Card Ladder import CSV into the canonical
17-column format CL expects when importing.

Input rows are mixed: most have 14 cols (short format); a few new entries
(like the Pikachu Art Rare row) use the full 16/17 col format. Output is
uniformly 17 cols with proper headers, ready to re-upload to Card Ladder.

Output: same folder as input, name "<input>_normalized.csv".
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

CL_HEADERS = [
    "Date Purchased", "Quantity", "Card", "Player", "Year", "Set",
    "Variation", "Number", "Category", "Condition", "Investment",
    "Current Value", "Potential Profit", "Ladder ID", "Slab Serial #",
    "Population", "Notes",
]


def apply_markup(base: float) -> int:
    """Same tiered markup the Square sync uses (user-mandated 2026-05-04 pm).
    Rounded to nearest integer ending in 0 or 5; ties round up."""
    if base <= 0:
        return 0
    if base < 200:
        marked = base * 1.15 + 3
    elif base < 1000:
        marked = base * 1.10 + 10
    else:
        marked = base * 1.08
    base_int = int(round(marked))
    cands = [n for n in range(max(1, base_int - 6), base_int + 7) if n % 5 == 0]
    cands.sort(key=lambda n: (abs(n - marked), -n))
    return cands[0] if cands else 0


def build_card_title(name: str, year: str, set_: str, number: str, condition: str) -> str:
    """Match the format CL uses for the 'Card' column when fully populated:
    '<year> <set> <name> #<num> <condition>' — falls back gracefully when
    a piece is missing."""
    parts = []
    if year: parts.append(year)
    if set_: parts.append(set_)
    if name: parts.append(name)
    if number: parts.append(f"#{number}")
    if condition: parts.append(condition)
    return " ".join(parts).strip()


def normalize_row(row: list[str]) -> list[str] | None:
    """Map input row (14, 16, or 17 columns) to the canonical 17-column form.
    Both short and full formats sometimes serialize to 16 cols due to trailing
    blanks, so format is detected by looking at position 3: a 4-digit year
    means short format (name at 2, year at 3); anything else means full
    format (title at 2, player at 3, year at 4)."""
    n = len(row)
    if n < 12:
        return None  # too sparse to be meaningful

    pos3 = (row[3] or "").strip() if n > 3 else ""
    is_short = bool(re.fullmatch(r"\d{4}", pos3))

    if is_short:
        # 0=Date(empty), 1=Qty, 2=Name, 3=Year, 4=Set, 5=Variation, 6=Number,
        # 7=Category, 8=Condition, 9=Investment, 10=duplicate-condition,
        # 11=Cert/SlabSerial, 12=CurrentValue, 13=SK/Notes
        date    = row[0]
        qty     = row[1] or "1"
        name    = row[2]
        year    = row[3]
        set_    = row[4] if n > 4 else ""
        variation = row[5] if n > 5 else ""
        number  = row[6] if n > 6 else ""
        category = (row[7] if n > 7 else "") or "Pokemon"
        condition = row[8] if n > 8 else ""
        investment = (row[9] if n > 9 else "") or "0"
        cert    = row[11] if n > 11 else ""
        cur_val = row[12] if n > 12 else ""
        sk      = row[13] if n > 13 else ""
    else:
        # Full format: 0=Date, 1=Qty, 2=Card title, 3=Player, 4=Year, 5=Set,
        # 6=Variation, 7=Number, 8=Category, 9=Condition, 10=Investment,
        # 11=CurrentValue, 12=PotentialProfit, 13=LadderId, 14=SlabSerial,
        # 15=Population, 16=Notes
        date    = row[0]
        qty     = row[1] or "1"
        name    = row[3] if n > 3 else ""
        year    = row[4] if n > 4 else ""
        set_    = row[5] if n > 5 else ""
        variation = row[6] if n > 6 else ""
        number  = row[7] if n > 7 else ""
        category = (row[8] if n > 8 else "") or "Pokemon"
        condition = row[9] if n > 9 else ""
        investment = (row[10] if n > 10 else "") or "0"
        cur_val = row[11] if n > 11 else ""
        cert    = row[14] if n > 14 else ""
        sk      = row[16] if n > 16 else ""

    if not name and not cert:
        return None

    title = build_card_title(name, year, set_, number, condition)
    # Current Value preserved as the user entered it — Card Ladder replaces it
    # with their market data when re-imported. Profit = Current Value − Investment.
    try:
        cur_f = float(cur_val) if cur_val else 0.0
        inv_f = float(investment or 0)
        profit_v = cur_f - inv_f
        profit_out = str(int(profit_v)) if profit_v == int(profit_v) else f"{profit_v:.2f}"
    except ValueError:
        profit_out = ""

    return [
        date, qty, title, name, year, set_, variation, number, category,
        condition, investment, cur_val, profit_out, "", cert, "", sk,
    ]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python _normalize_cardladder_csv.py <input.csv>"); return 1
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"file not found: {src}"); return 1
    dst = src.with_name(src.stem.rstrip(" ") + "_normalized.csv")

    out_rows: list[list[str]] = []
    with src.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row: continue
            norm = normalize_row(row)
            if norm is None:
                continue
            out_rows.append(norm)

    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(CL_HEADERS)
        for r in out_rows:
            w.writerow(r)

    print(f"wrote {len(out_rows)} normalized rows to {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
