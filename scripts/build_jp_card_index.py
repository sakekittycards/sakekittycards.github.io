"""
Build a compact Japanese Pokemon card name index for client-side search on
trade-in.html + grading-prep.html.

Why this exists: TCG CSV exposes JP Pokemon data per *group* (set), and our
existing JP search filters groups by name/abbreviation tokens. That works when
the user types a set hint ("Pikachu Promos", "151 Mew") but NOT when they type
just a character name ("Charizard") — JP set names don't contain card names,
so zero groups match and the search returns nothing. This script pre-builds a
flat array of every JP non-sealed product so the front-end can do an offline
substring search by card name.

Output: assets/jp-cards.json — array of [name, setName, number, productId, market].
Image URL is derivable on the client from the productId via the standard
TCGplayer CDN pattern (drops ~80 bytes per entry from the bundle). Market
price (single number, USD) is the TCGplayer Market Price for the product —
used as the dropdown anchor on Sell/Trade so customers see a value at-a-glance
instead of "No price". null when TCG CSV has no price entry for the productId.

Re-run when JP sets release (every few months) — the file is checked into git.

Usage:
    python scripts/build_jp_card_index.py
"""
from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_DIR / "assets" / "jp-cards.json"
PRICECHARTING_CSV = Path(r"C:\Users\lunar\OneDrive\Desktop\vending_inventory\pricecharting_pokemon.csv")

BASE = "https://tcgcsv.com/tcgplayer/85"  # categoryId 85 = JP Pokemon
USER_AGENT = "Mozilla/5.0 SakeKittyCards-JPIndex/1.0 (sakekittycards.com)"
RATE_DELAY_SEC = 0.5

# Drop JP cards with TCGplayer market < this floor — same convention used in
# build_all_cards_index.py. Aligned with the customer-facing "$3+ singles"
# guidance on trade-in.html (cards under ~$3 flow into the Quick-Add
# Flat-Rate Categories section instead of being individually searchable).
# Cards with no tracked price (market is None) are KEPT so obscure / new
# releases without prices yet still surface in search.
MARKET_FLOOR_USD = 3.00

# Same list trade-in.html / grading-prep.html use to filter sealed products
# out of card-grading flows. Sealed boxes/packs aren't gradeable.
SEALED_KEYWORDS = [
    "booster box", "booster display", "booster pack", "booster bundle",
    "sleeved booster", "blister",
    "elite trainer", "etb", "premium collection", "ultra premium", "upc",
    "collection box", "special collection", "premium playmat",
    "tin", "mini tin", "pin collection", "pin tin",
    "build & battle", "build and battle", "trainer kit", "theme deck",
    "battle deck", "league battle",
    "gift set", "deluxe", "display case", "case file", "stadium",
    "v box", "vmax box", "vstar box", "v battle",
    "starter set", "starter collection",
    # Jumbo / oversized cards (4x6"+) — not accepted at any tier.
    "jumbo",
]


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_sealed(name: str) -> bool:
    lower = (name or "").lower()
    return any(kw in lower for kw in SEALED_KEYWORDS)


def load_pc_loose_by_pid() -> dict[int, float]:
    """productId -> PC loose-price map. Used for max-overlay defense
    against TCG market suppression. See build_en_card_index.py for the
    full rationale (Mega Charizard X 125/094 $852 vs $1k+ true value)."""
    out: dict[int, float] = {}
    if not PRICECHARTING_CSV.exists():
        print(f"[pc] {PRICECHARTING_CSV} not found — skipping PC overlay")
        return out
    with PRICECHARTING_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            tcg_id = (r.get("tcg-id") or "").strip()
            if not tcg_id.isdigit():
                continue
            raw = (r.get("loose-price") or "").strip().lstrip("$").replace(",", "")
            if not raw:
                continue
            try:
                v = float(raw)
            except ValueError:
                continue
            out[int(tcg_id)] = v
    print(f"[pc] loaded {len(out):,} PC loose-prices for max-overlay")
    return out


def main() -> None:
    pc_loose_by_pid = load_pc_loose_by_pid()

    print(f"[build-jp] hitting {BASE}/groups")
    groups_data = fetch_json(f"{BASE}/groups")
    groups = groups_data.get("results", [])
    print(f"[build-jp] {len(groups)} groups")

    cards: list[list] = []
    pc_overlays = 0
    for i, g in enumerate(groups, 1):
        gid = g.get("groupId")
        gname = g.get("name") or ""
        try:
            products_data = fetch_json(f"{BASE}/{gid}/products")
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"[build-jp] {i}/{len(groups)} {gname}: products fetch failed: {e}")
            time.sleep(RATE_DELAY_SEC)
            continue
        time.sleep(RATE_DELAY_SEC)
        try:
            prices_data = fetch_json(f"{BASE}/{gid}/prices")
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"[build-jp] {i}/{len(groups)} {gname}: prices fetch failed: {e}")
            prices_data = {"results": []}

        # Build a productId -> best market price map. TCG CSV returns one
        # price entry per (productId, subType) — prefer marketPrice, then
        # midPrice, then lowPrice. Same fall-through getSealedMarketPrice uses.
        price_by_pid: dict[int, float] = {}
        for pr in prices_data.get("results", []):
            pid = pr.get("productId")
            if pid is None:
                continue
            mp = pr.get("marketPrice") or pr.get("midPrice") or pr.get("lowPrice")
            if mp and (pid not in price_by_pid or mp > price_by_pid[pid]):
                price_by_pid[pid] = float(mp)

        kept = 0
        skipped_floor = 0
        for p in products_data.get("results", []):
            pname = p.get("name") or ""
            if is_sealed(pname):
                continue
            number = ""
            for d in p.get("extendedData") or []:
                if d.get("name") == "Number":
                    number = str(d.get("value") or "")
                    break
            pid = p.get("productId")
            tcg_market = price_by_pid.get(pid)
            # Multi-source max — defense against TCGplayer suppression.
            # Same logic as build_en_card_index.py.
            pc_loose = pc_loose_by_pid.get(pid)
            if tcg_market is not None and pc_loose is not None:
                if pc_loose > tcg_market * 1.10:
                    market = pc_loose
                    pc_overlays += 1
                else:
                    market = tcg_market
            else:
                market = tcg_market if tcg_market is not None else pc_loose
            # $3 market floor — drop sub-bulk noise. Untracked cards (market
            # None) are KEPT so obscure / new releases without prices yet
            # still surface in search.
            if market is not None and market < MARKET_FLOOR_USD:
                skipped_floor += 1
                continue
            # Round to 2 decimal places as a number (not a string) to keep the
            # JSON tight — JSON.stringify will drop trailing zeros.
            market_rounded = round(market, 2) if market else None
            cards.append([pname, gname, number, pid, market_rounded])
            kept += 1

        print(f"[build-jp] {i}/{len(groups)} {gname}: +{kept} cards "
              f"({len(price_by_pid)} priced, {skipped_floor} dropped < ${MARKET_FLOOR_USD:.2f})"
              f"  total {len(cards)}")
        time.sleep(RATE_DELAY_SEC)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(cards, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"[build-jp] wrote {len(cards)} cards to {OUT_PATH}  ({size_kb:.1f} KB)")
    print(f"[build-jp] PC-overlay applied to {pc_overlays:,} cards")


if __name__ == "__main__":
    main()
