"""One-shot pairing for the 2026-05-15 Pikachu VSTAR Universe FA scan.

OCR misread the back-side cert (148877417 → 14831747), so manual pair.
Front: IMG_0001.png, Back: IMG_0002.png, cert 148877417.

Metadata + sticker pre-filled from CL18 + eBay-comp analysis:
  CL CV: $730.52, PC PSA 10: $667.50, eBay last-5 clean avg: $791
  -> max anchor $791, tier-2 markup -> sticker $880, floor $810
"""
from __future__ import annotations
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from process_card import process_one
from process_inbox import build_row, append_csv, append_edit_csv

INBOX = HERE / 'inbox'
PROCESSED = INBOX / '_processed'
FINISHED = HERE / 'finished'
PRICING_CSV = HERE / 'pricing.csv'
EDIT_CSV = HERE / 'pricing-edit.csv'

CERT = '148877417'
FRONT = INBOX / 'IMG_0001.png'
BACK = INBOX / 'IMG_0002.png'
SLUG = f'fa-pikachu-vstar-universe-cert{CERT}'

# Pre-cleaned metadata that matches existing pricing.csv conventions
PARSED = {
    'cert_number': CERT,
    'year': '2022',
    'set': 'VSTAR Universe (Japanese)',
    'card_title': 'FA Pikachu',
    'card_number': '205',
    'grade': 'PSA 10',
}
# pokemontcg.io set id for VSTAR Universe Japanese
MATCH = {
    'name': 'FA Pikachu',
    'set_name': 'VSTAR Universe (Japanese)',
    'number': '205',
    'set_id': 's12a',
    'tcgplayer_market': 791.0,  # eBay last-5 clean avg
}
STICKER = 880  # post-formula


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    PROCESSED.mkdir(exist_ok=True)

    if not FRONT.exists() or not BACK.exists():
        print(f'Missing inputs: front={FRONT.exists()} back={BACK.exists()}')
        return 1

    out_dir = FINISHED / SLUG
    print(f'Processing {FRONT.name} -> {out_dir.name}/{SLUG}-front.jpg')
    front_out, palette = process_one(
        FRONT, out_dir, out_name=f'{SLUG}-front.jpg'
    )
    print(f'Processing {BACK.name}  -> {out_dir.name}/{SLUG}-back.jpg')
    back_out, _ = process_one(
        BACK, out_dir, out_name=f'{SLUG}-back.jpg',
        palette_override=palette,
    )

    row = build_row(PARSED, MATCH, front_out, back_out)
    # Pre-fill the sticker so upload_to_square.py picks it up.
    row['your_price'] = str(STICKER)
    append_csv(PRICING_CSV, row)
    append_edit_csv(EDIT_CSV, row)
    print(f'\npricing.csv: appended row cert {CERT} sticker ${STICKER}')

    for src in (FRONT, BACK):
        try:
            shutil.move(str(src), PROCESSED / src.name)
        except Exception as e:
            print(f'  move {src.name} -> _processed failed: {e}')
    print(f'Originals moved to {PROCESSED}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
