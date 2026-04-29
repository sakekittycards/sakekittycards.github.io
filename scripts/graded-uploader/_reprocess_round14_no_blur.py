"""
Round 14: reprocess every cert from _cert_to_imgs.json EXCEPT cert
0014250139 (BGS Charizard), which has been hand-tuned with the
focal-blur softening for that one card's edge wear and shouldn't be
overwritten with the default no-blur output.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from process_card import process_one

HERE = Path(__file__).parent
PROCESSED = HERE / 'inbox' / '_processed'
FINISHED  = HERE / 'finished'
PRICING   = HERE / 'pricing.csv'
CERT_MAP  = HERE / '_cert_to_imgs.json'

# Cards that have card-specific tuning (e.g. focal blur for visible
# slab edge wear). Skip these so the default reprocess doesn't undo
# the per-card adjustment.
SKIP_CERTS = {'0014250139'}


def slug_from_path(front_path: str) -> str | None:
    if not front_path:
        return None
    return Path(front_path).parent.name


def main():
    cert_to_imgs = json.loads(CERT_MAP.read_text(encoding='utf-8'))
    cert_to_slug: dict[str, str] = {}
    with PRICING.open('r', encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            cert = (r.get('cert') or '').strip()
            slug = slug_from_path(r.get('front_image', ''))
            if cert and slug:
                cert_to_slug[cert] = slug

    jobs: list[dict] = []
    for cert, imgs in sorted(cert_to_imgs.items()):
        if cert in SKIP_CERTS:
            continue
        if len(imgs) != 2:
            continue
        slug = cert_to_slug.get(cert)
        if not slug:
            continue
        out_dir = FINISHED / slug
        if not out_dir.exists():
            continue
        jobs.append({'cert': cert, 'slug': slug,
                     'front': imgs[0], 'back': imgs[1], 'out': out_dir})

    print(f'Round 14: {len(jobs)} cards to reprocess (skipping {sorted(SKIP_CERTS)})')
    t_start = time.time()
    for i, job in enumerate(jobs, 1):
        front = PROCESSED / job['front']
        back  = PROCESSED / job['back']
        if not front.exists() or not back.exists():
            print(f'[{i}/{len(jobs)}] cert={job["cert"]}: SOURCE MISSING')
            continue
        front_name = f'{job["slug"]}-front.jpg'
        back_name  = f'{job["slug"]}-back.jpg'
        elapsed = time.time() - t_start
        eta = (elapsed / i) * (len(jobs) - i) if i > 1 else 0
        print(f'\n[{i}/{len(jobs)}] cert={job["cert"]} ({job["slug"]}) — '
              f'elapsed {elapsed:.0f}s, ETA {eta:.0f}s')
        try:
            front_out, palette = process_one(front, job['out'], out_name=front_name)
            back_out, _ = process_one(
                back, job['out'], out_name=back_name, palette_override=palette,
            )
            print(f'  -> {front_out.name}, {back_out.name}')
        except Exception as e:
            print(f'  ERROR: {e}')

    print(f'\nDone in {time.time()-t_start:.0f}s')


if __name__ == '__main__':
    main()
