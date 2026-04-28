"""
Push the freshly-reprocessed images for EVERY graded cert in pricing.csv
into Square via /admin/replace-graded-images. Idempotent — re-runs
just push the latest finished JPEGs again. Safe to run after both
round 3 (the original 5) and round 4 (everyone else) have completed.

Usage:
    SK_ADMIN_TOKEN=<token> python _replace_all_graded.py
    SK_ADMIN_TOKEN=<token> python _replace_all_graded.py --only=102607615,135860324
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
ENDPOINT = f"{WORKER}/admin/replace-graded-images"

HERE = Path(__file__).parent
PRICING = HERE / 'pricing.csv'


def b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode('ascii')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='comma-separated cert numbers to push (skip others)')
    args = ap.parse_args()

    only = set()
    if args.only:
        only = {c.strip() for c in args.only.split(',') if c.strip()}

    token = os.environ.get('SK_ADMIN_TOKEN', '').strip()
    if not token:
        print('Set SK_ADMIN_TOKEN env var.')
        sys.exit(1)

    rows: list[dict] = []
    with PRICING.open('r', encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            cert = (r.get('cert') or '').strip()
            front = (r.get('front_image') or '').strip()
            back  = (r.get('back_image') or '').strip()
            if not cert or not front:
                continue
            if only and cert not in only:
                continue
            rows.append({'cert': cert, 'front': Path(front), 'back': Path(back)})

    print(f'Pushing {len(rows)} card(s) via {ENDPOINT}')
    t0 = time.time()
    ok = 0
    fail = 0
    for i, row in enumerate(rows, 1):
        cert = row['cert']
        front = row['front']
        back  = row['back']
        if not front.exists():
            print(f'[{i}/{len(rows)}] cert={cert}: front missing — skip')
            fail += 1
            continue
        payload = {
            'cert':            cert,
            'image_base64':    b64(front),
            'image_filename':  front.name,
        }
        if back.exists():
            payload['back_image_base64']   = b64(back)
            payload['back_image_filename'] = back.name

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
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
                print(f'[{i}/{len(rows)}] cert={cert}  OK  item={d.get("item_id")}  '
                      f'deleted={len(d.get("deleted_old_image_ids", []))}')
                ok += 1
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:200]
            print(f'[{i}/{len(rows)}] cert={cert}  HTTP {e.code}: {body}')
            fail += 1
        except Exception as e:
            print(f'[{i}/{len(rows)}] cert={cert}  ERROR: {e}')
            fail += 1

    print(f'\nDone in {time.time()-t0:.0f}s — {ok} OK, {fail} failed')


if __name__ == '__main__':
    main()
