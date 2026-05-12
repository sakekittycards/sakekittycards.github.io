"""pop_and_profit.py — graded-inventory profitability + pop report.

For every slab in `manifests/graded_from_square.csv`:
  * Match it to a PriceCharting row via fuzzy (name, set, number) lookup
  * Report market price at every PSA tier (raw, 7, 8, 9, 9.5, 10), CGC 10,
    BGS 10, BGS Black Label
  * Compute profit at each grade vs the card's current grade & your_tcg_price,
    flagging which grades would have been (or still are) profitable
  * Stub pop columns so a follow-up `pop_fetch.py` can fill them in

PriceCharting Pokemon column mapping (authoritative, from site CLAUDE.md
verified 2026-05-02 — the column names are PC's generic CIB/new/etc. labels,
not Pokemon tier names):
    loose-price        -> Ungraded (raw)
    new-price          -> PSA 8
    graded-price       -> PSA 9
    box-only-price     -> PSA 9.5 / BGS 9.5
    manual-only-price  -> PSA 10
    bgs-10-price       -> BGS 10
CGC + SGC don't get separate columns; PC maps them to the PSA-equivalent
column. PSA 7 / 6 / lower aren't tracked by PC for Pokemon.
"""
from __future__ import annotations

import csv
import math
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Inventory + raw PriceCharting CSV live outside this repo, in the
# vending_inventory workspace where the build_manifest / Square sync runs.
VENDING = Path(r"C:\Users\lunar\OneDrive\Desktop\vending_inventory")
INVENTORY = VENDING / "manifests" / "graded_from_square.csv"
PRICECHARTING = VENDING / "pricecharting_pokemon.csv"
OUT = HERE / f"_pop_and_profit_report_{date.today().isoformat()}.csv"

# Assumption baseline. Tune in CLI if needed.
GRADING_COST = 30.0    # PSA Value tier + return ship per card
PROFIT_FLOOR = 25.0    # Below this, "profitable" is too thin to bother
HOLDING_COST = 0.0     # Already-graded; no additional cost to keep

# PC column -> our tier label (authoritative mapping from site CLAUDE.md)
PC_TIERS: list[tuple[str, str]] = [
    ("loose-price", "Raw"),
    ("new-price", "PSA 8"),
    ("graded-price", "PSA 9"),
    ("box-only-price", "PSA 9.5"),
    ("manual-only-price", "PSA 10"),
    ("bgs-10-price", "BGS 10"),
]

# Map a PSA grade string ("10", "9", "8", "8.5", "7", "6") to the tier label
# we should use for "current market" lookup. Half-grades floor to the nearest
# whole tier we track; <PSA 8 has no PC data (leave blank).
GRADE_TO_TIER = {
    "10": "PSA 10",
    "9.5": "PSA 9.5",
    "9": "PSA 9",
    "8.5": "PSA 9",   # 8.5s typically trade close to 9s
    "8": "PSA 8",
}


