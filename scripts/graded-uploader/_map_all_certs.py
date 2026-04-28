"""
Walk every PNG in inbox/_processed/, OCR the top half (where the PSA/CGC
cert lives), and emit a JSON map of cert -> [list of IMG filenames].

Used as the source-of-truth for round-3-all-cards reprocessing — we need
to know which IMG pair belongs to each cert in pricing.csv so we can
re-run process_card.py with the new edge-refinement crop.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

HERE = Path(__file__).parent
PROCESSED = HERE / 'inbox' / '_processed'
PRICING = HERE / 'pricing.csv'
OUT_JSON = HERE / '_cert_to_imgs.json'


def ocr_text(ocr, img: Image.Image) -> str:
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
    return ' '.join(parts).replace(' ', '')


def main():
    # Load every cert from pricing.csv that we want to find.
    targets: set[str] = set()
    with PRICING.open('r', encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            cert = (r.get('cert') or '').strip()
            if cert:
                targets.add(cert)
    print(f'Searching for {len(targets)} certs in {PROCESSED}')

    print('Loading RapidOCR...')
    ocr = RapidOCR()

    files = sorted(p for p in PROCESSED.iterdir() if p.suffix.lower() == '.png')
    print(f'Scanning {len(files)} processed scans')

    found: dict[str, list[str]] = {}
    for f in files:
        try:
            img = Image.open(f).convert('RGB')
            w, h = img.size
            top = img.crop((0, 0, w, h // 2))
            blob = ocr_text(ocr, top)
            for cert in targets:
                if cert in blob:
                    found.setdefault(cert, []).append(f.name)
        except Exception as e:
            print(f'  {f.name}: ERROR {e}', file=sys.stderr)
            continue

    OUT_JSON.write_text(json.dumps(found, indent=2), encoding='utf-8')
    print(f'\nWrote {OUT_JSON}')
    print(f'Found {len(found)}/{len(targets)} certs.')
    missing = sorted(targets - set(found.keys()))
    if missing:
        print(f'Missing: {missing}')
    # Cards where we found != 2 IMGs are probably OCR misses
    suspicious = {c: imgs for c, imgs in found.items() if len(imgs) != 2}
    if suspicious:
        print(f'\nSuspicious (count != 2):')
        for c, imgs in suspicious.items():
            print(f'  {c}: {imgs}')


if __name__ == '__main__':
    main()
