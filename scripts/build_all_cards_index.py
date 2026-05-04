"""
Build assets/all-cards-fallback.json — every Pokemon card PriceCharting knows
about that has a TCGplayer productId. Used by trade-in.html as a SEARCH-ONLY
fallback when pokemontcg.io (English primary) and assets/jp-cards.json
(Japanese primary) both return nothing for the customer's query.

Pricing is NEVER taken from PriceCharting per the project rule (PC's loose-price
diverges from TCGplayer's published Market Price). The price flow is unchanged:
once the customer picks a card from this fallback, the productId is used to
hit /tcg/market on the worker, which returns TCGplayer's authoritative
marketPrice.

Index entries: [name, console, productId] — compact array form, no separate
sealed flag (sealed products can be traded in too, so we keep them).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
PRICECHARTING_CSV = Path(r"C:\Users\lunar\OneDrive\Desktop\vending_inventory\pricecharting_pokemon.csv")
OUT_PATH = REPO_DIR / "assets" / "all-cards-fallback.json"


def main() -> None:
    if not PRICECHARTING_CSV.exists():
        print(f"PriceCharting CSV not found at {PRICECHARTING_CSV}")
        return

    rows: list[list] = []
    seen: set[str] = set()  # de-dupe by tcg_id (some PC rows duplicate variant entries)
    skipped_no_tcg = 0
    with PRICECHARTING_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            console = (r.get("console-name") or "").strip()
            if "Pokemon" not in console:
                continue
            tcg_id = (r.get("tcg-id") or "").strip()
            if not tcg_id or not tcg_id.isdigit():
                skipped_no_tcg += 1
                continue
            if tcg_id in seen:
                continue
            seen.add(tcg_id)
            name = (r.get("product-name") or "").strip()
            rows.append([name, console, int(tcg_id)])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"[build-all] wrote {len(rows):,} unique-by-productId entries to {OUT_PATH}")
    print(f"[build-all] file size: {size_kb:,.1f} KB raw")
    print(f"[build-all] {skipped_no_tcg:,} PC rows skipped (no tcg-id)")


if __name__ == "__main__":
    main()
