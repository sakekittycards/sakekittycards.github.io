"""
Read the filled-out _missing_certs_template.csv (with metadata + price)
and the _missing_cert_to_imgs.json (built by _resolve_missing_certs.py).
For each cert: process the IMG pair through the pipeline into
finished/<slug>/, then POST /admin/upload-graded with the metadata +
the front+back as base64.

Mirrors upload_to_square.py's payload format but reads from the
template CSV instead of pricing.csv. After successful upload, appends
a row to pricing.csv so the catalog audit stays in sync.

Usage:
    SK_ADMIN_TOKEN=<token> python _upload_missing_certs.py
"""
from __future__ import annotations

import base64
import csv
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from process_card import process_one

WORKER_BASE = 'https://sakekitty-square.nwilliams23999.workers.dev'
ENDPOINT = f'{WORKER_BASE}/admin/upload-graded'

HERE = Path(__file__).parent
PROCESSED = HERE / 'inbox' / '_processed'
INBOX = HERE / 'inbox'
FINISHED = HERE / 'finished'


def find_img(name: str) -> Path | None:
    """Look for an IMG file in both inbox/ (loose) and inbox/_processed/."""
    for d in (PROCESSED, INBOX):
        p = d / name
        if p.exists():
            return p
    return None
PRICING = HERE / 'pricing.csv'
TEMPLATE = HERE / '_missing_certs_template.csv'
CERT_MAP = HERE / '_missing_cert_to_imgs.json'

CSV_COLUMNS = [
    'cert', 'year', 'set', 'name', 'number', 'grade',
    'suggested_price_tcgplayer', 'your_price', 'condition_note', 'offer_min',
    'front_image', 'back_image', 'pokemontcg_set_id', 'identified_at',
]


def slugify(s: str, fallback: str) -> str:
    s = re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-').lower()
    return s or fallback


def parse_price_to_cents(raw: str) -> int | None:
    s = (raw or '').strip().lstrip('$').replace(',', '')
    if not s or s.startswith('[uploaded]'):
        return None
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return None


def b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode('ascii')


def upload(card: dict, price_cents: int, front: Path, back: Path,
           token: str) -> dict:
    payload = {
        'card': {
            'cert_number':       card.get('cert'),
            'card_number':       card.get('number'),
            'name':              card.get('name'),
            'set_name':          card.get('set'),
            'year':              card.get('year'),
            'grade':             card.get('grade'),
            'grader':            card.get('grader') or 'PSA',
            'pokemontcg_set_id': '',
            'condition_note':    card.get('condition_note', ''),
        },
        'price_cents':         price_cents,
        'image_base64':        b64(front),
        'image_filename':      front.name,
        'back_image_base64':   b64(back),
        'back_image_filename': back.name,
    }
    req = urllib.request.Request(
        ENDPOINT, method='POST',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type':       'application/json',
            'X-Sake-Admin-Token': token,
            'User-Agent':
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0 Safari/537.36',
            'Accept':             'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {'http_error': e.code, 'body': e.read().decode('utf-8', errors='replace')}
    except Exception as e:
        return {'error': str(e)}


def append_pricing_row(card: dict, price_str: str, front_path: Path, back_path: Path):
    """Drop a row in pricing.csv so audit stays in sync."""
    row = {col: '' for col in CSV_COLUMNS}
    row.update({
        'cert':             card.get('cert', ''),
        'year':             card.get('year', ''),
        'set':              card.get('set', ''),
        'name':             card.get('name', ''),
        'number':           card.get('number', ''),
        'grade':            card.get('grade', ''),
        'your_price':       f'[uploaded]{price_str}',
        'front_image':      str(front_path),
        'back_image':       str(back_path),
        'identified_at':    datetime.now(timezone.utc).isoformat(timespec='seconds'),
    })
    new_file = not PRICING.exists()
    with PRICING.open('a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def main():
    token = os.environ.get('SK_ADMIN_TOKEN', '').strip()
    if not token:
        print('Set SK_ADMIN_TOKEN env var.')
        sys.exit(1)

    if not TEMPLATE.exists():
        print(f'Missing {TEMPLATE}')
        sys.exit(1)
    if not CERT_MAP.exists():
        print(f'Missing {CERT_MAP} — run _resolve_missing_certs.py first.')
        sys.exit(1)

    cert_to_imgs = json.loads(CERT_MAP.read_text(encoding='utf-8'))

    rows: list[dict] = []
    with TEMPLATE.open('r', encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))

    # Filter rows ready for upload: have price + at least 1 IMG mapped.
    ready: list[tuple[dict, list[str]]] = []
    skipped: list[str] = []
    for r in rows:
        cert = r.get('cert', '').strip()
        if not cert:
            continue
        price_cents = parse_price_to_cents(r.get('your_price', ''))
        if price_cents is None:
            skipped.append(f'{cert}: no price set')
            continue
        imgs = cert_to_imgs.get(cert, [])
        if len(imgs) < 2:
            skipped.append(f'{cert}: only {len(imgs)} IMG matches')
            continue
        ready.append((r, imgs))

    print(f'Ready to upload: {len(ready)} card(s)')
    if skipped:
        print(f'Skipping {len(skipped)}:')
        for s in skipped:
            print(f'  - {s}')
    if not ready:
        print('Nothing to do.')
        return

    for i, (row, imgs) in enumerate(ready, 1):
        cert = row['cert'].strip()
        front_src = find_img(imgs[0])
        back_src  = find_img(imgs[1])
        if not front_src or not back_src:
            print(f'[{i}/{len(ready)}] cert={cert}: source missing — looked for {imgs}')
            continue

        # Slug from name + cert. If name is blank, fall back to cert.
        name_slug = slugify(row.get('name', ''), 'graded-card')
        slug = f'{name_slug}-cert{cert}'
        out_dir = FINISHED / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f'\n[{i}/{len(ready)}] cert={cert}  {row.get("name", "?")}  ${row.get("your_price")}')
        print(f'  front: {front_src.name}  back: {back_src.name}')

        front_path = out_dir / f'{slug}-front.jpg'
        back_path  = out_dir / f'{slug}-back.jpg'
        try:
            front_out, palette = process_one(front_src, out_dir, out_name=front_path.name)
            back_out, _ = process_one(
                back_src, out_dir, out_name=back_path.name, palette_override=palette,
            )
        except Exception as e:
            print(f'  pipeline ERROR: {e}')
            continue

        price_cents = parse_price_to_cents(row.get('your_price', ''))
        res = upload(row, price_cents, front_out, back_out, token)
        if res.get('ok'):
            print(f'  uploaded  item={res.get("item_id")}  '
                  f'listing={res.get("listing_url", "?")}')
            append_pricing_row(row, row.get('your_price', ''), front_out, back_out)
        elif 'http_error' in res:
            print(f'  HTTP {res["http_error"]}: {res["body"][:200]}')
        else:
            print(f'  error: {res}')


if __name__ == '__main__':
    main()
