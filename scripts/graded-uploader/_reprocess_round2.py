"""
Round 2: with the bottom-plastic margin fix in crop_slab, reprocess the
Wobbuffet (cert 135860324) AND re-do Pikachu Van Gogh #2 (cert 102607615)
since the user flagged its bottom as over-cropped on Square.

Output JPEGs land in the same finished/<slug> folders so the existing
pricing.csv image paths stay valid. After this finishes, hand off to
replace_images.py to push the new images into Square.

Source-pair map (cert -> IMG pair) — Wobbuffet from OCR via _find_certs.py:
  102607615 (Pikachu Van Gogh #2)        -> IMG_0037 + IMG_0038
  135860324 (Wobbuffet Pokemon Center)   -> IMG_0021 + IMG_0022
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from process_card import process_one

PROCESSED = Path(__file__).parent / 'inbox' / '_processed'
FINISHED  = Path(__file__).parent / 'finished'

JOBS = [
    {
        'cert': '102607615',
        'slug': 'pikachu-with-grey-felt-hat-cert102607615',
        'front': 'IMG_0037.png',
        'back':  'IMG_0038.png',
    },
    {
        'cert': '135860324',
        'slug': 'card-135860324-cert135860324',
        'front': 'IMG_0021.png',
        'back':  'IMG_0022.png',
    },
]


def main():
    for job in JOBS:
        front = PROCESSED / job['front']
        back  = PROCESSED / job['back']
        if not front.exists() or not back.exists():
            print(f'SKIP {job["cert"]}: missing source')
            continue

        out_dir = FINISHED / job['slug']
        front_name = f'{job["slug"]}-front.jpg'
        back_name  = f'{job["slug"]}-back.jpg'

        print(f'\n=== {job["cert"]} ({job["slug"]}) ===')
        front_out, palette = process_one(front, out_dir, out_name=front_name)
        back_out, _ = process_one(
            back, out_dir, out_name=back_name, palette_override=palette,
        )
        print(f'  -> {front_out.name}, {back_out.name}')


if __name__ == '__main__':
    main()
