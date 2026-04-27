"""
Sanity-check OCR on the PSA label of sample slab photos.

Crops the slab, isolates the top label band, runs RapidOCR, parses
the meta out, then optionally hits pokemontcg.io to enrich.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from process_card import crop_slab
from psa import isolate_label, parse_psa, lookup_pokemontcg


def main():
    sources = [Path(p) for p in sys.argv[1:]]
    if not sources:
        print("Usage: python test_ocr.py <slab.webp> [<slab2.webp> ...]")
        sys.exit(1)

    print("Loading RapidOCR (first run downloads ~10MB of ONNX models)...")
    ocr = RapidOCR()

    for src in sources:
        print(f"\n--- {src.name} ---")
        if not src.exists():
            print("  MISSING file; skipping")
            continue

        img = Image.open(src).convert("RGB")
        cropped = crop_slab(img)
        label = isolate_label(cropped)
        result, elapsed = ocr(np.asarray(label))
        if result is None:
            print("  no text detected")
            continue

        lines = []
        print(f"  raw OCR ({sum(elapsed):.2f}s):")
        for entry in result:
            text = next((x for x in entry if isinstance(x, str)), None)
            if text is None:
                continue
            print(f"    {text!r}")
            lines.append(text)

        parsed = parse_psa(lines)
        print(f"  parsed:")
        for k, v in parsed.items():
            print(f"    {k:12s} = {v!r}")

        if parsed.get("card_number"):
            print(f"  pokemontcg.io enrichment:")
            match = lookup_pokemontcg(
                parsed["card_number"],
                parsed.get("set"),
                parsed.get("card_title"),
            )
            if match:
                print(f"    matched via {match['match_query']!r}")
                for k, v in match.items():
                    if k == "match_query":
                        continue
                    print(f"    {k:18s} = {v!r}")
            else:
                print("    no match (likely a Japanese-only or recent promo not in DB)")


if __name__ == "__main__":
    main()
