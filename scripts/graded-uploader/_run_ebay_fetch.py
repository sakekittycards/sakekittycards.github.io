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
    parts = [
        (row.get("year") or "").strip(),
        (row.get("set") or "").strip(),
        (row.get("card_name") or "").strip(),
        (row.get("number") or "").strip(),
        (row.get("grade") or "").strip(),
    ]
    q = " ".join(p for p in parts if p)
    # Strip Pokemon prefix (already implied by being a card search)
    q = re.sub(r"\bPokemon\s+", "", q, flags=re.I)
    # Trim 'Set Variation' artifact and weird CL truncations
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
