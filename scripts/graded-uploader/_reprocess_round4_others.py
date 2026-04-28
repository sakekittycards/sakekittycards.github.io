"""
Round 4: reprocess every graded card that wasn't already covered by
round 3 — i.e. every cert in pricing.csv minus the 5 we just redid.

Reads the cert→IMG-list mapping from _cert_to_imgs.json (built by
_map_all_certs.py via OCR over inbox/_processed/). Reprocesses each
card with the rembg-based pipeline and writes back into the existing
finished/<slug>/ folders.

Skipped automatically:
  - Certs whose OCR mapping returned 0 or >2 IMGs (ambiguous)
  - Certs already covered by round 3 (5 cards)
  - Certs without a matching finished/ folder (we use the slug from
    pricing.csv to decide where to write)
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

ROUND_3_CERTS = {'102607615', '135860324', '151350422', '4321131035', '131611480'}


def slug_from_path(front_path: str) -> str | None:
    """
    pricing.csv stores absolute paths like
        .../finished/<slug>/<slug>-front.jpg
    Pull out the <slug> directory name.
    """
    if not front_path:
        return None
    p = Path(front_path)
    return p.parent.name


def main():
    if not CERT_MAP.exists():
        print(f'ERROR: {CERT_MAP} not found. Run _map_all_certs.py first.')
        sys.exit(1)
    cert_to_imgs: dict[str, list[str]] = json.loads(CERT_MAP.read_text(encoding='utf-8'))

    # Load pricing.csv to get slug per cert.
    cert_to_slug: dict[str, str] = {}
    with PRICING.open('r', encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            cert = (r.get('cert') or '').strip()
            slug = slug_from_path(r.get('front_image', ''))
            if cert and slug:
                cert_to_slug[cert] = slug

    jobs: list[dict] = []
    skipped: list[str] = []
    for cert, imgs in sorted(cert_to_imgs.items()):
        if cert in ROUND_3_CERTS:
            skipped.append(f'{cert}: already in round 3')
            continue
        if len(imgs) != 2:
            skipped.append(f'{cert}: OCR found {len(imgs)} IMGs ({imgs})')
            continue
        slug = cert_to_slug.get(cert)
        if not slug:
            skipped.append(f'{cert}: no slug in pricing.csv')
            continue
        out_dir = FINISHED / slug
        if not out_dir.exists():
            skipped.append(f'{cert}: finished folder missing ({slug})')
            continue
        jobs.append({
            'cert':  cert,
            'slug':  slug,
            'front': imgs[0],
            'back':  imgs[1],
            'out':   out_dir,
        })

    print(f'Round 4: {len(jobs)} cards to reprocess')
    if skipped:
        print(f'Skipping {len(skipped)}:')
        for s in skipped:
            print(f'  - {s}')

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
