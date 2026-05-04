"""
Coverage audit: cross-reference the PriceCharting CSV (every Pokemon card with
a TCGplayer productId) against the data the trade-in form can currently find.

The trade-in form's search sources are:
  - pokemontcg.io           — English Pokemon cards (live API, near-100% modern coverage)
  - assets/jp-cards.json    — Japanese cards from TCG CSV (29,278 entries as of 2026-05-04)

PriceCharting has a `tcg-id` column that maps cleanly to TCGplayer productId, so
we can ask: of all the cards PC knows about with a productId, which ones are
ALSO in our JP index? (English coverage we'll spot-check separately — pokemontcg.io
is a live API, can't bulk-test it cheaply.)

Output: prints gap counts + writes scripts/_coverage_gaps.json with the list of
PriceCharting rows that have a tcg-id but aren't in any of our search indexes,
so we can decide whether to extend the index.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
PRICECHARTING_CSV = Path(r"C:\Users\lunar\OneDrive\Desktop\vending_inventory\pricecharting_pokemon.csv")
JP_INDEX = REPO_DIR / "assets" / "jp-cards.json"
GAPS_OUT = REPO_DIR / "scripts" / "_coverage_gaps.json"


def main() -> None:
    if not PRICECHARTING_CSV.exists():
        print(f"PriceCharting CSV not found at {PRICECHARTING_CSV}")
        return

    # Load JP index productIds
    jp_pids: set[int] = set()
    if JP_INDEX.exists():
        for row in json.loads(JP_INDEX.read_text(encoding="utf-8")):
            pid = row[3] if len(row) >= 4 else None
            if isinstance(pid, int):
                jp_pids.add(pid)
    print(f"[audit] JP index has {len(jp_pids):,} productIds")

    # Walk PriceCharting; bucket by language hint (console-name contains "Japanese")
    en_total = 0
    en_with_pid = 0
    jp_total = 0
    jp_with_pid = 0
    jp_in_index = 0
    jp_gaps: list[dict] = []
    en_gaps: list[dict] = []  # all English with tcg-id — we'll check pokemontcg.io coverage separately

    with PRICECHARTING_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            console = (row.get("console-name") or "").strip()
            if "Pokemon" not in console:  # skip non-Pokemon rows if any
                continue
            tcg_id = (row.get("tcg-id") or "").strip()
            is_jp = "Japanese" in console

            if is_jp:
                jp_total += 1
                if tcg_id:
                    jp_with_pid += 1
                    pid_int = int(tcg_id) if tcg_id.isdigit() else None
                    if pid_int and pid_int in jp_pids:
                        jp_in_index += 1
                    else:
                        jp_gaps.append({
                            "console": console,
                            "name": (row.get("product-name") or "").strip(),
                            "tcg_id": tcg_id,
                            "loose_price": (row.get("loose-price") or "").strip(),
                        })
            else:
                en_total += 1
                if tcg_id:
                    en_with_pid += 1
                    en_gaps.append({
                        "console": console,
                        "name": (row.get("product-name") or "").strip(),
                        "tcg_id": tcg_id,
                    })

    print()
    print("=" * 70)
    print("ENGLISH coverage (vs pokemontcg.io — sampled, not bulk-tested)")
    print("=" * 70)
    print(f"  PriceCharting English Pokemon rows:          {en_total:>8,}")
    print(f"  English rows with TCGplayer productId:        {en_with_pid:>8,}")
    print(f"  -> these need a static fallback index for cards pokemontcg.io misses")
    print()
    print("=" * 70)
    print("JAPANESE coverage (vs assets/jp-cards.json)")
    print("=" * 70)
    print(f"  PriceCharting JP Pokemon rows:                 {jp_total:>8,}")
    print(f"  JP rows with TCGplayer productId:              {jp_with_pid:>8,}")
    print(f"  JP rows ALREADY in our index:                  {jp_in_index:>8,}")
    print(f"  JP rows with productId but NOT in our index:   {len(jp_gaps):>8,}  <- gaps")
    print()

    GAPS_OUT.write_text(
        json.dumps({"jp_gaps": jp_gaps, "en_with_pid": en_gaps}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[audit] gap detail written to {GAPS_OUT}")

    if jp_gaps:
        print()
        print("Sample JP gaps:")
        for g in jp_gaps[:10]:
            print(f"  - [{g['tcg_id']}] {g['console']} :: {g['name']}")


if __name__ == "__main__":
    main()
