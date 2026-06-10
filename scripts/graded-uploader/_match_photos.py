"""Match Nick's own front/back slab photos to graded cards by OCR'ing the cert
number off each photo and cross-referencing the Card Ladder CSV cert list.

Photos: D:\\Dropbox\\Camera Uploads\\Grade Photos 6.10.26\\*.jpg — front+back per
card, captured in CSV order. Both faces of a PSA/CGC slab show the cert, so we
identify each photo by cert (robust to any ordering gap), then split each cert's
pair into front (earlier capture) / back (later).

Cross-referencing OCR numbers against the actual CSV cert set ignores noise
(years, card numbers) and only accepts real certs.

Writes _photo_map.json: {cert: {"front": path, "back": path|null}}.
Run this FIRST (dry report), eyeball it, then _attach_photos.py uploads.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

PHOTO_DIR = Path(r"D:\Dropbox\Camera Uploads\Grade Photos 6.10.26")
CSV_PATH = Path(os.environ.get("RELIST_CSV",
                r"C:\Users\lunar\Downloads\Collection - Card Ladder (48).csv"))
HERE = Path(__file__).resolve().parent
OUT = HERE / "_photo_map.json"
OCR_CACHE = HERE / "_photo_ocr_cache.json"

_OCR = None
def ocr():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def parse_ts(name: str) -> float:
    """'Photo Jun 10 2026, 1 09 17 AM.jpg' -> sortable timestamp (capture order)."""
    m = re.search(r"(\w+ \d+ \d{4}), (\d+) (\d+) (\d+) ([AP]M)", name)
    if not m:
        return 0.0
    try:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)} {m.group(5)}",
                               "%b %d %Y %I:%M:%S %p")
        return dt.timestamp()
    except ValueError:
        return 0.0


def certs_in(img: Image.Image, valid: set[str]) -> list[str]:
    res, _ = ocr()(np.asarray(img))
    found = []
    for _b, t, _c in (res or []):
        for run in re.findall(r"\d{6,}", (t or "").replace(" ", "")):
            if run in valid:
                found.append(run)
    return found


def detect_cert(path: Path, valid: set[str]) -> tuple[str | None, int]:
    """Return (cert, ocr_box_count). Downscale first; full-res retry on miss."""
    im = Image.open(path).convert("RGB")
    work = im.copy()
    work.thumbnail((1600, 1600))
    res, _ = ocr()(np.asarray(work))
    boxes = len(res or [])
    hits = []
    for _b, t, _c in (res or []):
        for run in re.findall(r"\d{6,}", (t or "").replace(" ", "")):
            if run in valid:
                hits.append(run)
    if not hits:                      # full-res retry
        res2, _ = ocr()(np.asarray(im))
        boxes = max(boxes, len(res2 or []))
        for _b, t, _c in (res2 or []):
            for run in re.findall(r"\d{6,}", (t or "").replace(" ", "")):
                if run in valid:
                    hits.append(run)
    cert = max(set(hits), key=hits.count) if hits else None
    return cert, boxes


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    rows = [r for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig"))
            if (r.get("Graded Cert #") or "").strip()]
    csv_certs = [r["Graded Cert #"].strip() for r in rows]
    valid = set(csv_certs)

    files = sorted(glob.glob(str(PHOTO_DIR / "*.jpg")), key=lambda p: parse_ts(os.path.basename(p)))
    print(f"[match] {len(files)} photos | {len(csv_certs)} CSV cards")

    cache = {}
    if OCR_CACHE.exists():
        try:
            cache = json.loads(OCR_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # Ordered (path, cert_or_None, boxes) in capture order.
    seq = []
    misses = []
    for f in files:
        if f in cache:
            cert, boxes = cache[f]["cert"], cache[f]["boxes"]
        else:
            cert, boxes = detect_cert(Path(f), valid)
            cache[f] = {"cert": cert, "boxes": boxes}
            OCR_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        seq.append((f, cert, boxes))
        if not cert:
            misses.append(f)
        print(f"  {os.path.basename(f)[-22:]:24} -> {cert or 'NO CERT'}")

    # Group by cert in capture order. A NO-CERT photo (CGC holographic backs OCR
    # poorly) is inferred as the BACK of the immediately-preceding card, but only
    # if that card still has just its front — so a front always reads first.
    groups: dict[str, list] = {}
    last_cert = None
    inferred = []
    for f, cert, boxes in seq:
        if cert:
            groups.setdefault(cert, []).append((f, boxes))
            last_cert = cert
        elif last_cert and len(groups.get(last_cert, [])) == 1:
            groups[last_cert].append((f, boxes))
            inferred.append((last_cert, f))

    photo_map = {}
    for cert, lst in groups.items():
        if len(lst) >= 2:
            by_boxes = sorted(lst, key=lambda x: -x[1])   # front = most card text
            front = by_boxes[0][0]
            back = next((p for p, _b in lst if p != front), None)
        else:
            front, back = lst[0][0], None
        photo_map[cert] = {"front": front, "back": back}

    OUT.write_text(json.dumps(photo_map, indent=2), encoding="utf-8")

    matched2 = [c for c, v in photo_map.items() if v["back"]]
    matched1 = [c for c, v in photo_map.items() if not v["back"]]
    no_photos = [c for c in csv_certs if c not in photo_map]
    extra = [c for c in photo_map if c not in valid]
    print(f"[match] inferred {len(inferred)} no-cert backs to preceding card")
    still_miss = [f for f in misses if not any(f == p for _c, p in inferred)]
    print(f"[match] photos still unassigned: {len(still_miss)}")
    for m in still_miss:
        print(f"        {os.path.basename(m)}")

    print(f"\n[match] cards with front+back: {len(matched2)}")
    print(f"[match] cards with only ONE photo: {len(matched1)}  {matched1}")
    print(f"[match] CSV cards with NO photos: {len(no_photos)}  {no_photos}")
    print(f"[match] photos with NO cert read: {len(misses)}")
    for m in misses:
        print(f"        {os.path.basename(m)}")
    print(f"\n[match] wrote {OUT}")


if __name__ == "__main__":
    main()
