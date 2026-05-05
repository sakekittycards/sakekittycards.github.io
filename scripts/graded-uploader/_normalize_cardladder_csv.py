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
import sys
from pathlib import Path

CL_HEADERS = [
    "Date Purchased", "Quantity", "Card", "Player", "Year", "Set",
    "Variation", "Number", "Category", "Condition", "Investment",
    "Current Value", "Potential Profit", "Ladder ID", "Slab Serial #",
    "Population", "Notes",
]


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
    """Map input row (14 or 17 columns) to the canonical 17-column form."""
    n = len(row)
    if n < 12:
        return None  # too sparse to be meaningful

    if n == 14:
        # Short format observed in the user's CL imports:
        # 0=Date(empty), 1=Qty, 2=Name, 3=Year, 4=Set, 5=Variation, 6=Number,
        # 7=Category, 8=Condition, 9=Investment, 10=duplicate-condition,
        # 11=Cert/SlabSerial, 12=CurrentValue, 13=SK/Notes
        date    = row[0]
        qty     = row[1]
        name    = row[2]
        year    = row[3]
        set_    = row[4]
        variation = row[5]
        number  = row[6]
        category = row[7] or "Pokemon"
        condition = row[8]
        investment = row[9] or "0"
        cert    = row[11]
        cur_val = row[12]
        sk      = row[13]
    else:
        # Full format (16 or 17 cols, like the Pikachu Art Rare row):
        # 0=Date, 1=Qty, 2=Card title, 3=Player, 4=Year, 5=Set, 6=Variation,
        # 7=Number, 8=Category, 9=Condition, 10=Investment, 11=CurrentValue,
        # 12=PotentialProfit, 13=LadderId, 14=SlabSerial, 15=Population, 16=Notes
        date    = row[0]
        qty     = row[1]
        name    = row[3]
        year    = row[4]
        set_    = row[5]
        variation = row[6]
        number  = row[7]
        category = row[8] or "Pokemon"
        condition = row[9]
        investment = row[10] or "0"
        cur_val = row[11] if len(row) > 11 else ""
        cert    = row[14] if len(row) > 14 else ""
        sk      = row[16] if len(row) > 16 else ""

    if not name and not cert:
        return None

    title = build_card_title(name, year, set_, number, condition)
    try:
        profit = str(float(cur_val or 0) - float(investment or 0)) if cur_val else ""
    except ValueError:
        profit = ""
    if profit and profit.endswith(".0"):
        profit = profit[:-2]

    return [
        date, qty, title, name, year, set_, variation, number, category,
        condition, investment, cur_val, profit, "", cert, "", sk,
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
