"""
Build a compact English Pokemon card index for client-side search on
trade-in.html + grading-prep.html.

Sister of build_jp_card_index.py — same approach, categoryId 3 (English)
instead of 85 (Japanese). The site previously relied on pokemontcg.io as
the live EN search source, but pokemontcg.io has gaps (newer promos like
Victini #208, oddballs, some collab products) and rate-limits + paginates.
A static index of every TCGplayer-tracked EN card removes those gaps and
makes "show every Charizard variant" actually return every variant.

Output: assets/en-cards.json — array of [name, setName, number, productId, market].
Image URL is derived on the client via the standard TCGplayer CDN pattern.
Market price is the TCGplayer Market Price (or midPrice/lowPrice fallback).

Re-run after major set releases. The file is checked into git.

Usage:
    python scripts/build_en_card_index.py
"""
from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_DIR / "assets" / "en-cards.json"
PRICECHARTING_CSV = Path(r"C:\Users\lunar\OneDrive\Desktop\vending_inventory\pricecharting_pokemon.csv")

BASE = "https://tcgcsv.com/tcgplayer/3"  # categoryId 3 = English Pokemon
USER_AGENT = "Mozilla/5.0 SakeKittyCards-ENIndex/1.0 (sakekittycards.com)"
RATE_DELAY_SEC = 0.5

# Drop EN cards with TCGplayer market < this floor — same convention as
# build_jp_card_index.py and build_all_cards_index.py. Customer-facing
# guidance: "$3+ singles warrant individual review; sub-$3 flows into
# Quick-Add Flat-Rate Categories." Cards with no tracked price (market
# is None) are KEPT so brand-new releases still surface in search.
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
    # Jumbo / oversized cards (4x6"+) — not accepted at any tier per Sake Kitty
    # business rules (CLAUDE.md). Excluded from search so they don't surface
    # in the dropdown on either intake form.
    "jumbo",
]


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_pc_loose_by_pid() -> dict[int, float]:
    """Load PriceCharting CSV and build productId -> loose-price map.

    Used as a defense against TCGplayer Market Price suppression — TCG CSV
    can be wash-traded down on thin-volume cards (e.g. Mega Charizard X
    125/094 sat at $852 TCG market while obvious real value is $1,000+,
    visibly suppressed by clusters of $349/$447/$549 sales). PC's
    loose-price uses different methodology (eBay-anchored), harder to
    coordinate suppression on both sources simultaneously. We take the
    MAX of the two below.
    """
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


# Word-boundary check — same regex pattern the front-end uses, so 'tin'
# stops eating 'victini', 'etb' stops matching inside random product slugs.
import re
_SEALED_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in SEALED_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_sealed(name: str) -> bool:
    return bool(_SEALED_RE.search(name or ""))


def main() -> None:
    pc_loose_by_pid = load_pc_loose_by_pid()

    print(f"[build-en] hitting {BASE}/groups")
    groups_data = fetch_json(f"{BASE}/groups")
    groups = groups_data.get("results", [])
    print(f"[build-en] {len(groups)} groups")

    cards: list[list] = []
    pc_overlays = 0
    for i, g in enumerate(groups, 1):
        gid = g.get("groupId")
        gname = g.get("name") or ""
        try:
            products_data = fetch_json(f"{BASE}/{gid}/products")
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"[build-en] {i}/{len(groups)} {gname}: products fetch failed: {e}")
            time.sleep(RATE_DELAY_SEC)
            continue
        time.sleep(RATE_DELAY_SEC)
        try:
            prices_data = fetch_json(f"{BASE}/{gid}/prices")
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"[build-en] {i}/{len(groups)} {gname}: prices fetch failed: {e}")
            prices_data = {"results": []}

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
            # Multi-source max — defense against TCGplayer Market Price
            # suppression. PC loose-price uses different methodology, so
            # taking max() catches cards visibly suppressed on TCG (e.g.
            # Mega Charizard X 125/094 sat at $852 TCG market vs $1k+
            # actual value).
            pc_loose = pc_loose_by_pid.get(pid)
            if tcg_market is not None and pc_loose is not None:
                if pc_loose > tcg_market * 1.10:    # PC at least 10% higher = suppression suspected
                    market = pc_loose
                    pc_overlays += 1
                else:
                    market = tcg_market
            else:
                market = tcg_market if tcg_market is not None else pc_loose
            if market is not None and market < MARKET_FLOOR_USD:
                skipped_floor += 1
                continue
            market_rounded = round(market, 2) if market else None
            cards.append([pname, gname, number, pid, market_rounded])
            kept += 1

        print(f"[build-en] {i}/{len(groups)} {gname}: +{kept} cards "
              f"({len(price_by_pid)} priced, {skipped_floor} dropped < ${MARKET_FLOOR_USD:.2f})"
              f"  total {len(cards)}")
        time.sleep(RATE_DELAY_SEC)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(cards, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"[build-en] wrote {len(cards)} cards to {OUT_PATH}  ({size_kb:.1f} KB)")
    print(f"[build-en] PC-overlay applied to {pc_overlays:,} cards (PC loose > TCG market by 10%+)")


if __name__ == "__main__":
    main()
