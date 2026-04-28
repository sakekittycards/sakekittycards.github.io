"""
OCR the FULL image (not just the top half) of every IMG_NNNN that isn't
already accounted for in _cert_to_imgs.json. Looks for any of the
missing cert numbers in the OCR text and writes back a merged map.

Useful when the cert-on-the-label OCR missed because of font/contrast
issues — running OCR over the whole image often picks the cert up from
the slab's barcode label or footer.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

HERE = Path(__file__).parent
PROCESSED = HERE / 'inbox' / '_processed'
PRICING = HERE / 'pricing.csv'
CERT_MAP = HERE / '_cert_to_imgs.json'


def ocr_full(ocr, img: Image.Image) -> str:
    arr = np.asarray(img)
    result, _ = ocr(arr)
    if not result:
        return ''
    parts = []
    for entry in result:
        for x in entry:
            if isinstance(x, str):
                parts.append(x)
                break
    return ' '.join(parts).replace(' ', '').replace('-', '')


def main():
    # Targets: every cert in pricing.csv that isn't already mapped.
    existing = json.loads(CERT_MAP.read_text(encoding='utf-8'))
    mapped_certs = set(existing.keys())
    mapped_imgs: set[str] = set()
    for imgs in existing.values():
        mapped_imgs.update(imgs)

    targets: set[str] = set()
    with PRICING.open('r', encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            c = (r.get('cert') or '').strip()
            if c and c not in mapped_certs:
                targets.add(c)

    if not targets:
        print('Every cert already mapped. Nothing to do.')
        return

    print(f'Looking for {len(targets)} missing certs: {sorted(targets)}')

    candidates = [
        p for p in sorted(PROCESSED.iterdir())
        if p.suffix.lower() == '.png' and p.name not in mapped_imgs
    ]
    print(f'Scanning {len(candidates)} unaccounted IMG files (full image)\n')

    print('Loading RapidOCR...')
    ocr = RapidOCR()

    # OCR cache: keep results so re-runs are cheap.
    found: dict[str, list[str]] = dict(existing)
    for f in candidates:
        try:
            img = Image.open(f).convert('RGB')
            blob = ocr_full(ocr, img)
            for cert in targets:
                # Cert can be embedded in barcode digits — match
                # substring against the digit-stripped blob.
                stripped = re.sub(r'\D', '', blob)
                if cert in stripped:
                    found.setdefault(cert, []).append(f.name)
                    print(f'  {f.name}: matched {cert}')
        except Exception as e:
            print(f'  {f.name}: ERROR {e}', file=sys.stderr)

    # Auto-add the next IMG number as the back when only one is found.
    for cert, imgs in list(found.items()):
        if len(imgs) == 1:
            n = int(re.search(r'IMG_(\d+)', imgs[0]).group(1))
            nxt = f'IMG_{n+1:04d}.png'
            if (PROCESSED / nxt).exists():
                found[cert].append(nxt)

    CERT_MAP.write_text(json.dumps(found, indent=2), encoding='utf-8')
    print(f'\nWrote {CERT_MAP}')
    print(f'Total mapped: {len(found)} / target was {len(mapped_certs) + len(targets)}')
    still_missing = targets - set(found.keys())
    if still_missing:
        print(f'Still missing: {sorted(still_missing)}')


if __name__ == '__main__':
    main()
