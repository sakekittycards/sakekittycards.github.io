"""
OCR-only pass over D:\\Dropbox\\Personal Use\\Graded Pic\\ to extract the cert
numbers of every physical card the user owns. Skips full image processing —
this is just inventory truth-up so we can cross-reference Square and delete
items the user no longer owns.

Output:
  scripts/graded-uploader/_owned_certs.txt
    One cert number per line. Source of truth for "what user owns".

Each photo is run through:
  1. RapidOCR on the full image (PSA labels are usually visible as the top band)
  2. parse_psa() on the OCR lines to extract cert_number
  3. If cert not found via parse_psa, fall back to a raw 8-10 digit number scan

Cards photographed front+back contribute the same cert from each side; we
dedupe at the end.

Usage:
    python _ocr_inventory.py
    python _ocr_inventory.py --src "D:\\\\Dropbox\\\\Personal Use\\\\Graded Pic"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
except ImportError as e:
    print(f"Missing dependency: {e}. Install with: pip install rapidocr_onnxruntime pillow numpy")
    sys.exit(1)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from psa import parse_psa  # type: ignore


SRC_DEFAULT = Path(r"D:\Dropbox\Personal Use\Graded Pic")
OUT_PATH = HERE / "_owned_certs.txt"
SKU_OUT_PATH = HERE / "_owned_skus.txt"   # SK-NN-X-NNNN codes — primary key for inventory CSV match
SKU_PATTERN = re.compile(r"SK[\s\-]?(\d{2})[\s\-]?([A-Z])[\s\-]?(\d{3,4})", re.IGNORECASE)


def ocr_lines(img_path: Path, ocr) -> list[str]:
    """Run RapidOCR on the image and return the recognized text lines."""
    try:
        img = Image.open(img_path).convert("RGB")
    except Exception as e:
        print(f"  [open-err] {img_path.name}: {e}")
        return []
    arr = np.array(img)
    try:
        result, _ = ocr(arr)
    except Exception as e:
        print(f"  [ocr-err]  {img_path.name}: {e}")
        return []
    if not result:
        return []
    return [r[1] for r in result if len(r) >= 2]


def extract_cert(lines: list[str]) -> str | None:
    """Try parse_psa first, then a plain digit-string fallback."""
    parsed = parse_psa(lines)
    if parsed.get("cert_number"):
        return parsed["cert_number"]
    # Fallback: any 8-10 digit token in the OCR'd lines
    blob = " ".join(lines)
    m = re.search(r"\b(\d{8,10})\b", blob)
    return m.group(1) if m else None


def extract_sku(lines: list[str]) -> str | None:
    """Look for an SK-26-G-NNNN code (the inventory CSV's card_id). OCR may
    drop the dashes or run characters together, so the pattern is forgiving."""
    blob = " ".join(lines)
    m = SKU_PATTERN.search(blob)
    if not m: return None
    yr, letter, num = m.group(1), m.group(2).upper(), m.group(3)
    # Pad to 4 digits to match inventory CSV format (SK-26-G-0056 not SK-26-G-56)
    return f"SK-{yr}-{letter}-{num.zfill(4)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=SRC_DEFAULT,
                    help="Folder containing graded-card photos")
    args = ap.parse_args()

    src = args.src
    if not src.exists():
        print(f"[ocr] source folder not found: {src}")
        return 1

    photos = sorted([p for p in src.iterdir()
                     if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")])
    if not photos:
        print(f"[ocr] no photos in {src}"); return 1
    print(f"[ocr] {len(photos)} photos in {src}")
    print(f"[ocr] initializing RapidOCR (first run downloads ~80MB of models, slow)...")
    ocr = RapidOCR()
    print(f"[ocr] OCR'ing each photo...")

    owned: dict[str, list[str]] = {}      # cert -> [photo names]
    skus:  dict[str, list[str]] = {}      # SK-26-G-NNNN -> [photo names]
    no_id: list[tuple[str, str]] = []     # (photo_name, ocr_text)

    for i, p in enumerate(photos, 1):
        lines = ocr_lines(p, ocr)
        cert = extract_cert(lines)
        sku  = extract_sku(lines)
        tags = []
        if cert:
            owned.setdefault(cert, []).append(p.name)
            tags.append(f"cert {cert}")
        if sku:
            skus.setdefault(sku, []).append(p.name)
            tags.append(f"sku {sku}")
        if tags:
            print(f"[ocr] {i:>3}/{len(photos)} {p.name}: {' | '.join(tags)}")
        else:
            text = ' | '.join(lines)[:160]
            no_id.append((p.name, text))
            text_safe = text.encode('ascii', 'replace').decode('ascii')
            print(f"[ocr] {i:>3}/{len(photos)} {p.name}: NO ID  (OCR text: {text_safe})")

    print()
    print(f"[ocr] {len(owned)} unique certs detected, {len(skus)} unique SKs detected, "
          f"{len(no_id)} photos with no id")

    OUT_PATH.write_text("\n".join(sorted(owned.keys())) + "\n", encoding="utf-8")
    SKU_OUT_PATH.write_text("\n".join(sorted(skus.keys())) + "\n", encoding="utf-8")
    print(f"[ocr] wrote {len(owned)} certs to {OUT_PATH}")
    print(f"[ocr] wrote {len(skus)} SKs   to {SKU_OUT_PATH}")

    if no_id:
        print()
        print("Photos with no cert AND no SK code (manual review):")
        for n, _ in no_id:
            print(f"  - {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
