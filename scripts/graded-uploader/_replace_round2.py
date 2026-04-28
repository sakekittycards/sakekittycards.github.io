"""
Round 2 image push: after _reprocess_round2.py regenerates Pikachu Van
Gogh #2 + Wobbuffet with the bottom-plastic margin fix, hit the worker's
/admin/replace-graded-images for each so Square shows the new crop.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
ENDPOINT = f"{WORKER}/admin/replace-graded-images"

FINISHED = Path(__file__).parent / 'finished'

JOBS = [
    {'cert': '102607615', 'slug': 'pikachu-with-grey-felt-hat-cert102607615'},
    {'cert': '135860324', 'slug': 'card-135860324-cert135860324'},
    {'cert': '151350422', 'slug': 'graded-card-151350422'},
    {'cert': '4321131035', 'slug': 'graded-card-4321131035'},
    {'cert': '131611480', 'slug': 'kangaskhan-ex-cert131611480'},
]


def b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode('ascii')


def main():
    token = os.environ.get('SK_ADMIN_TOKEN', '').strip()
    if not token:
        print('Set SK_ADMIN_TOKEN env var first.')
        sys.exit(1)

    for job in JOBS:
        cert = job['cert']
        slug = job['slug']
        front = FINISHED / slug / f'{slug}-front.jpg'
        back  = FINISHED / slug / f'{slug}-back.jpg'
        if not front.exists() or not back.exists():
            print(f'SKIP {cert}: missing one or both files in {slug}/')
            continue

        payload = {
            'cert':                 cert,
            'image_base64':         b64(front),
            'image_filename':       front.name,
            'back_image_base64':    b64(back),
            'back_image_filename':  back.name,
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
            },
        )
        print(f'cert {cert}  front={front.stat().st_size//1024}KB  back={back.stat().st_size//1024}KB')
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
                print(f'  OK  item={d.get("item_id")}  '
                      f'front_img={d.get("front_image_id")}  '
                      f'back_img={d.get("back_image_id")}  '
                      f'deleted={len(d.get("deleted_old_image_ids", []))}')
        except urllib.error.HTTPError as e:
            print(f'  HTTP {e.code}: {e.read().decode("utf-8", errors="replace")}')
        except Exception as e:
            print(f'  ERROR: {e}')


if __name__ == '__main__':
    main()
