"""
Refresh the description on every graded Square listing by re-POSTing
through /admin/update-graded with the existing card metadata. The
worker rebuilds the description from scratch — so any stale text in
the old descriptions (e.g. the "Free shipping on orders $100+" line
that we dropped from the worker template) gets rewritten cleanly.

Reads the cert + metadata from pricing.csv and re-pushes via the
update endpoint with the same name/year/set/grade values, no
content change. Title and description both regenerate.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

WORKER_BASE = 'https://sakekitty-square.nwilliams23999.workers.dev'
ENDPOINT = f'{WORKER_BASE}/admin/update-graded'

HERE = Path(__file__).parent
PRICING = HERE / 'pricing.csv'

# Map grade strings in pricing.csv to (grader, grade-string) overrides
# for the ones we know shouldn't default to PSA. Any cert not listed
# here gets the worker's default 'PSA' grader.
GRADER_OVERRIDES = {
    '4321131035': 'CGC Pristine',
    '0014250139': 'BGS NM-MT+',
}


def update_one(cert: str, card: dict, token: str) -> dict:
    payload = {'cert': cert, 'card': card}
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
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {'http_error': e.code, 'body': e.read().decode('utf-8', errors='replace')}
    except Exception as e:
        return {'error': str(e)}


def main():
    token = os.environ.get('SK_ADMIN_TOKEN', '').strip()
    if not token:
        print('Set SK_ADMIN_TOKEN env var.')
        sys.exit(1)

    rows = []
    seen = set()
    with PRICING.open('r', encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            cert = (r.get('cert') or '').strip()
            if not cert or cert in seen:
                continue
            seen.add(cert)
            rows.append(r)

    print(f'Refreshing {len(rows)} graded descriptions…')
    ok = 0
    fail = 0
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        cert = r['cert'].strip()
        card = {
            'name':        r.get('name', ''),
            'year':        r.get('year', ''),
            'set_name':    r.get('set', ''),
            'card_number': r.get('number', ''),
            'grade':       r.get('grade', ''),
        }
        if cert in GRADER_OVERRIDES:
            card['grader'] = GRADER_OVERRIDES[cert]
        res = update_one(cert, card, token)
        if res.get('ok'):
            print(f'[{i}/{len(rows)}] {cert}  ok')
            ok += 1
        elif res.get('error') == 'item_not_found_for_cert' or res.get('http_error') == 404:
            print(f'[{i}/{len(rows)}] {cert}  not in Square (skip)')
        else:
            print(f'[{i}/{len(rows)}] {cert}  {res}')
            fail += 1
        time.sleep(0.3)

    print(f'\nDone in {time.time()-t0:.0f}s — {ok} updated, {fail} failed')


if __name__ == '__main__':
    main()
