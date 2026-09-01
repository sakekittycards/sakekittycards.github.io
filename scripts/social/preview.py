# -*- coding: utf-8 -*-
"""Render a contact sheet of the templates against real events.

The point is to look at the hard cases before shipping, not the easy one. The
sample deliberately includes the longest show name on the calendar, a
cross-month multi-day run, an online stream and a show with no venue parsed —
those are where a layout breaks.

    python scripts/social/preview.py                 # 4:5 sheet
    python scripts/social/preview.py --canvas story  # 9:16
    python scripts/social/preview.py --out DIR       # also write the full-size PNGs
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw

import ingest
import sk_brand as B
import templates as T

CANVASES = {"feed": B.FEED_45, "square": B.FEED_11, "story": B.STORY_916}


def pick_samples(events: list[dict]) -> list[tuple[dict, str]]:
    """One of each shape that has broken a layout before."""
    upcoming = [e for e in events if not e["masked"]]
    by_title = {e["title"]: e for e in upcoming}

    longest = max(upcoming, key=lambda e: len(e["title"]))
    multi = next((e for e in upcoming if e.get("end_date")
                  and e["end_date"][:7] != e["event_date"][:7]), None)
    multi = multi or next(e for e in upcoming if e.get("end_date"))
    online = next((e for e in upcoming if e["kind"] == "online"), None)
    noven = next((e for e in upcoming if not e["venue"] and e["kind"] == "show"), None)

    out = [
        (by_title.get("Stuart Card Show") or upcoming[0], "THIS_WEEKEND"),
        (longest, "ANNOUNCEMENT"),
        (multi, "UPCOMING"),
    ]
    if online:
        out.append((online, "ANNOUNCEMENT"))
    if noven:
        out.append((noven, "UPCOMING"))
    short = min(upcoming, key=lambda e: len(e["title"]))
    out.append((short, "ANNOUNCEMENT"))
    seen, uniq = set(), []
    for ev, kind in out:
        key = (ev["title"], ev["event_date"], kind)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((ev, kind))
    return uniq


def sheet(tiles: list[tuple[str, Image.Image]], cols: int = 3, tile_w: int = 460) -> Image.Image:
    scaled = []
    for label, im in tiles:
        h = int(im.height * tile_w / im.width)
        scaled.append((label, im.resize((tile_w, h), Image.LANCZOS)))
    rows = (len(scaled) + cols - 1) // cols
    cell_h = max(im.height for _, im in scaled) + 34
    out = Image.new("RGB", (cols * (tile_w + 20) + 20, rows * (cell_h + 20) + 20), (18, 18, 24))
    d = ImageDraw.Draw(out)
    f = B.font(B.INTER_SB, 15)
    for i, (label, im) in enumerate(scaled):
        cx = 20 + (i % cols) * (tile_w + 20)
        cy = 20 + (i // cols) * (cell_h + 20)
        d.text((cx, cy), label, font=f, fill=(200, 200, 214))
        out.paste(im, (cx, cy + 26))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canvas", default="feed", choices=list(CANVASES))
    ap.add_argument("--out", default=None, help="directory for full-size PNGs")
    ap.add_argument("--sheet", default="social-templates.png")
    args = ap.parse_args()

    cv = CANVASES[args.canvas]
    events = [ingest.normalize(r) for r in ingest.load_events()]
    tiles = []
    for ev, kind in pick_samples(events):
        img = T.render_banner(ev, kind, cv)
        label = f"{kind} · {ev['title'][:36]}"
        tiles.append((label, img))
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            safe = "".join(c if c.isalnum() else "-" for c in ev["title"])[:40]
            img.save(os.path.join(args.out, f"{args.canvas}-{kind}-{safe}.png"))
        print(f"rendered {label}  {img.size}")

    s = sheet(tiles, cols=3 if args.canvas != "story" else 4,
              tile_w=460 if args.canvas != "story" else 320)
    s.save(args.sheet)
    print(f"\nsheet -> {args.sheet}  {s.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
