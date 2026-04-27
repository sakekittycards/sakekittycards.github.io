"""
Process a folder of scanned graded-card images end-to-end.

Pairs files sequentially (front=odd, back=even), OCRs the PSA label off
each front, enriches via pokemontcg.io, runs the image pipeline on both
front and back, moves the originals into a 'processed' subfolder, and
appends a row per card to pricing.csv ready for you to fill in your_price.

Usage:
    python process_inbox.py
        (uses default ./inbox, ./finished, ./pricing.csv)

    python process_inbox.py --inbox ../scans --finished ../listings \\
                            --csv ../listings/pricing.csv

CSV columns:
    cert, year, set, name, number, grade,
    suggested_price_tcgplayer, your_price, condition_note, offer_min,
    front_image, back_image, pokemontcg_set_id, identified_at

Pairing rules:
    Files are sorted by name. Pairs taken in order: 1+2, 3+4, 5+6...
    First file of each pair is treated as the front (carries the PSA
    label and gets OCR'd); second is the back. If you scan in a
    different order, rename the files so they sort the way you scanned.

Errors:
    If OCR fails (e.g. unreadable scan), the row is still written with
    cert='UNKNOWN-<filename>' so you can inspect manually. Originals
    are left in inbox/ so you can rescan.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from process_card import crop_slab, process_one
from psa import isolate_label, parse_psa, lookup_pokemontcg

CSV_COLUMNS = [
    "cert",
    "year",
    "set",
    "name",
    "number",
    "grade",
    "suggested_price_tcgplayer",
    "your_price",
    "condition_note",
    "offer_min",
    "front_image",
    "back_image",
    "pokemontcg_set_id",
    "identified_at",
]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


def list_pairs(inbox: Path) -> list[tuple[Path, Path]]:
    """Sort image files lexicographically and pair them sequentially."""
    files = sorted(
        p for p in inbox.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if len(files) % 2 != 0:
        print(f"  WARN: odd number of files in inbox ({len(files)}); "
              f"last one will be skipped — rescan or rename to fix")
        files = files[:-1]
    return [(files[i], files[i + 1]) for i in range(0, len(files), 2)]


def ocr_front(ocr: RapidOCR, src: Path) -> tuple[dict, dict | None]:
    """OCR + parse the front. Returns (parsed_psa, pokemontcg_match_or_none)."""
    img = Image.open(src).convert("RGB")
    cropped = crop_slab(img)
    label = isolate_label(cropped)
    result, _elapsed = ocr(np.asarray(label))
    lines: list[str] = []
    if result is not None:
        for entry in result:
            text = next((x for x in entry if isinstance(x, str)), None)
            if text:
                lines.append(text)

    parsed = parse_psa(lines)
    match = None
    if parsed.get("card_number"):
        match = lookup_pokemontcg(
            parsed["card_number"],
            parsed.get("set"),
            parsed.get("card_title"),
        )
    return parsed, match


def slug(s: str | None, max_len: int = 40) -> str:
    if not s:
        return "unknown"
    out = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return out[:max_len] or "unknown"


def build_row(parsed: dict, match: dict | None,
              front_image: Path, back_image: Path) -> dict:
    suggested = match.get("tcgplayer_market") if match else None
    return {
        "cert": parsed.get("cert_number") or f"UNKNOWN-{front_image.stem}",
        "year": parsed.get("year") or "",
        "set": (match or {}).get("set_name") or parsed.get("set") or "",
        "name": (match or {}).get("name") or parsed.get("card_title") or "",
        "number": (match or {}).get("number") or parsed.get("card_number") or "",
        "grade": parsed.get("grade") or "",
        "suggested_price_tcgplayer": f"{suggested:.2f}" if suggested else "",
        "your_price": "",
        "condition_note": "",
        "offer_min": "",
        "front_image": str(front_image),
        "back_image": str(back_image),
        "pokemontcg_set_id": (match or {}).get("set_id") or "",
        "identified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def append_csv(csv_path: Path, row: dict):
    """Append a row, creating the file with a header if it doesn't exist."""
    new = not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


def main():
    here = Path(__file__).parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", type=Path, default=here / "inbox",
                    help="Folder where scanner drops paired front/back images")
    ap.add_argument("--finished", type=Path, default=here / "finished",
                    help="Folder where processed listing JPEGs go")
    ap.add_argument("--csv", type=Path, default=here / "pricing.csv",
                    help="CSV file to append identified-card rows to")
    ap.add_argument("--keep-originals", action="store_true",
                    help="Don't move originals out of inbox after success")
    args = ap.parse_args()

    if not args.inbox.exists():
        print(f"Inbox folder doesn't exist: {args.inbox}")
        print(f"Create it and drop scanned images there, then re-run.")
        sys.exit(1)

    pairs = list_pairs(args.inbox)
    if not pairs:
        print(f"No image pairs in {args.inbox}")
        sys.exit(0)

    print(f"Inbox:    {args.inbox.resolve()}")
    print(f"Finished: {args.finished.resolve()}")
    print(f"CSV:      {args.csv.resolve()}")
    print(f"Pairs to process: {len(pairs)}")
    print()

    print("Loading RapidOCR (first run downloads ~10MB of ONNX models)...")
    ocr = RapidOCR()

    processed_dir = args.inbox / "_processed"
    processed_dir.mkdir(exist_ok=True)

    for i, (front_src, back_src) in enumerate(pairs, 1):
        t0 = time.time()
        print(f"[{i}/{len(pairs)}] front={front_src.name}  back={back_src.name}")

        try:
            parsed, match = ocr_front(ocr, front_src)
        except Exception as e:
            print(f"  ERROR during OCR: {e} — leaving in inbox")
            continue

        cert = parsed.get("cert_number") or f"unknown-{front_src.stem}"
        slug_name = slug((match or {}).get("name") or parsed.get("card_title"))
        out_subdir = args.finished / f"{slug_name}-cert{cert}"

        try:
            front_out = process_one(front_src, out_subdir,
                                     out_name=f"{slug_name}-cert{cert}-front.jpg")
            back_out = process_one(back_src, out_subdir,
                                    out_name=f"{slug_name}-cert{cert}-back.jpg")
        except Exception as e:
            print(f"  ERROR during image pipeline: {e} — leaving in inbox")
            continue

        row = build_row(parsed, match, front_out, back_out)
        append_csv(args.csv, row)

        if not args.keep_originals:
            shutil.move(str(front_src), processed_dir / front_src.name)
            shutil.move(str(back_src), processed_dir / back_src.name)

        identified = match.get("name") if match else "(unidentified)"
        suggested = match.get("tcgplayer_market") if match else None
        suggested_str = f"${suggested:.2f}" if suggested else "—"
        elapsed = time.time() - t0
        print(f"  -> {identified} | {parsed.get('grade') or '?'} "
              f"| cert {cert} | suggested {suggested_str} ({elapsed:.1f}s)")

    print()
    print(f"Done. Edit {args.csv} to fill in your_price for each card, "
          f"then run upload_to_square.py.")


if __name__ == "__main__":
    main()
