"""
Manually pair + process the 2 graded scans from 5/13 whose backs OCR
missed (RapidOCR couldn't read the PSA back-hologram cert).

Pairings verified against the Card Ladder (14) CSV — fronts OCR'd
correctly, backs are the odd+1 IMG following each front:
  IMG_0001 (front, cert=156593992) + IMG_0002 (back) → Reshiram ex White Flare PSA 10
  IMG_0003 (front, cert=104313026) + IMG_0004 (back) → Palafin Illustration Rare PSA 10

Metadata comes from the CL CSV (truth source).  Prices are NOT set here;
applied via the multisource reprice formula after this lands rows in
pricing.csv.
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

GROUPS = [
    {
        "cert":   "156593992",
        "front":  "IMG_0001.png",
        "back":   "IMG_0002.png",
        "name":   "Reshiram ex (Black White Rare)",
        "year":   "2025",
        "set":    "White Flare",
        "number": "173",
        "grade":  "PSA 10",
        "set_id": "",  # White Flare pokemontcg.io set id TBD
    },
    {
        "cert":   "104313026",
        "front":  "IMG_0003.png",
        "back":   "IMG_0004.png",
        "name":   "Palafin (Illustration Rare)",
        "year":   "2024",
        "set":    "Paldean Fates",
        "number": "225",
        "grade":  "PSA 10",
        "set_id": "sv4pt5",  # Paldean Fates
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

        for src in (front_src, back_src):
            try:
                shutil.move(str(src), PROCESSED / src.name)
            except Exception as e:
                print(f"  warn: could not move {src.name}: {e}")

    with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"\n[done] pricing.csv now has {len(rows)} rows.")


if __name__ == "__main__":
    main()
