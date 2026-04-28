"""
Debug: visualize what each slab detector picks on a given source image.
Saves three masks and a bbox preview to /tmp so we can see why the
detector is choosing the wrong region.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from process_card import (
    _slab_contour_by_brightness,
    _slab_contour_by_saturation,
)

OUT = Path(__file__).parent / '_debug'
OUT.mkdir(exist_ok=True)


def save_mask(name, mask):
    Image.fromarray(mask).save(OUT / f'{name}.png')


def draw_bbox(img, contour, color):
    img2 = img.copy()
    if contour is not None:
        x, y, w, h = cv2.boundingRect(contour)
        d = ImageDraw.Draw(img2)
        d.rectangle((x, y, x + w, y + h), outline=color, width=8)
    return img2


def debug_one(path: Path):
    img = Image.open(path).convert('RGB')
    arr = np.asarray(img.convert('L'))
    arr_blur = cv2.GaussianBlur(arr, (5, 5), 0)

    # Brightness mask
    _, bright_mask = cv2.threshold(arr_blur, 240, 255, cv2.THRESH_BINARY_INV)
    bright_mask = cv2.morphologyEx(
        bright_mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (45, 45)),
    )
    bright_mask = cv2.morphologyEx(
        bright_mask, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)),
    )
    save_mask(f'{path.stem}_bright', bright_mask)

    # Saturation mask
    hsv = np.asarray(img.convert('HSV'))
    sat = hsv[..., 1]
    _, sat_mask = cv2.threshold(sat, 60, 255, cv2.THRESH_BINARY)
    sat_mask = cv2.morphologyEx(
        sat_mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (60, 60)),
    )
    save_mask(f'{path.stem}_sat', sat_mask)

    # Bbox previews
    bright_c = _slab_contour_by_brightness(img)
    sat_c    = _slab_contour_by_saturation(img)
    preview  = draw_bbox(img, bright_c, (255, 0, 0))   # red: brightness
    preview  = draw_bbox(preview, sat_c, (0, 255, 0))  # green: saturation
    preview.save(OUT / f'{path.stem}_bbox.jpg', quality=85)

    if bright_c is not None:
        x, y, w, h = cv2.boundingRect(bright_c)
        print(f'  brightness bbox: x={x} y={y} w={w} h={h}  '
              f'aspect={h/w:.2f}  area_frac={(w*h)/(arr.shape[0]*arr.shape[1]):.2f}')
    else:
        print('  brightness: NO CONTOUR')
    if sat_c is not None:
        x, y, w, h = cv2.boundingRect(sat_c)
        print(f'  saturation bbox: x={x} y={y} w={w} h={h}  '
              f'aspect={h/w:.2f}  area_frac={(w*h)/(arr.shape[0]*arr.shape[1]):.2f}')
    else:
        print('  saturation: NO CONTOUR')


def main():
    targets = [
        'IMG_0037.png', 'IMG_0038.png',
        'IMG_0019.png', 'IMG_0020.png',
        'IMG_0043.png', 'IMG_0044.png',
        'IMG_0013.png', 'IMG_0014.png',
    ]
    PROCESSED = Path(__file__).parent / 'inbox' / '_processed'
    for name in targets:
        p = PROCESSED / name
        if not p.exists():
            print(f'SKIP {name}: missing')
            continue
        print(f'\n{name}:')
        debug_one(p)
    print(f'\nMasks + bbox previews saved to {OUT}')


if __name__ == '__main__':
    main()
