"""Crop + deskew a phone photo of a graded slab: isolate the slab (rembg
birefnet), straighten it, and crop to the slab with a small margin. Keeps the
original photo pixels (Nick's own background) — just cropped + rotated.
"""
from __future__ import annotations

import io
import numpy as np
from PIL import Image, ImageOps

_SESSION = None
def _session():
    global _SESSION
    if _SESSION is None:
        from rembg import new_session
        _SESSION = new_session("birefnet-general")
    return _SESSION


def _slab_mask(rgb: Image.Image) -> np.ndarray:
    from rembg import remove
    out = remove(rgb, session=_session())          # RGBA
    a = np.asarray(out)[:, :, 3]
    return (a > 128).astype(np.uint8) * 255


def crop_deskew(path: str, margin: float = 0.045, max_px: int = 1400) -> bytes:
    """Return a cropped+deskewed JPEG (bytes) of the slab in `path`."""
    import cv2
    img = Image.open(path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    # Work at reduced size for the mask, scale the box back up.
    work = img.copy()
    scale = min(1.0, 1600 / max(work.size))
    if scale < 1.0:
        work = work.resize((int(work.width * scale), int(work.height * scale)))
    mask = _slab_mask(work)

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        # Fallback: just return the original downsized.
        out = img.copy(); out.thumbnail((max_px, max_px))
        b = io.BytesIO(); out.save(b, "JPEG", quality=92); return b.getvalue()
    c = max(cnts, key=cv2.contourArea)
    rect = cv2.minAreaRect(c)                       # ((cx,cy),(w,h),angle)
    (cx, cy), (rw, rh), angle = rect
    # Normalize angle so the slab ends up upright (portrait).
    if rw < rh:
        angle = angle
    else:
        angle = angle + 90
    if angle > 45:
        angle -= 90
    if angle < -45:
        angle += 90
    # Only deskew small tilts (avoid flipping on a noisy mask).
    if abs(angle) > 20:
        angle = 0.0

    inv = 1.0 / scale
    full = np.asarray(img)
    h, w = full.shape[:2]
    M = cv2.getRotationMatrix2D((cx * inv, cy * inv), angle, 1.0)
    rot = cv2.warpAffine(full, M, (w, h), flags=cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_REPLICATE)
    rmask = cv2.warpAffine(mask, cv2.getRotationMatrix2D((cx, cy), angle, 1.0),
                           (mask.shape[1], mask.shape[0]))
    ys, xs = np.where(rmask > 128)
    if len(xs) < 10:
        out = Image.fromarray(rot); out.thumbnail((max_px, max_px))
        b = io.BytesIO(); out.save(b, "JPEG", quality=92); return b.getvalue()
    x0, x1 = xs.min() * inv, xs.max() * inv
    y0, y1 = ys.min() * inv, ys.max() * inv
    bw, bh = x1 - x0, y1 - y0
    mx, my = bw * margin, bh * margin
    x0 = int(max(0, x0 - mx)); x1 = int(min(w, x1 + mx))
    y0 = int(max(0, y0 - my)); y1 = int(min(h, y1 + my))
    crop = Image.fromarray(rot[y0:y1, x0:x1])
    crop.thumbnail((max_px, max_px))
    b = io.BytesIO(); crop.save(b, "JPEG", quality=92)
    return b.getvalue()


if __name__ == "__main__":
    import sys
    from pathlib import Path
    for p in sys.argv[1:]:
        out = crop_deskew(p)
        dst = Path("_crop_test") / (Path(p).stem + ".jpg")
        dst.parent.mkdir(exist_ok=True)
        dst.write_bytes(out)
        print("wrote", dst, len(out), "bytes")
