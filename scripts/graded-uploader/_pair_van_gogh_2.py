"""
One-shot: process the second Van Gogh Pikachu pair (IMG_0037 + IMG_0038)
and append it to pricing.csv. Mirrors the metadata of the first one
(cert 94676138) since they're the same card, only the cert differs.
After this, run upload_to_square.py to push to Square.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from process_card import process_one
from process_inbox import append_csv, append_edit_csv

INBOX = Path(__file__).parent / 'inbox'
PROCESSED = INBOX / '_processed'
FINISHED = Path(__file__).parent / 'finished'
PRICING_CSV = Path(__file__).parent / 'pricing.csv'
EDIT_CSV    = Path(__file__).parent / 'pricing-edit.csv'

CERT = '102607615'
PAIR = ('IMG_0037.png', 'IMG_0038.png')

# Same card as cert 94676138, copied straight from pricing.csv row 17.
CARD_META = {
    'year':              '2023',
    'set':               'Scarlet & Violet Black Star Promos',
    'name':              'Pikachu with Grey Felt Hat',
    'number':            '85',
    'grade':             'GEMMT 10',
    'pokemontcg_set_id': 'svp',
    'your_price':        '3175',
}


def main():
    PROCESSED.mkdir(exist_ok=True)
    f1 = INBOX / PAIR[0]
    f2 = INBOX / PAIR[1]
    if not f1.exists() or not f2.exists():
        print(f'Source missing: {PAIR}')
        sys.exit(1)

    slug_name = f'pikachu-with-grey-felt-hat-cert{CERT}'
    out_dir = FINISHED / slug_name
    print(f'{f1.name} (front) + {f2.name} (back) -> cert {CERT}')

    front_out, palette = process_one(
        f1, out_dir, out_name=f'{slug_name}-front.jpg',
    )
    back_out, _ = process_one(
        f2, out_dir, out_name=f'{slug_name}-back.jpg',
        palette_override=palette,
    )

    row = {
        'cert':                       CERT,
        'year':                       CARD_META['year'],
        'set':                        CARD_META['set'],
        'name':                       CARD_META['name'],
        'number':                     CARD_META['number'],
        'grade':                      CARD_META['grade'],
        'suggested_price_tcgplayer':  '',
        'your_price':                 CARD_META['your_price'],
        'condition_note':             '',
        'offer_min':                  '',
        'front_image':                str(front_out),
        'back_image':                 str(back_out),
        'pokemontcg_set_id':          CARD_META['pokemontcg_set_id'],
        'identified_at':              datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    append_csv(PRICING_CSV, row)
    append_edit_csv(EDIT_CSV, row)
    print(f'Appended row to {PRICING_CSV.name} and {EDIT_CSV.name}')

    for src in (f1, f2):
        try:
            shutil.move(str(src), PROCESSED / src.name)
        except Exception as e:
            print(f'  move fail {src.name}: {e}')

    print('Done. Now run: .\\scripts\\graded-uploader\\upload.ps1')


if __name__ == '__main__':
    main()
