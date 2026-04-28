"""
Process a folder of scanned graded-card images end-to-end.

Approach:
    1. OCR the top label band of every image in the inbox.
    2. Classify each scan as 'front' (has year/set/grade/title) or
       'back' (only the cert hologram is visible).
    3. Pair fronts with backs by cert number.
    4. Run the image pipeline on each pair, output to per-card folders,
       append a row to pricing.csv.
    5. Move processed originals out of the inbox; leave unmatched
       scans in place with a console summary.

You can scan in ANY order - the pipeline matches by cert, not by
filename order. Misses (one-sided cards, unreadable certs) get logged
and left in the inbox so you can rescan or pair manually.

Usage:
    python process_inbox.py
        (defaults: ./inbox, ./finished, ./pricing.csv)

    python process_inbox.py --inbox <path> --finished <path> --csv <path>

CSV columns:
    cert, year, set, name, number, grade,
    suggested_price_tcgplayer, your_price, condition_note, offer_min,
    front_image, back_image, pokemontcg_set_id, identified_at
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
import time
from collections import defaultdict
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

# Google-Sheets-friendly companion CSV. No file paths, no timestamps —
# just the columns the human cares about while pricing cards. Process
# writes here on every new card; upload script syncs your_price /
# condition_note / offer_min back into the canonical pricing.csv before
# uploading.
EDIT_CSV_COLUMNS = [
    "cert",
    "name",
    "year",
    "set",
    "grade",
    "suggested_price",
    "your_price",
    "condition_note",
    "offer_min",
]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


def slug(s: str | None, max_len: int = 40) -> str:
    if not s:
        return "unknown"
    out = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return out[:max_len] or "unknown"


def list_image_files(inbox: Path) -> list[Path]:
    return sorted(
        p for p in inbox.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )


def ocr_label(ocr: RapidOCR, src: Path) -> tuple[dict, list[str]]:
    """
    OCR the full cropped slab and parse PSA fields.

    Originally limited to the top 25% (the label band) for speed, but
    that turned out brittle: small grade numbers like "10" and the cert
    tail sometimes fall outside the band depending on slab proportions.
    Full-slab OCR is ~1.5s per scan instead of 0.6s but catches every
    field reliably. parse_psa filters card-art noise out of the result.
    """
    img = Image.open(src).convert("RGB")
    cropped = crop_slab(img)
    result, _elapsed = ocr(np.asarray(cropped))
    lines: list[str] = []
    if result is not None:
        for entry in result:
            text = next((x for x in entry if isinstance(x, str)), None)
            if text:
                lines.append(text)
    parsed = parse_psa(lines)
    return parsed, lines


def classify_face(parsed: dict) -> str:
    """
    'front' if the front-only fields (year + grade or card_number) read,
    'back' if only a cert # (hologram-only side),
    'unknown' if neither.

    Backs sometimes pick up OCR garbage from the Pokemon back artwork
    ("Pekene", "PaKeney"). card_title alone isn't a reliable front
    signal — require the structured fields (year, grade, card #) that
    only appear on the printed PSA label.
    """
    front_signals = bool(
        parsed.get("year")
        or parsed.get("grade")
        or parsed.get("card_number")
    )
    if front_signals:
        return "front"
    if parsed.get("cert_number"):
        return "back"
    return "unknown"


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
    new = not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


def append_edit_csv(csv_path: Path, row: dict):
    """Append a sheet-friendly row mirroring the canonical CSV row."""
    new = not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EDIT_CSV_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({
            "cert":             row.get("cert", ""),
            "name":             row.get("name", ""),
            "year":             row.get("year", ""),
            "set":              row.get("set", ""),
            "grade":            row.get("grade", ""),
            "suggested_price":  row.get("suggested_price_tcgplayer", ""),
            "your_price":       "",
            "condition_note":   "",
            "offer_min":        "",
        })


def main():
    here = Path(__file__).parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", type=Path, default=here / "inbox",
                    help="Folder where scanner drops front+back images (any order)")
    ap.add_argument("--finished", type=Path, default=here / "finished",
                    help="Folder where processed listing JPEGs go")
    ap.add_argument("--csv", type=Path, default=here / "pricing.csv",
                    help="CSV file to append identified-card rows to")
    ap.add_argument("--edit-csv", type=Path, default=here / "pricing-edit.csv",
                    help="Sheet-friendly companion CSV for editing prices in Google Sheets")
    ap.add_argument("--keep-originals", action="store_true",
                    help="Don't move originals out of inbox after success")
    args = ap.parse_args()

    if not args.inbox.exists():
        print(f"Inbox folder doesn't exist: {args.inbox}")
        print("Create it and drop scanned images there, then re-run.")
        sys.exit(1)

    files = list_image_files(args.inbox)
    if not files:
        print(f"No image files in {args.inbox}")
        sys.exit(0)

    print(f"Inbox:    {args.inbox.resolve()}")
    print(f"Finished: {args.finished.resolve()}")
    print(f"CSV:      {args.csv.resolve()}")
    print(f"Files to OCR: {len(files)}")
    print()
    print("Loading RapidOCR (first run downloads ~10MB of ONNX models)...")
    ocr = RapidOCR()

    # Pass 1 - OCR each file, classify face, group by cert.
    print()
    print("=== Pass 1: OCR + classify ===")
    by_cert: dict[str, dict] = defaultdict(lambda: {"front": [], "back": [], "unknown": []})
    no_cert: list[Path] = []

    for i, src in enumerate(files, 1):
        t0 = time.time()
        try:
            parsed, _lines = ocr_label(ocr, src)
        except Exception as e:
            print(f"  [{i:>3}/{len(files)}] {src.name}  ERROR: {e}")
            continue
        face = classify_face(parsed)
        cert = parsed.get("cert_number")
        elapsed = time.time() - t0

        if cert:
            by_cert[cert][face].append({"src": src, "parsed": parsed})
            tag = (
                f"{face} cert={cert}" if face != "unknown"
                else f"unknown-side cert={cert}"
            )
        else:
            no_cert.append(src)
            tag = f"NO CERT detected"
        print(f"  [{i:>3}/{len(files)}] {src.name:30s} {tag} ({elapsed:.1f}s)")

    # Try to fuzzy-merge cert groups before pairing - OCR sometimes drops a
    # leading or trailing digit, especially on the back hologram. If a cert
    # is a strict suffix or prefix of another (e.g. '21116624' vs '121116624')
    # treat them as the same group, preferring the longer cert as canonical.
    def _fuzzy_merge(by_cert):
        certs = sorted(by_cert.keys(), key=len, reverse=True)
        used = set()
        merged = {}
        for c in certs:
            if c in used:
                continue
            buckets = {"front": list(by_cert[c]["front"]),
                       "back":  list(by_cert[c]["back"]),
                       "unknown": list(by_cert[c]["unknown"])}
            for other in certs:
                if other == c or other in used:
                    continue
                if len(other) >= 6 and (c.endswith(other) or c.startswith(other) or
                                         other.endswith(c) or other.startswith(c)):
                    for k in ("front", "back", "unknown"):
                        buckets[k].extend(by_cert[other][k])
                    used.add(other)
            merged[c] = buckets
            used.add(c)
        return merged

    by_cert = _fuzzy_merge(by_cert)

    # Pass 2 - pair cert groups, run image pipeline.
    print()
    print("=== Pass 2: pair + process ===")
    processed_dir = args.inbox / "_processed"
    processed_dir.mkdir(exist_ok=True)
    moved: list[Path] = []
    summary = {"paired": 0, "front_only": 0, "back_only": 0, "weird": 0}

    for cert, group in by_cert.items():
        fronts = group["front"]
        backs = group["back"]
        unknowns = group["unknown"]

        # If we have a front + back → pair. If we have unknowns, treat them
        # as the missing side (cert was detected but OCR was sparse).
        if len(fronts) == 1 and len(backs) == 1:
            front_info = fronts[0]
            back_info = backs[0]
        elif len(fronts) == 1 and len(backs) == 0 and len(unknowns) == 1:
            front_info = fronts[0]
            back_info = unknowns[0]
        elif len(fronts) == 0 and len(backs) == 1 and len(unknowns) == 1:
            front_info = unknowns[0]
            back_info = backs[0]
        elif len(fronts) >= 1 and len(backs) == 0 and len(unknowns) == 0:
            print(f"  cert {cert}: front-only, no back found - leaving in inbox")
            summary["front_only"] += 1
            continue
        elif len(fronts) == 0 and len(backs) >= 1:
            print(f"  cert {cert}: back-only, no front found - leaving in inbox")
            summary["back_only"] += 1
            continue
        else:
            print(f"  cert {cert}: weird group (fronts={len(fronts)}, "
                  f"backs={len(backs)}, unknowns={len(unknowns)}) - leaving in inbox")
            summary["weird"] += 1
            continue

        front_src = front_info["src"]
        back_src = back_info["src"]
        # Front carries the rich metadata; if it's actually an "unknown" we
        # only have cert which is fine - pokemontcg lookup may still hit.
        parsed = front_info["parsed"]
        if not parsed.get("card_number") and back_info["parsed"].get("card_number"):
            parsed = back_info["parsed"]

        match = None
        if parsed.get("card_number"):
            try:
                match = lookup_pokemontcg(
                    parsed["card_number"],
                    parsed.get("set"),
                    parsed.get("card_title"),
                )
            except Exception as e:
                print(f"  cert {cert}: pokemontcg lookup error ({e}); continuing without enrichment")

        slug_name = slug((match or {}).get("name") or parsed.get("card_title"))
        out_subdir = args.finished / f"{slug_name}-cert{cert}"
        try:
            # Front first — captures the palette derived from the card art.
            front_out, palette = process_one(
                front_src, out_subdir,
                out_name=f"{slug_name}-cert{cert}-front.jpg",
            )
            # Back reuses the front's palette so the wordmark / aura
            # colors match across both gallery images.
            back_out, _ = process_one(
                back_src, out_subdir,
                out_name=f"{slug_name}-cert{cert}-back.jpg",
                palette_override=palette,
            )
        except Exception as e:
            print(f"  cert {cert}: image pipeline failed: {e}")
            continue

        row = build_row(parsed, match, front_out, back_out)
        append_csv(args.csv, row)
        append_edit_csv(args.edit_csv, row)

        identified = (match or {}).get("name") or parsed.get("card_title") or "(unidentified)"
        suggested = (match or {}).get("tcgplayer_market") if match else None
        suggested_str = f"${suggested:.2f}" if suggested else "-"
        print(f"  cert {cert}: {identified} | grade {parsed.get('grade') or '?'} "
              f"| suggested {suggested_str}")
        summary["paired"] += 1

        if not args.keep_originals:
            for src in (front_src, back_src):
                try:
                    shutil.move(str(src), processed_dir / src.name)
                    moved.append(src)
                except Exception as e:
                    print(f"  warn: could not move {src.name}: {e}")

    # Pass 3 - summarize.
    print()
    print("=== Summary ===")
    print(f"  paired:      {summary['paired']}")
    print(f"  front-only:  {summary['front_only']}")
    print(f"  back-only:   {summary['back_only']}")
    print(f"  weird:       {summary['weird']}")
    print(f"  no cert read:{len(no_cert)}")
    if no_cert:
        print()
        print("  Files where OCR didn't find a cert number:")
        for p in no_cert:
            print(f"    {p.name}")
        print()
        print("  -> Try rescanning these (cards may be misaligned, glare on hologram, "
              "or scan resolution too low - bump to 600 dpi if 300 isn't enough).")

    print()
    print(f"Done. Edit {args.csv} to fill in your_price for each card, "
          f"then run upload_to_square.py.")


if __name__ == "__main__":
    main()
