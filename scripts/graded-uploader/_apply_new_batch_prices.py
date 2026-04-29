"""
After process_inbox.py finishes the new batch and pricing.csv has rows
for every cert, sync the prices from _new_batch_prices.csv (cert,price
two-column format from the user) into pricing-edit.csv. Then
upload_to_square.py picks up any unprefixed your_price values and
pushes the priced cards to Square.
"""
from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).parent
NEW_PRICES = HERE / '_new_batch_prices.csv'
EDIT_CSV   = HERE / 'pricing-edit.csv'
PRICING    = HERE / 'pricing.csv'


def load_new_prices() -> dict[str, str]:
    """Two-column cert,price CSV from the user's pricing list."""
    out: dict[str, str] = {}
    with NEW_PRICES.open('r', encoding='utf-8', newline='') as f:
        for row in csv.reader(f):
            if not row or not row[0].strip():
                continue
            cert = row[0].strip()
            price = row[1].strip() if len(row) > 1 else ''
            if cert and price:
                out[cert] = price
    return out


def update_edit_csv(prices: dict[str, str]) -> int:
    """Write user prices into pricing-edit.csv your_price column."""
    if not EDIT_CSV.exists():
        # Build pricing-edit.csv from pricing.csv if it doesn't exist —
        # process_inbox.py creates pricing-edit.csv too, but be safe.
        print(f'WARN: {EDIT_CSV.name} missing — running anyway will create it.')

    rows: list[dict] = []
    fieldnames: list[str] = []
    if EDIT_CSV.exists():
        with EDIT_CSV.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)

    if not rows:
        # Build from pricing.csv shape
        with PRICING.open('r', encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                rows.append({
                    'cert': r.get('cert', ''),
                    'name': r.get('name', ''),
                    'year': r.get('year', ''),
                    'set':  r.get('set', ''),
                    'grade': r.get('grade', ''),
                    'suggested_price_tcgplayer': r.get('suggested_price_tcgplayer', ''),
                    'your_price': r.get('your_price', ''),
                    'condition_note': r.get('condition_note', ''),
                    'offer_min': r.get('offer_min', ''),
                })
        fieldnames = ['cert', 'name', 'year', 'set', 'grade',
                      'suggested_price_tcgplayer', 'your_price',
                      'condition_note', 'offer_min']

    updated = 0
    for r in rows:
        cert = (r.get('cert') or '').strip()
        if cert in prices:
            current = (r.get('your_price') or '').strip()
            if current.startswith('[uploaded]'):
                continue
            if current != prices[cert]:
                r['your_price'] = prices[cert]
                updated += 1

    if updated:
        with EDIT_CSV.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return updated


def main():
    prices = load_new_prices()
    print(f'Loaded {len(prices)} cert→price entries from {NEW_PRICES.name}')
    n = update_edit_csv(prices)
    print(f'Updated {n} row(s) in {EDIT_CSV.name}')
    if n < len(prices):
        # Some certs in the price CSV aren't in pricing.csv yet — log them
        # so the user knows which cards still need to land via process_inbox.
        with PRICING.open('r', encoding='utf-8', newline='') as f:
            existing = {r.get('cert', '').strip() for r in csv.DictReader(f)}
        missing = [c for c in prices if c not in existing]
        if missing:
            print(f'\nNot in pricing.csv yet ({len(missing)} certs):')
            for c in missing:
                print(f'  {c}: {prices[c]}')
            print('Run process_inbox.py first (or rescan if certs are missing entirely).')


if __name__ == '__main__':
    main()
