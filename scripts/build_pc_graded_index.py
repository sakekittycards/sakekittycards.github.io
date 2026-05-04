"""
Build assets/pc-graded.json — per-grade values keyed by TCGplayer productId.

Used by grading-prep.html to show "if this card grades to PSA X, here's the
market value and the profit margin after grading fees" inline on each card the
customer adds. PriceCharting is the right source here per the project pricing
policy (graded only; raw still uses TCGplayer-derived sources elsewhere).

Column mapping (verified 2026-05-02 against PC's web pages):
    loose-price          -> Ungraded
    new-price            -> PSA 8
    graded-price         -> PSA 9
    box-only-price       -> PSA 9.5 / BGS 9.5
    manual-only-price    -> PSA 10
    bgs-10-price         -> BGS 10
    condition-17-price   -> NOT PSA 10 (some CGC tier — ignore)
    condition-18-price   -> unknown — ignore

Output shape: { "<productId>": [ungraded, psa8, psa9, psa95, psa10, bgs10] }
All values in dollars. null entries for missing grades. Cards with no
productId or no usable prices are skipped entirely.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
PC_CSV = Path(r"C:\Users\lunar\OneDrive\Desktop\vending_inventory\pricecharting_pokemon.csv")
OUT_PATH = REPO_DIR / "assets" / "pc-graded.json"


def parse_price(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def main() -> None:
    if not PC_CSV.exists():
        print(f"PriceCharting CSV not found at {PC_CSV}")
        return

    out: dict[str, list] = {}
    skipped_no_pid = 0
    skipped_no_prices = 0
    with PC_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            console = (row.get("console-name") or "").strip()
            if "Pokemon" not in console:
                continue
            tcg_id = (row.get("tcg-id") or "").strip()
            if not tcg_id or not tcg_id.isdigit():
                skipped_no_pid += 1
                continue

            ungraded = parse_price(row.get("loose-price"))
            psa8     = parse_price(row.get("new-price"))
            psa9     = parse_price(row.get("graded-price"))
            psa95    = parse_price(row.get("box-only-price"))
            psa10    = parse_price(row.get("manual-only-price"))
            bgs10    = parse_price(row.get("bgs-10-price"))

            # Skip rows that have no usable graded prices at all — only ungraded
            # isn't useful here (the customer already knows it's ungraded).
            if not any((psa8, psa9, psa95, psa10, bgs10)):
                skipped_no_prices += 1
                continue

            out[tcg_id] = [ungraded, psa8, psa9, psa95, psa10, bgs10]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"[build-pc-graded] wrote {len(out):,} entries to {OUT_PATH}  ({size_kb:,.1f} KB)")
    print(f"[build-pc-graded] skipped {skipped_no_pid:,} (no tcg-id) + {skipped_no_prices:,} (no graded prices)")


if __name__ == "__main__":
    main()
