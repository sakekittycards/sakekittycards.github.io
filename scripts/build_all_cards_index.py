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
    seen: set[str] = set()  # de-dupe by productId
    skipped_no_id = 0
    with PRICECHARTING_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            console = (r.get("console-name") or "").strip()
            if "Pokemon" not in console:
                continue
            tcg_id = (r.get("tcg-id") or "").strip()
            pc_id = (r.get("id") or "").strip()
            is_chinese = "Chinese" in console
            # Use TCGplayer productId when present (joins to /tcg/market /pricepoints
            # via the worker). For Chinese cards TCGplayer doesn't carry, fall back
            # to a "pc:<id>" synthetic key — these route straight to PC pricing on
            # the front-end since TCGplayer has no data for them.
            if tcg_id and tcg_id.isdigit():
                pid_str: str | int = int(tcg_id)
                key = str(pid_str)
            elif is_chinese and pc_id and pc_id.isdigit():
                pid_str = f"pc:{pc_id}"
                key = pid_str
            else:
                skipped_no_id += 1
                continue
            if key in seen:
                continue
            seen.add(key)
            name = (r.get("product-name") or "").strip()
            rows.append([name, console, pid_str])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"[build-all] wrote {len(rows):,} unique-by-productId entries to {OUT_PATH}")
    print(f"[build-all] file size: {size_kb:,.1f} KB raw")
    print(f"[build-all] {skipped_no_id:,} PC rows skipped (no productId AND not Chinese)")


if __name__ == "__main__":
    main()
