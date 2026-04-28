"""
Iteratively try slab detectors against the 8 known-broken sources.
Saves bbox previews to _debug2/ so we can pick the winner.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

OUT = Path(__file__).parent / '_debug2'
OUT.mkdir(exist_ok=True)
PROCESSED = Path(__file__).parent / 'inbox' / '_processed'

TARGETS = [
    'IMG_0037.png', 'IMG_0038.png',
    'IMG_0019.png', 'IMG_0020.png',
    'IMG_0043.png', 'IMG_0044.png',
    'IMG_0013.png', 'IMG_0014.png',
]


def detect_combined(img: Image.Image) -> tuple[np.ndarray | None, np.ndarray]:
    """
    Combined detector: union of saturation-positive and dark-pixel masks,
    closed with a kernel large enough to bridge label band to card art.
    """
    rgb = np.asarray(img.convert('RGB'))
    L   = np.asarray(img.convert('L'))
    L   = cv2.GaussianBlur(L, (7, 7), 0)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[..., 1]

    # Saturation pixels: card art, color tints in label
    mask_sat  = (sat > 25).astype(np.uint8) * 255
    # Darker pixels: edges, label text, inner black borders.
    # 150 is tighter than 170 — excludes the gentle vignette/shadow on
    # white paper which can hit ~155-170 along scan edges.
    mask_dark = (L   < 150).astype(np.uint8) * 255
    mask = cv2.bitwise_or(mask_sat, mask_dark)

    # Open small to kill scanner speckle / paper texture noise
    open_k  = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_k)

    # Close moderate to bridge label band to card art (~250-300px gap).
    # Smaller than 401 so we don't bridge to scanner-edge shadow strips.
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (251, 251))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_k)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, mask

    H, W = L.shape
    img_area = H * W
    candidates = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w == 0 or h == 0:
            continue
        ba = w * h
        if ba < img_area * 0.05 or ba > img_area * 0.85:
            continue
        # Use minAreaRect to penalize L-shaped or strip-like blobs that
        # have huge axis-aligned bboxes but tiny rotated ones.
        rect = cv2.minAreaRect(c)
        (_, _), (rw, rh), _ = rect
        if rw == 0 or rh == 0:
            continue
        rect_area = rw * rh
        rect_long = max(rw, rh)
        rect_short = min(rw, rh)
        rect_aspect = rect_long / rect_short
        # Reject very elongated shapes (shadow strips, scanner edges).
        if rect_aspect > 2.4:
            continue
        # Reject shapes whose contour fills less than 50% of its rotated
        # rect — that's an L / hollow / disconnected blob.
        c_area = cv2.contourArea(c)
        if c_area / max(rect_area, 1) < 0.55:
            continue
        # Slab rotated rect aspect ~1.6 (PSA), 1.55 (CGC). Score by area
        # with a gentle aspect-distance penalty.
        score = c_area * (1.0 - min(1.0, abs(rect_aspect - 1.6) / 2.0))
        candidates.append((score, c, x, y, w, h))
    if not candidates:
        return None, mask
    candidates.sort(key=lambda t: t[0], reverse=True)
    _, best_c, *_ = candidates[0]
    return best_c, mask


def main():
    for name in TARGETS:
        p = PROCESSED / name
        if not p.exists():
            continue
        img = Image.open(p).convert('RGB')
        contour, mask = detect_combined(img)
        # Save mask
        Image.fromarray(mask).save(OUT / f'{p.stem}_mask.png')
        # Draw bbox
        preview = img.copy()
        if contour is not None:
            x, y, w, h = cv2.boundingRect(contour)
            d = ImageDraw.Draw(preview)
            d.rectangle((x, y, x + w, y + h), outline=(255, 0, 255), width=12)
            print(f'{name}: bbox x={x} y={y} w={w} h={h}  '
                  f'aspect={h/w:.2f}  area_frac={(w*h)/(img.size[0]*img.size[1]):.2f}')
        else:
            print(f'{name}: NO CONTOUR')
        preview.save(OUT / f'{p.stem}_bbox.jpg', quality=82)


if __name__ == '__main__':
    main()
