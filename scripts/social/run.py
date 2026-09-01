# -*- coding: utf-8 -*-
"""The local content agent — one command runs a whole pass.

    python scripts/social/run.py

It does four things, in order:

  1. reads `assets/events-data.js` and reconciles the engine's mirror
  2. asks the worker which promotion opportunities are due
  3. renders a graphic and writes a caption for each
  4. uploads them and files a DRAFT

It never approves, never schedules and never publishes. The worker owns those,
and the split is deliberate: this script decides nothing. It is the hands, not
the head — which is why the machine being switched off delays content rather
than losing it, and why running this twice produces the same drafts rather than
duplicates.

Flyers: if an event carries an organizer flyer URL, `--flyers` fetches it and
uses the flyer template instead of the generated banner. See flyer.py for what
counts as an acceptable source; the short version is that it must be first-party
artwork we were pointed at, never an image search result.
"""
from __future__ import annotations

import argparse
import io as _io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image

import captions
import flyer as flyer_mod
import ingest
import sk_brand as B
import templates as T
from client import Client, SocialError


def jpeg_bytes(img: Image.Image, quality: int = 92) -> bytes:
    """Instagram re-encodes everything anyway; 92 is the point past which the
    upload gets bigger without the post looking better."""
    buf = _io.BytesIO()
    img.save(buf, "JPEG", quality=quality, subsampling=0, optimize=True)
    return buf.getvalue()


def render_for(ev: dict, kind: str, cv, flyer_img: Image.Image | None):
    if flyer_img is not None:
        return T.render_flyer(ev, kind, flyer_img, cv), "flyer"
    return T.render_banner(ev, kind, cv), "banner"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-ingest", action="store_true")
    ap.add_argument("--flyers", action="store_true",
                    help="try to fetch organizer artwork for events that name one")
    ap.add_argument("--canvas", default="feed", choices=["feed", "square", "story"])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true",
                    help="render and print, upload nothing")
    ap.add_argument("--save-to", help="also write the rendered PNGs here")
    args = ap.parse_args()

    cv = {"feed": B.FEED_45, "square": B.FEED_11, "story": B.STORY_916}[args.canvas]
    c = Client()

    health = c.health()
    print(f"worker: {c.base}")
    print(f"  publish mode : {health['mode']}  (deploy={health['deploy_mode']})")
    print(f"  instagram    : {'configured' if health['instagram_configured'] else 'NOT CONFIGURED'}")
    print()

    # 1 — ingest
    if not args.skip_ingest:
        events = [ingest.normalize(r) for r in ingest.load_events()]
        res = c.post("/events/ingest", {"events": events})
        ev = res["events"]
        print(f"events: {len(ev['added'])} new · {len(ev['material'])} materially changed "
              f"· {len(ev['cancelled'])} cancelled · {ev['unchanged']} unchanged")
        for m in ev["material"]:
            print(f"   changed: {m['id']} ({', '.join(x['field'] for x in m['changed'])})")
        for cid in ev["cancelled"]:
            print(f"   CANCELLED: {cid}")
        o = res["opportunities"]
        print(f"opportunities: +{o['created']} · {o['retired']} retired · {o['expired']} expired")
        print()

    # 2 — what is due
    due = c.get("/opportunities/due")
    policy = due["policy"]
    items = due["due"][: args.limit]
    if not items:
        print("nothing due. Every eligible promotion already has a draft.")
        return 0

    print(f"{len(items)} opportunit{'y' if len(items) == 1 else 'ies'} due:\n")

    made = 0
    for row in items:
        opp, ev = row["opportunity"], row["event"]
        kind = opp["kind"]
        label = f"{ev['title']} — {kind}"
        print(f"  {label}")

        # 3 — flyer, then graphic, then caption
        flyer_img, flyer_media = None, None
        if args.flyers:
            try:
                flyer_media = flyer_mod.resolve(c, ev)
                if flyer_media:
                    flyer_img = flyer_mod.load(c, flyer_media)
                    print(f"     official flyer: {flyer_media.get('source_url')}")
            except Exception as e:
                print(f"     no usable flyer ({e}) — generating our own")

        img, template = render_for(ev, kind, cv, flyer_img)
        cap = captions.build(ev, kind, policy)

        if cap["warnings"]:
            for w in cap["warnings"]:
                print(f"     caption warning: {w}")

        if args.save_to:
            os.makedirs(args.save_to, exist_ok=True)
            safe = "".join(ch if ch.isalnum() else "-" for ch in ev["title"])[:40]
            path = os.path.join(args.save_to, f"{kind}-{safe}.png")
            img.save(path)
            print(f"     saved {path}")

        if args.dry_run:
            print("     --- caption ---")
            for line in cap["caption"].splitlines():
                print(f"     {line}")
            print(f"     {' '.join(cap['hashtags'])}")
            print()
            continue

        # 4 — upload + draft
        media = c.upload_image(
            jpeg_bytes(img), width=img.width, height=img.height, template=template,
            source_kind="flyer-derivative" if flyer_img is not None else "generated",
            provenance={"event_id": ev["id"], "opportunity": opp["id"],
                        "flyer_media": flyer_media["id"] if flyer_media else None},
        )
        res = c.post("/items/event", {
            "event_id": ev["id"], "opportunity_id": opp["id"], "kind": kind,
            "caption": cap["caption"], "hashtags": cap["hashtags"],
            "media_id": media["id"], "surface": "story" if args.canvas == "story" else "feed",
            "warnings": cap["warnings"], "target_at": opp["target_at"],
        })
        made += 1
        print(f"     draft {res['id']}  media {media['id']}"
              f"{'  (auto-approved by policy)' if res.get('auto_approved') else ''}")
        print()

    if args.dry_run:
        print(f"--dry-run: {len(items)} draft(s) would have been created")
    else:
        print(f"{made} draft(s) created and awaiting approval.")
        print("Open social.html, or: python scripts/social/run.py --help")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SocialError as e:
        print(f"error: {e}")
        sys.exit(1)
