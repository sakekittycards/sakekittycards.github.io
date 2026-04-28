"""
One-shot: re-run the image pipeline on the four cards whose first-pass
output was bad (slab detector picked the inner card instead of the full
slab, or crop missed entirely). Pulls source IMGs out of inbox/_processed,
re-processes with the improved brightness-threshold detector, and writes
new front + back JPEGs in the existing finished/<slug-cert*> folders so
the upload step can reuse the same paths.

Cert -> source-pair map:
  102607615 (Pikachu Van Gogh #2) -> IMG_0037 + IMG_0038
  151350422                       -> IMG_0043 + IMG_0044
  4321131035 (CGC Blastoise)      -> IMG_0019 + IMG_0020
  131611480 (Mewtwo GX)           -> IMG_0013 + IMG_0014
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from process_card import process_one

PROCESSED = Path(__file__).parent / 'inbox' / '_processed'
FINISHED  = Path(__file__).parent / 'finished'

# (cert, slug, front_img, back_img). slug must match the existing
# folder so the upload script (which reads from pricing.csv) doesn't
# need any path edits.
JOBS = [
    {
        'cert': '102607615',
        'slug': 'pikachu-with-grey-felt-hat-cert102607615',
        'front': 'IMG_0037.png',
        'back':  'IMG_0038.png',
    },
    {
        'cert': '151350422',
        'slug': 'graded-card-151350422',
        'front': 'IMG_0043.png',
        'back':  'IMG_0044.png',
    },
    {
        'cert': '4321131035',
        'slug': 'graded-card-4321131035',
        'front': 'IMG_0019.png',
        'back':  'IMG_0020.png',
    },
    {
        'cert': '131611480',
        'slug': 'kangaskhan-ex-cert131611480',
        'front': 'IMG_0013.png',
        'back':  'IMG_0014.png',
    },
]


def main():
    for job in JOBS:
        front = PROCESSED / job['front']
        back  = PROCESSED / job['back']
        if not front.exists() or not back.exists():
            print(f'SKIP {job["cert"]}: source missing ({front.name}, {back.name})')
            continue

        out_dir = FINISHED / job['slug']
        front_name = f'{job["slug"]}-front.jpg'
        back_name  = f'{job["slug"]}-back.jpg'

        print(f'\n=== {job["cert"]} ({job["slug"]}) ===')
        print(f'  front: {front.name}  back: {back.name}')
        front_out, palette = process_one(front, out_dir, out_name=front_name)
        back_out, _ = process_one(
            back, out_dir, out_name=back_name, palette_override=palette,
        )
        print(f'  -> {front_out.name}, {back_out.name}')


if __name__ == '__main__':
    main()
