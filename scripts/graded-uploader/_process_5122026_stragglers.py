"""
Manually pair + process the 4 graded scans whose OCR failed/misread
(2 CGC slabs with long 10-digit certs, 1 PSA back where OCR misread
a digit on the hologram, 1 PSA back where OCR missed the hologram).

Pairings (verified by visually inspecting the front images against the
Card Ladder CSV):
  IMG_0001 + IMG_0002 → cert 6021612152 (Ceruledge CGC Pristine 10)
  IMG_0003 + IMG_0004 → cert 6021615021 (Pikachu World Champs CGC Pristine 10)
  IMG_0007 + IMG_0008 → cert 151936010  (Mega Dragonite ex PSA 10)
  IMG_0013 + IMG_0014 → cert 89932897   (Charizard ex SIR Mew EN-151 PSA 10)

Metadata is taken from the Card Ladder CSV (the user's truth source for
graded inventory). Prices are NOT set here — applied later via the
aggressive CL formula and written into pricing-edit.csv / pricing.csv.
"""
from __future__ import annotations

import csv
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from process_card import process_one

HERE = Path(__file__).resolve().parent
INBOX = HERE / "inbox"
FINISHED = HERE / "finished"
PROCESSED = INBOX / "_processed"
PRICING_CSV = HERE / "pricing.csv"

# Pre-paired groups derived from the Card Ladder CSV and visual inspection
# of the unprocessed scans.
GROUPS = [
    {
        "cert":   "6021612152",
        "front":  "IMG_0001.png",
        "back":   "IMG_0002.png",
        "name":   "Ceruledge",
        "year":   "2024",
        "set":    "Paldean Fates",
        "number": "040/091",
        "grade":  "CGC Pristine 10",
        "set_id": "sv4pt5",  # Paldean Fates
    },
    {
        "cert":   "6021615021",
        "front":  "IMG_0003.png",
        "back":   "IMG_0004.png",
        "name":   "Pikachu (World Championships)",
        "year":   "2024",
        "set":    "SVP Black Star Promos",
        "number": "190",
        "grade":  "CGC Pristine 10",
        "set_id": "svp",
    },
    {
        "cert":   "151936010",
        "front":  "IMG_0007.png",
        "back":   "IMG_0008.png",
        "name":   "Mega Dragonite ex (Special Illustration Rare)",
        "year":   "2026",
        "set":    "Ascended Heroes",
        "number": "290",
        "grade":  "PSA 10",
        "set_id": "",  # No pokemontcg.io set for ME2 yet
    },
    {
        "cert":   "89932897",
        "front":  "IMG_0013.png",
        "back":   "IMG_0014.png",
        "name":   "Charizard ex (Special Illustration Rare)",
        "year":   "2023",
        "set":    "Mew EN-151",
        "number": "199",
        "grade":  "PSA 10",
        "set_id": "sv3pt5",  # 151
    },
]

CSV_COLUMNS = [
    "cert", "year", "set", "name", "number", "grade",
    "suggested_price_tcgplayer", "your_price", "condition_note", "offer_min",
    "front_image", "back_image", "pokemontcg_set_id", "identified_at",
]


def slug(s: str, max_len: int = 40) -> str:
    out = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return out[:max_len] or "unknown"


def main() -> None:
    PROCESSED.mkdir(exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    existing_certs = set()
    rows = []
    if PRICING_CSV.exists():
        with PRICING_CSV.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                rows.append(row)
                if row.get("cert"):
                    existing_certs.add(row["cert"])

    for g in GROUPS:
        if g["cert"] in existing_certs:
            print(f"[skip] cert {g['cert']} already in pricing.csv")
            continue

        front_src = INBOX / g["front"]
        back_src = INBOX / g["back"]
        if not front_src.exists() or not back_src.exists():
            print(f"[skip] cert {g['cert']}: missing {front_src.name} or {back_src.name}")
            continue

        slug_name = slug(g["name"])
        out_subdir = FINISHED / f"{slug_name}-cert{g['cert']}"
        out_subdir.mkdir(parents=True, exist_ok=True)

        print(f"[run]  cert {g['cert']} -> {slug_name}/")
        front_out, palette = process_one(
            front_src, out_subdir,
            out_name=f"{slug_name}-cert{g['cert']}-front.jpg",
        )
        back_out, _ = process_one(
            back_src, out_subdir,
            out_name=f"{slug_name}-cert{g['cert']}-back.jpg",
            palette_override=palette,
        )

        rows.append({
            "cert":   g["cert"],
            "year":   g["year"],
            "set":    g["set"],
            "name":   g["name"],
            "number": g["number"],
            "grade":  g["grade"],
            "suggested_price_tcgplayer": "",
            "your_price": "",
            "condition_note": "",
            "offer_min": "",
            "front_image": str(front_out),
            "back_image":  str(back_out),
            "pokemontcg_set_id": g["set_id"],
            "identified_at": now_iso,
        })

        # Move sources to _processed
        for src in (front_src, back_src):
            try:
                shutil.move(str(src), PROCESSED / src.name)
            except Exception as e:
                print(f"  warn: could not move {src.name}: {e}")

    # Write back the merged pricing.csv
    with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"\n[done] pricing.csv now has {len(rows)} rows.")


if __name__ == "__main__":
    main()
