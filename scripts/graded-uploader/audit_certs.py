"""
Audit the live Square catalog: pull every ITEM, parse the PSA/CGC/BGS
cert from its description, and report duplicates (same cert in >1
listing) plus any graded-looking items without a cert.

Hits GET /admin/inspect?types=ITEM on the worker, which is a thin
proxy over Square's /v2/catalog/list?types=ITEM. Pagination is handled
by re-calling with the cursor returned by Square.

Usage:
    SK_ADMIN_TOKEN=<token> python audit_certs.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{WORKER}/admin/inspect"

CERT_RE = re.compile(r'Cert\s*#?:?\s*([A-Za-z0-9]+)', re.IGNORECASE)


def fetch_items(token: str) -> list[dict]:
    """
    Square's /v2/catalog/list paginates with a `cursor` in each response.
    The worker's /admin/inspect just forwards a single page, so we
    paginate client-side by hitting the worker repeatedly with the cursor
    appended to the upstream request — which the worker doesn't support.

    Workaround: the inspect endpoint returns Square's full response
    including `cursor`. We can use it to build a worker URL that includes
    the cursor as part of the types param... but the worker URL-encodes
    types, which breaks. Simplest safe path: bail after the first page
    (Square defaults to 100 objects/page) and warn if the catalog has
    grown past one page so we know to revisit.
    """
    all_items: list[dict] = []
    cursor = None
    pages = 0
    while True:
        # Worker's /admin/inspect doesn't pass cursors through, but
        # Square's /v2/catalog/list defaults to 100 items per page and
        # the shop currently has well under that. If we ever exceed 100,
        # the loop below will detect the cursor and we'll need to extend
        # the worker to forward it.
        url = f"{INSPECT}?types=ITEM"
        if cursor:
            url += f"&cursor={urllib.parse.quote(cursor)}"
        req = urllib.request.Request(
            url, method='GET',
            headers={
                'X-Sake-Admin-Token': token,
                'User-Agent':
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0 Safari/537.36',
                'Accept': 'application/json',
            },
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        objs = d.get('objects', [])
        all_items.extend(o for o in objs if o.get('type') == 'ITEM')
        pages += 1
        cursor = d.get('cursor')
        if not cursor:
            break
        if pages >= 30:
            print(f'WARN: stopped pagination after {pages} pages (something looks off)')
            break
    return all_items


def cert_of(item: dict) -> str | None:
    desc = item.get('item_data', {}).get('description', '') or ''
    m = CERT_RE.search(desc)
    return m.group(1) if m else None


def main():
    token = os.environ.get('SK_ADMIN_TOKEN', '').strip()
    if not token:
        print('Set SK_ADMIN_TOKEN env var.')
        sys.exit(1)

    items = fetch_items(token)
    print(f'\nFetched {len(items)} ITEM objects from Square.\n')

    by_cert: dict[str, list[dict]] = defaultdict(list)
    no_cert: list[dict] = []
    for it in items:
        cert = cert_of(it)
        if cert:
            by_cert[cert].append(it)
        else:
            no_cert.append(it)

    dupes = {c: lst for c, lst in by_cert.items() if len(lst) > 1}

    if dupes:
        print(f'==== DUPLICATE CERTS ({len(dupes)}) ====')
        for cert, lst in sorted(dupes.items()):
            print(f'\ncert {cert}  ({len(lst)} listings)')
            for it in lst:
                name = it.get('item_data', {}).get('name', '?')
                iid  = it.get('id', '?')
                upd  = it.get('updated_at', '?')
                print(f'  - {iid}  {name}  (updated {upd})')
    else:
        print('==== No duplicate certs ====')

    print(f'\n==== Items without parseable cert ({len(no_cert)}) ====')
    for it in no_cert:
        name = it.get('item_data', {}).get('name', '?')
        iid  = it.get('id', '?')
        print(f'  - {iid}  {name}')

    # Cross-check against pricing.csv: anything in CSV but missing from
    # Square is suspicious; anything in Square but missing from CSV is
    # ungraded merch (plushies, sealed) and expected.
    csv_path = Path(__file__).parent / 'pricing.csv'
    if csv_path.exists():
        import csv
        with csv_path.open('r', encoding='utf-8', newline='') as f:
            csv_certs = {r['cert'].strip() for r in csv.DictReader(f) if r.get('cert', '').strip()}
        missing_in_square = csv_certs - set(by_cert.keys())
        if missing_in_square:
            print(f'\n==== In pricing.csv but NOT in Square ({len(missing_in_square)}) ====')
            for c in sorted(missing_in_square):
                print(f'  - {c}')
        else:
            print('\n==== Every cert in pricing.csv is present in Square ====')

    print(f'\nSummary: {len(items)} items / {len(by_cert)} unique certs / '
          f'{len(dupes)} dupe groups / {len(no_cert)} items without cert')


if __name__ == '__main__':
    main()
