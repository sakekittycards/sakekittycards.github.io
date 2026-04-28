"""
One-shot pairer for the current inbox: walks sequential image pairs
(IMG_NNNN + IMG_NNNN+1), OCRs both, and matches against the user's
known cert list. Handles cases the standard pipeline can't:
  - cert OCR fails on the back (tilted hologram, small text)
  - CGC slabs (different label layout from PSA)
  - any pair where OCR is sparse on one side
Falls back to sequential file order (front-then-back convention).
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, str(Path(__file__).parent))
from process_card import process_one, crop_slab
from psa import parse_psa, lookup_pokemontcg
from process_inbox import slug, build_row, append_csv, append_edit_csv

# User-provided certs for the cards being priced this batch. Pipeline
# already paired Latias 99513425 and Arceus 95199161 separately, so they
# aren't repeated here.
KNOWN_CERTS = [
    '108973922', '146746311', '75183695',  '107496657', '131611480',
    '99211118',  '98922016',  '4321131035','135860324', '0014250139',
    '84566703',  '143411379', '99746732',  '145316191', '111350109',
    '94676138',  '134321907', '63063677',  '151350422', '110772487',
    '139206918', '84497733',  '110420477',
]

INBOX = Path(__file__).parent / 'inbox'
PROCESSED = INBOX / '_processed'
FINISHED = Path(__file__).parent / 'finished'
PRICING_CSV = Path(__file__).parent / 'pricing.csv'
EDIT_CSV   = Path(__file__).parent / 'pricing-edit.csv'


def already_done() -> set[str]:
    """Certs already in pricing.csv — skip those."""
    done = set()
    if PRICING_CSV.exists():
        with PRICING_CSV.open('r', encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                if r.get('cert'): done.add(r['cert'])
    return done


def ocr_lines(ocr: RapidOCR, img: Image.Image) -> list[str]:
    arr = np.asarray(img)
    result, _ = ocr(arr)
    out = []
    if result:
        for entry in result:
            text = next((x for x in entry if isinstance(x, str)), None)
            if text: out.append(text)
    return out


def find_known_cert(blob: str) -> str | None:
    """Look for any of the user's known certs in OCR'd text. Exact first,
    then with one-digit tolerance (OCR often drops the leading or
    trailing digit on holograms)."""
    for cert in KNOWN_CERTS:
        if cert in blob:
            return cert
    # Fuzzy: substring of length >= max(7, len(cert)-1)
    for cert in KNOWN_CERTS:
        threshold = max(7, len(cert) - 1)
        for i in range(len(cert) - threshold + 1):
            sub = cert[i:i + threshold]
            if sub in blob:
                return cert
    return None


def main():
    done = already_done()
    print(f'Already in pricing.csv: {len(done)} cert(s)')

    files = sorted(p for p in INBOX.iterdir() if p.suffix.lower() == '.png')
    print(f'Inbox files: {len(files)}\n')

    print('Loading RapidOCR...')
    ocr = RapidOCR()
    print()

    handled = 0
    skipped = []
    PROCESSED.mkdir(exist_ok=True)

    for i in range(0, len(files), 2):
        if i + 1 >= len(files):
            skipped.append((files[i].name, 'no pair'))
            break
        f1, f2 = files[i], files[i + 1]

        try:
            img1 = Image.open(f1).convert('RGB')
            img2 = Image.open(f2).convert('RGB')
            cropped1 = crop_slab(img1)
            cropped2 = crop_slab(img2)
            lines1 = ocr_lines(ocr, cropped1)
            lines2 = ocr_lines(ocr, cropped2)
        except Exception as e:
            print(f'{f1.name} + {f2.name}: OCR error ({e})')
            skipped.append((f'{f1.name}+{f2.name}', f'ocr error: {e}'))
            continue

        blob1 = ' '.join(lines1)
        blob2 = ' '.join(lines2)
        cert = find_known_cert(blob1) or find_known_cert(blob2)

        if not cert:
            print(f'{f1.name} + {f2.name}: NO MATCH against known certs - skipping')
            skipped.append((f'{f1.name}+{f2.name}', 'no known cert in OCR'))
            continue
        if cert in done:
            print(f'{f1.name} + {f2.name}: cert {cert} already done - skipping')
            continue

        # Prefer the side with PSA-label-like fields as the "front".
        parsed1 = parse_psa(lines1)
        parsed2 = parse_psa(lines2)
        score1 = bool(parsed1.get('year')) + bool(parsed1.get('grade')) + bool(parsed1.get('card_number'))
        score2 = bool(parsed2.get('year')) + bool(parsed2.get('grade')) + bool(parsed2.get('card_number'))
        if score1 >= score2:
            front, back, parsed = f1, f2, parsed1
        else:
            front, back, parsed = f2, f1, parsed2
        parsed['cert_number'] = cert  # override with the authoritative known cert

        match = None
        if parsed.get('card_number'):
            try:
                match = lookup_pokemontcg(parsed['card_number'],
                                          parsed.get('set'),
                                          parsed.get('card_title'))
            except Exception:
                match = None

        name = (match or {}).get('name') or parsed.get('card_title') or f'card-{cert}'
        slug_name = slug(name)
        out_dir = FINISHED / f'{slug_name}-cert{cert}'

        print(f'{front.name} + {back.name}: cert {cert} -> {name}')
        try:
            front_out, palette = process_one(front, out_dir,
                out_name=f'{slug_name}-cert{cert}-front.jpg')
            back_out, _ = process_one(back, out_dir,
                out_name=f'{slug_name}-cert{cert}-back.jpg',
                palette_override=palette)
        except Exception as e:
            print(f'  ERROR processing: {e}')
            skipped.append((f'{f1.name}+{f2.name}', f'process error: {e}'))
            continue

        row = build_row(parsed, match, front_out, back_out)
        append_csv(PRICING_CSV, row)
        append_edit_csv(EDIT_CSV, row)
        done.add(cert)
        handled += 1

        for src in (f1, f2):
            try: shutil.move(str(src), PROCESSED / src.name)
            except Exception: pass

    print()
    print(f'=== Summary ===')
    print(f'Handled this run: {handled}')
    print(f'Skipped: {len(skipped)}')
    for name, reason in skipped:
        print(f'  {name}: {reason}')


if __name__ == '__main__':
    main()