def parse_price(raw: str) -> float | None:
    if not raw:
        return None
    s = raw.replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def normalize(s: str) -> str:
    """Strip punctuation, lowercase, collapse whitespace."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_PRISTINE_HEAD = re.compile(r"^pristine\s+\d{4}\s+", re.IGNORECASE)


def strip_inv_name(name: str, set_name: str = "") -> str:
    """Remove 'Pristine YYYY <Set> ' leak prefix from Square titles.

    Uses the inventory's `set` field to know exactly what to strip after the
    'Pristine YYYY ' header.
    """
    s = _PRISTINE_HEAD.sub("", name)
    if s == name:
        return name
    # Strip the set name (case-insensitive) if it leads the remainder
    if set_name:
        sn = set_name.strip()
        if s.lower().startswith(sn.lower() + " "):
            s = s[len(sn) + 1:]
    return s


# Inventory set name -> likely PC console-name pattern. Best-effort; for misses
# we fall back to fuzzy substring match on the card-name token.
SET_HINTS: dict[str, list[str]] = {
    "sword and shield crown zenith": ["crown zenith"],
    "sword & shield: brilliant stars": ["brilliant stars"],
    "sword & shield: fusion strike": ["fusion strike"],
    "sword & shield: evolving skies": ["evolving skies"],
    "sword & shield evolving skies": ["evolving skies"],
    "sword & shield vivid voltage": ["vivid voltage"],
    "sun & moon shining legends": ["shining legends"],
    "sun & moon unified minds": ["unified minds"],
    "xy evolutions": ["evolutions"],
    "celebrations - classic coll.": ["celebrations"],
    "obf en-obsidian flames": ["obsidian flames"],
    "meg en-mega evolution": ["mega evolution"],
    "pre en-prismatic evolutions": ["prismatic evolutions"],
    "paf en-paldean fates": ["paldean fates"],
    "svp en-sv black star promo": ["pokemon promo"],
    "svp black star promos": ["pokemon promo"],
    "scarlet & violet: surging sparks": ["surging sparks"],
    "scarlet & violet promos japanese": ["japanese promo"],
    "gym heroes": ["gym heroes"],
    "neo genesis": ["neo genesis"],
    "neo destiny": ["neo destiny"],
    "go": ["pokemon go"],
    "game": ["base set", "jungle", "fossil"],  # 1998-99 ambiguous
    "black star promos": ["black star promos"],
    "premium trainer xy collection promo": ["roaring skies", "xy black star promos", "xy promo"],
    "black star promos": ["pokemon promo", "black star promos"],
    "neo genesis": ["neo genesis"],
    "japanese neo 2": ["japanese neo 2", "japanese neo"],
    "japanese neo 3": ["japanese neo 3", "japanese neo"],
    "japanese vending": ["japanese vending"],
    "japanese sword & shield shiny star v": ["japanese shiny star"],
    "japanese sword & shield vmax climax": ["japanese vmax climax"],
    "japanese sv1a-triplet beat": ["japanese triplet beat"],
    "japanese sv7a-paradise dragona": ["japanese paradise dragona"],
    "japanese sv8-super electric breaker": ["japanese super electric breaker"],
    "japanese sun & moon sky legend": ["japanese sky legend"],
    "card 151 japanese": ["japanese scarlet violet 151", "japanese 151"],
    "simplified chinese 151 c-collection 151": ["chinese 151"],
}


_SET_HINTS_NORM = {normalize(k): v for k, v in SET_HINTS.items()}


def candidate_consoles(inv_set: str) -> list[str]:
    key = normalize(inv_set)
    if key in _SET_HINTS_NORM:
        return _SET_HINTS_NORM[key]
    # Fallback: try the raw lowercased set string
    return [key]


VARIANT_SUFFIXES = ("jumbo", "prize pack", "staff", "winner", "champ", "stamp")


def match_pc_row(inv_row: dict, pc_rows: list[dict]) -> dict | None:
    """Match by set-hint console + number-first; tie-break on name overlap.

    Numbers stay as the inventory has them ("215", "087", "GG12") with a leading-
    zero variant tried too. Variants like [Jumbo] / [Prize Pack] in PC are
    de-prioritized when the inventory entry doesn't reference them.
    """
    raw_name = strip_inv_name(inv_row["name"], inv_row.get("set", ""))
    name = normalize(raw_name)
    number_full = (inv_row["number"] or "").strip().lower()
    # "5/111" -> "5"; "202/165" -> "202"; "77a" stays as-is
    number = number_full.split("/")[0]
    number_short = number.lstrip("0") or number
    name_tokens = [t for t in name.split() if len(t) >= 3]
    consoles = candidate_consoles(inv_row["set"])

    candidates: list[tuple[int, dict]] = []
    for pc in pc_rows:
        cn = normalize(pc.get("console-name", ""))
        pn_raw = pc.get("product-name", "")  # keep # for number anchoring
        pn = normalize(pn_raw)

        if not any(c in cn for c in consoles):
            continue

        score = 0
        num_match = False
        if number and re.search(rf"#{re.escape(number)}\b", pn_raw, re.IGNORECASE):
            score += 10
            num_match = True
        elif number_short and re.search(rf"#{re.escape(number_short)}\b", pn_raw, re.IGNORECASE):
            score += 9
            num_match = True

        for t in name_tokens:
            if t in pn:
                score += 2

        # Penalize variant suffixes that the inventory entry doesn't mention
        for suffix in VARIANT_SUFFIXES:
            if suffix in pn and suffix not in name:
                score -= 3

        # If we have a number match, accept on score >= 8 even without name.
        # If no number match, require name evidence (score >= 4).
        threshold = 8 if num_match else 4
        if score >= threshold:
            candidates.append((score, pc))

    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def load_pricecharting() -> list[dict]:
    with PRICECHARTING.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def tier_prices(pc: dict | None) -> dict[str, float | None]:
    if not pc:
        return {label: None for _, label in PC_TIERS}
    return {label: parse_price(pc.get(col, "")) for col, label in PC_TIERS}


def profitable_grades(prices: dict[str, float | None], your_price: float) -> list[tuple[str, float]]:
    """Return [(tier, net_profit_vs_your_price)] for tiers where profit >= floor.

    Compared against the card's current LIST price (your_tcg_price): if any
    alternate grade tier would yield more revenue than the listing, surface it.
    Net profit is `market - your_price` (no grading cost re-added since the
    slab is already in hand).
    """
    out = []
    for _, label in PC_TIERS:
        if label == "Raw":
            continue
        p = prices.get(label)
        if p is None:
            continue
        net = p - your_price
        if net >= PROFIT_FLOOR:
            out.append((label, net))
    return sorted(out, key=lambda x: -x[1])


def main():
    pc_rows = load_pricecharting()
    print(f"PriceCharting rows: {len(pc_rows):,}")

    inv_rows = list(csv.DictReader(INVENTORY.open("r", encoding="utf-8")))
    print(f"Inventory rows: {len(inv_rows)}")

    # Output columns
    cols = [
        "cert", "name", "set", "number", "grader", "grade", "your_tcg_price",
        "pc_matched",
        # Prices per tier
        *(f"price_{label.replace(' ', '_').lower()}" for _, label in PC_TIERS),
        # Profit analysis
        "current_tier_market", "current_tier_vs_list",
        "best_alt_tier", "best_alt_market", "best_alt_uplift",
        "profitable_tiers",
        # Pop columns (filled by pop_fetch.py)
        "psa_pop_current_grade", "psa_pop_psa10", "psa_pop_psa9", "pop_source",
        "notes",
    ]

    matched = 0
    rows_out = []
    for inv in inv_rows:
        pc = match_pc_row(inv, pc_rows)
        if pc:
            matched += 1
        prices = tier_prices(pc)

        try:
            your_price = float(inv.get("your_tcg_price") or 0)
        except ValueError:
            your_price = 0.0

        current_tier = GRADE_TO_TIER.get(inv["grade"], "")
        current_market = prices.get(current_tier) if current_tier else None
        current_vs_list = (current_market - your_price) if current_market is not None else None

        alts = profitable_grades(prices, your_price)
        # Exclude the current tier from "alt" suggestions
        alts = [(t, n) for t, n in alts if t != current_tier]
        best_alt = alts[0] if alts else (None, None)

        rows_out.append({
            "cert": inv["cert"],
            "name": inv["name"],
            "set": inv["set"],
            "number": inv["number"],
            "grader": inv["grader"],
            "grade": inv["grade"],
            "your_tcg_price": f"{your_price:.2f}",
            "pc_matched": "yes" if pc else "NO",
            **{
                f"price_{label.replace(' ', '_').lower()}":
                    f"{prices[label]:.2f}" if prices[label] is not None else ""
                for _, label in PC_TIERS
            },
            "current_tier_market": f"{current_market:.2f}" if current_market is not None else "",
            "current_tier_vs_list":
                f"{current_vs_list:+.2f}" if current_vs_list is not None else "",
            "best_alt_tier": best_alt[0] or "",
            "best_alt_market":
                f"{prices.get(best_alt[0]):.2f}" if best_alt[0] else "",
            "best_alt_uplift":
                f"{best_alt[1]:+.2f}" if best_alt[1] is not None else "",
            "profitable_tiers": "; ".join(f"{t} (+${n:.0f})" for t, n in alts),
            "psa_pop_current_grade": "",
            "psa_pop_psa10": "",
            "psa_pop_psa9": "",
            "pop_source": "",
            "notes": "" if pc else "no PriceCharting match",
        })

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows_out)

    print(f"\nMatched {matched}/{len(inv_rows)} inventory cards to PriceCharting")
    print(f"Output: {OUT}")
    print(f"\nNext step: run `python pop_fetch.py` to fill in PSA pop columns")


if __name__ == "__main__":
    main()
