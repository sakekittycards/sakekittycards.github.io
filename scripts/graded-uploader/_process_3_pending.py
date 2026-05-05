"""
Run the full image pipeline (crop + upscale + brand-color composition) on the
3 cards we uploaded with raw scans because process_inbox.py couldn't OCR
their certs cleanly. Outputs land in finished/<slug>-cert<NNN>/ — the same
folder layout the regular pipeline uses.

Cards:
  - cert 139036804 (Zapdos Holo)         IMG_0009 + IMG_0010
  - cert 147655076 (Pikachu VMAX)        IMG_0007 + IMG_0008
  - cert 4321131035 (Blastoise ex SAR)   IMG_0011 + IMG_0012

Inputs come from inbox/ (still has the originals); outputs replace what's in
finished/torkoal-cert139036804/ for Zapdos and create new folders for the
other two.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from process_card import process_one


CARDS = [
    {
        "cert":  "139036804",
        "slug":  "zapdos-holo-cert139036804",
        "front": HERE / "inbox" / "IMG_0009.jpg",
        "back":  HERE / "inbox" / "IMG_0010.jpg",
    },
    {
        "cert":  "147655076",
        "slug":  "pikachu-vmax-cert147655076",
        "front": HERE / "inbox" / "IMG_0007.jpg",
        "back":  HERE / "inbox" / "IMG_0008.jpg",
    },
    {
        "cert":  "4321131035",
        "slug":  "blastoise-ex-sar-cert4321131035",
        "front": HERE / "inbox" / "IMG_0011.jpg",
        "back":  HERE / "inbox" / "IMG_0012.jpg",
    },
]


def main() -> int:
    finished_root = HERE / "finished"
    for c in CARDS:
        out_dir = finished_root / c["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        if not c["front"].exists():
            print(f"[proc] missing front for cert {c['cert']}: {c['front']}"); continue
        # Process front first to capture palette, reuse on back so brand
        # colors match across the pair.
        front_out, palette = process_one(
            c["front"], out_dir,
            out_name=f"{c['slug']}-front.jpg",
            upscale=4,
        )
        if c["back"].exists():
            back_out, _ = process_one(
                c["back"], out_dir,
                out_name=f"{c['slug']}-back.jpg",
                palette_override=palette,
                upscale=4,
            )
        print(f"[proc] cert {c['cert']} done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
