"""
Quick locator: OCR _processed/IMG_*.png and find which images contain
the given cert numbers. Used to recover source IMGs for cards whose
output got mis-cropped and need re-processing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

PROCESSED = Path(__file__).parent / 'inbox' / '_processed'

TARGET_CERTS = {
    '131611480',  # Mewtwo GX
    # Already known from _pair_manual.py:
    #   IMG_0019/0020 -> 4321131035 (CGC Blastoise)
    #   IMG_0043/0044 -> 151350422
    # And from _pair_van_gogh_2.py: IMG_0037/0038 -> 102607615
}


def ocr_lines(ocr, img):
    arr = np.asarray(img)
    result, _ = ocr(arr)
    out = []
    if result:
        for entry in result:
            text = next((x for x in entry if isinstance(x, str)), None)
            if text:
                out.append(text)
    return out


def main():
    print('Loading RapidOCR...')
    ocr = RapidOCR()
    files = sorted(p for p in PROCESSED.iterdir() if p.suffix.lower() == '.png')
    print(f'Scanning {len(files)} processed scans for {sorted(TARGET_CERTS)}\n')
    found = {}
    for f in files:
        try:
            img = Image.open(f).convert('RGB')
            # Crop top half — PSA cert is on the front label, top of the slab
            w, h = img.size
            top = img.crop((0, 0, w, h // 2))
            blob = ' '.join(ocr_lines(ocr, top)).replace(' ', '')
            for cert in TARGET_CERTS:
                if cert in blob:
                    found.setdefault(cert, []).append(f.name)
                    print(f'  {f.name}: matched {cert}')
        except Exception as e:
            print(f'  {f.name}: ERROR {e}', file=sys.stderr)
    print('\nResult:')
    for cert in sorted(TARGET_CERTS):
        print(f'  {cert}: {found.get(cert, ["NOT FOUND"])}')


if __name__ == '__main__':
    main()
