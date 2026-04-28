"""
Round 3: re-run all 5 originally-broken cards with the new edge-
refinement crop. Replaces round 2 + round 2b output.

The crop now walks outward from the content bbox and back in until it
leaves paper, so the slab is bounded to its actual plastic edge — no
margins, no halo, no clipped plastic.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from process_card import process_one

PROCESSED = Path(__file__).parent / 'inbox' / '_processed'
FINISHED  = Path(__file__).parent / 'finished'

JOBS = [
    {'cert': '102607615', 'slug': 'pikachu-with-grey-felt-hat-cert102607615',
     'front': 'IMG_0037.png', 'back': 'IMG_0038.png'},
    {'cert': '135860324', 'slug': 'card-135860324-cert135860324',
     'front': 'IMG_0021.png', 'back': 'IMG_0022.png'},
    {'cert': '151350422', 'slug': 'graded-card-151350422',
     'front': 'IMG_0043.png', 'back': 'IMG_0044.png'},
    {'cert': '4321131035', 'slug': 'graded-card-4321131035',
     'front': 'IMG_0019.png', 'back': 'IMG_0020.png'},
    {'cert': '131611480', 'slug': 'kangaskhan-ex-cert131611480',
     'front': 'IMG_0013.png', 'back': 'IMG_0014.png'},
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
