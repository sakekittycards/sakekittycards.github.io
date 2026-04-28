"""
Final manual pass for cards where OCR couldn't read the cert on either
side (CGC slabs, vintage labels, heavily glared scans). Maps the still-
unprocessed inbox image pairs to known certs based on scan order, then
runs the full image pipeline. Customer can fill metadata in pricing-edit.csv
after upload.
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from process_card import process_one
from psa import lookup_pokemontcg
from process_inbox import slug, build_row, append_csv, append_edit_csv

INBOX = Path(__file__).parent / 'inbox'
PROCESSED = INBOX / '_processed'
FINISHED = Path(__file__).parent / 'finished'
PRICING_CSV = Path(__file__).parent / 'pricing.csv'
EDIT_CSV   = Path(__file__).parent / 'pricing-edit.csv'

# Manual scan-order → cert mapping for pairs where OCR couldn't help.
# Image numbers refer to the IMG_NNNN.png pairs still left in the inbox.
# IMG_0037+0038 is the extra unpriced card the user scanned but didn't
# include in the price list — skipped here.
MANUAL = [
    {'pair': ('IMG_0007.png', 'IMG_0008.png'), 'cert': '146746311'},
    {'pair': ('IMG_0015.png', 'IMG_0016.png'), 'cert': '99211118'},
    {'pair': ('IMG_0019.png', 'IMG_0020.png'), 'cert': '4321131035'},
    {'pair': ('IMG_0023.png', 'IMG_0024.png'), 'cert': '0014250139'},
    {'pair': ('IMG_0027.png', 'IMG_0028.png'), 'cert': '143411379'},
    {'pair': ('IMG_0043.png', 'IMG_0044.png'), 'cert': '151350422'},
    {'pair': ('IMG_0051.png', 'IMG_0052.png'), 'cert': '110420477'},
]


def main():
    PROCESSED.mkdir(exist_ok=True)
    handled = 0
    for entry in MANUAL:
        f1 = INBOX / entry['pair'][0]
        f2 = INBOX / entry['pair'][1]
        cert = entry['cert']

        if not f1.exists() or not f2.exists():
            print(f'{entry["pair"]}: source missing - skipping')
            continue

        # Minimal parsed dict — title/year/grade can be filled in CSV later
        # when the user reviews the row. Card name defaults to a generic
        # "graded-card-<cert>" via the slug fallback.
        parsed = {
            'cert_number': cert,
            'year':        '',
            'set':         '',
            'card_title':  '',
            'card_number': '',
            'grade':       '',
        }
        match = None  # no card_number to look up
        slug_name = f'graded-card-{cert}'
        out_dir = FINISHED / f'{slug_name}'
        print(f'{f1.name} + {f2.name}: cert {cert}')
        try:
            front_out, palette = process_one(f1, out_dir,
                out_name=f'{slug_name}-front.jpg')
            back_out, _ = process_one(f2, out_dir,
                out_name=f'{slug_name}-back.jpg',
                palette_override=palette)
        except Exception as e:
            print(f'  ERROR processing: {e}')
            continue

        row = build_row(parsed, match, front_out, back_out)
        append_csv(PRICING_CSV, row)
        append_edit_csv(EDIT_CSV, row)
        handled += 1

        for src in (f1, f2):
            try: shutil.move(str(src), PROCESSED / src.name)
            except Exception: pass

    print()
    print(f'Manually paired: {handled}')


if __name__ == '__main__':
    main()
