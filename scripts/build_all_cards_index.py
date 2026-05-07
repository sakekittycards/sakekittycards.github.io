"""
Build assets/all-cards-fallback.json — every Pokemon card PriceCharting knows
about that has a TCGplayer productId AND a loose-price >= MARKET_FLOOR.
Used by trade-in.html + grading-prep.html as a SEARCH-ONLY fallback when
pokemontcg.io (English primary) and assets/jp-cards.json (Japanese primary)
both return nothing for the customer's query.

Pricing for QUOTES is NEVER taken from PriceCharting per the project rule
(PC's loose-price diverges from TCGplayer's published Market Price). The
PC price is used here ONLY as a floor filter — when the customer picks a
card, /tcg/market on the worker still drives the actual quote.

The $3 floor was added 2026-05-07 per Nick: keeps the index clean of sub-bulk
cards that would clutter search results (most cards <$3 aren't worth the
grading-prep fee floor or the trade-in shipping anyway).

Index entries: [name, console, productId] — same compact array shape the
front-end search expects. Sealed products kept (sealed can be traded in too).
"""
from __future__ import annotations

import csv
import json
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
PRICECHARTING_CSV = Path(r"C:\Users\lunar\OneDrive\Desktop\vending_inventory\pricecharting_pokemon.csv")
PC_DOWNLOAD_URL_FILE = Path.home() / ".claude" / "pricecharting_csv_url.txt"
OUT_PATH = REPO_DIR / "assets" / "all-cards-fallback.json"

# Drop cards with PriceCharting loose-price below this floor. Aligned with
# the customer-facing guidance on trade-in.html: cards ~$5+ market typically
# warrant individual review; sub-$5 flows into the Quick-Add Flat-Rate
# Categories. Bumped 3 -> 5 on 2026-05-07 so the UX matches the helper text.
MARKET_FLOOR_USD = 5.00


def parse_pc_price(s: str) -> float | None:
    """PC CSV prices look like '$34.98' or '$1,234.00' or empty. Returns float or None."""
    s = (s or "").strip().lstrip("$").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fresh_pc_csv_path() -> Path:
    """Download a fresh PriceCharting CSV using the user's saved subscription
    URL (stored locally at ~/.claude/pricecharting_csv_url.txt, never committed),
    falling back to the existing on-disk CSV if the URL file is missing or the
    download fails. Returns the path to use."""
    if not PC_DOWNLOAD_URL_FILE.exists():
        if PRICECHARTING_CSV.exists():
            print(f"[pc] no download URL configured at {PC_DOWNLOAD_URL_FILE}; using existing CSV")
            return PRICECHARTING_CSV
        raise FileNotFoundError(
            f"No PC download URL at {PC_DOWNLOAD_URL_FILE} and no fallback CSV at {PRICECHARTING_CSV}."
        )
    url = PC_DOWNLOAD_URL_FILE.read_text(encoding="utf-8").strip()
    if not url.startswith("http"):
        if PRICECHARTING_CSV.exists():
            print(f"[pc] URL file content not a URL; using existing CSV")
            return PRICECHARTING_CSV
        raise ValueError(f"PC URL file at {PC_DOWNLOAD_URL_FILE} doesn't contain a URL.")
    print(f"[pc] downloading fresh CSV from PriceCharting...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SakeKittyCards-Index/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        # Overwrite the on-disk CSV so future scripts can use the same fresh copy.
        PRICECHARTING_CSV.write_bytes(data)
        size_mb = len(data) / 1024 / 1024
        print(f"[pc] downloaded {size_mb:.1f} MB to {PRICECHARTING_CSV}")
        return PRICECHARTING_CSV
    except Exception as e:
        print(f"[pc] download failed ({e}); falling back to existing CSV")
        if PRICECHARTING_CSV.exists():
            return PRICECHARTING_CSV
        raise


def main() -> None:
    csv_path = fresh_pc_csv_path()

    rows: list[list] = []
    seen: set[str] = set()  # de-dupe by productId
    skipped_no_id = 0
    skipped_below_floor = 0
    with csv_path.open("r", encoding="utf-8", newline="") as f:
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
            # $3 market floor — drop sub-bulk entries that clutter search.
            # Falls through to other price columns (cib, new) if loose is empty,
            # so a card without a tracked loose-price still gets a fair shot.
            loose = parse_pc_price(r.get("loose-price") or "")
            cib   = parse_pc_price(r.get("cib-price") or "")
            new_p = parse_pc_price(r.get("new-price") or "")
            best_price = max(p for p in [loose, cib, new_p, 0] if p is not None)
            if best_price < MARKET_FLOOR_USD:
                skipped_below_floor += 1
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
    print(f"[build-all] {skipped_below_floor:,} skipped below ${MARKET_FLOOR_USD:.2f} market floor")


if __name__ == "__main__":
    main()
