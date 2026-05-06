"""Kick off the eBay sold-listings fetch for all 53 cards.

Builds a search query per card, starts an async Apify run with all 53
keywords, polls until done, and writes _ebay_data_dump.json with the
full per-card sold list (no last-5 limit) for downstream reasoning.
"""
from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

from _ebay_apify import fetch_apify

HERE = Path(__file__).parent
PRICES_CSV = HERE / "_card_ladder_prices.csv"
OUT_PATH = HERE / "_ebay_data_dump.json"


def build_query(row: dict) -> str:
    """Build eBay query from CL data. Uses the full CL `card_full` string,
    then surgically removes formatting artifacts that hurt eBay search:
      - 'Pokemon' prefix (redundant)
      - CL set abbreviation prefixes: 'Sv8-', 'Obf En-', 'Pre En-', 'Meg En-',
        'Paf En-', 'Sve En-', 'Svp En-', 'M2-' (CL internal codes)
      - ☆ character → 'Gold Star' (preserves meaning vs broken '?')
      - Bstr → Booster (CL abbreviation)
      - 'Alternate Full Art' / 'Alt Art' → 'FA' (eBay matches FA more)
      - Redundant repeats like "151 C-Collection 151"
      - Box-topper / variant verbose suffixes
    Preserves dots in grades (CGC 8.5 stays 8.5, doesn't become 8 5)."""
    full = (row.get("card_full") or "").strip()
    grade = (row.get("grade") or "").strip()

    if full:
        q = full
        if grade and grade.upper() not in q.upper():
            q = f"{q} {grade}"
    else:
        name = (row.get("card_name") or "").strip()
        number = (row.get("number") or "").strip()
        q = " ".join(p for p in (name, number, grade) if p)

    # Strip redundant Pokemon prefix
    q = re.sub(r"\bPokemon\s+", "", q, flags=re.I)
    # Strip CL set abbreviation prefixes
    q = re.sub(
        r"\b(Sv\d+a?|Obf En|Paf En|Pre En|Sve En|Svp En|Mev En|Meg En|M2)\s*[-\s]\s*",
        "", q, flags=re.I,
    )
    # Unicode artifacts
    q = q.replace("☆", "Gold Star").replace("?", "")
    # CL abbreviations
    q = re.sub(r"\bBstr\b", "Booster", q, flags=re.I)
    q = re.sub(r"\bAlternate Full Art\b|\bAlt Art\b", "FA", q, flags=re.I)
    # Redundant repeats: "151 C-Collection 151" → "151 C-Collection"
    q = re.sub(r"\b(\d+)\s+C[- ]?Collection\s+\1\b", r"\1 C-Collection", q, flags=re.I)
    # Drop "Box Topper" / "Enhanced Booster Box Topper" — too specific, eBay sellers omit it
    q = re.sub(r"\bEnhanced\s+Booster\s+Box\s+Topper\b", "Box Topper", q, flags=re.I)
    # Strip "POP Series N" — confuses search (Celebrations reprint mentions POP 5)
    q = re.sub(r"\bPOP Series \d+\b", "", q, flags=re.I)
    # Strip dashes (but NOT dots — dots in grades like "8.5" must survive)
    q = q.replace("-", " ")
    # Strip "#" before card numbers (some eBay sellers don't use it)
    q = q.replace("#", "")
    # Strip "Secret" — usually redundant with FA/SAR variant tags
    q = re.sub(r"\bSecret\b", "", q, flags=re.I)
    # Dedupe tokens globally (case-insensitive) — CL repeats set name within
    # card_full ("Vivid Voltage Fa / Pikachu Vmax Vivid Voltage"). Dedupe
    # while preserving order — first occurrence wins.
    tokens = q.split()
    seen: set[str] = set()
    deduped = []
    for tok in tokens:
        key = tok.lower().rstrip(",;:")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tok)
    q = " ".join(deduped)
    # Normalize whitespace
    q = re.sub(r"\s+", " ", q).strip()
    return q


def main() -> None:
    rows = list(csv.DictReader(PRICES_CSV.open("r", encoding="utf-8")))
    print(f"[ebay-fetch] {len(rows)} cards to query")

    queries: list[str] = []
    cert_to_query: dict[str, str] = {}
    for r in rows:
        cert = (r.get("cert") or "").strip()
        if not cert:
            continue
        q = build_query(r)
        queries.append(q)
        cert_to_query[cert] = q
        safe = q.encode("ascii", "replace").decode("ascii")
        print(f"  {cert:>12}  {safe}")

    unique_queries = list(dict.fromkeys(queries))
    print(f"\n[ebay-fetch] {len(unique_queries)} unique queries (deduped from {len(queries)})")
    print(f"[ebay-fetch] starting async Apify run; this may take 15-30 minutes...")

    started = time.time()
    grouped = fetch_apify(unique_queries, poll_interval=20, max_wait=2400)
    elapsed = time.time() - started

    if not grouped:
        print(f"[ebay-fetch] no data returned (run may have failed)")
        return

    # Map back to certs
    per_cert: dict[str, dict] = {}
    for cert, q in cert_to_query.items():
        items = grouped.get(q, [])
        per_cert[cert] = {
            "query": q,
            "items": items,
            "n_items": len(items),
        }

    OUT_PATH.write_text(json.dumps(per_cert, indent=2), encoding="utf-8")
    print(f"\n[ebay-fetch] elapsed: {elapsed:.0f}s")
    print(f"[ebay-fetch] wrote {OUT_PATH.name}")
    # Quick summary
    counts = sorted([(c, d["n_items"]) for c, d in per_cert.items()],
                    key=lambda x: x[1], reverse=True)
    print(f"[ebay-fetch] coverage:")
    print(f"  cards with >0 items: {sum(1 for _, n in counts if n > 0)}")
    print(f"  cards with 0 items:  {sum(1 for _, n in counts if n == 0)}")
    print(f"  median items/card:   {counts[len(counts)//2][1]}")


if __name__ == "__main__":
    main()
