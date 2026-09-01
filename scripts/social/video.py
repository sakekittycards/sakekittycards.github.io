# -*- coding: utf-8 -*-
"""Video intake for the social engine.

Scans the finished-shorts folder, probes each file with ffprobe, hashes it, and
registers it with the worker.

## What this deliberately does NOT do

It does not approve anything. Not for any folder, not for any filename, not for
any render that finished cleanly. Everything it registers lands in REVIEW.

That is not caution for its own sake. Until 2026-08-31 the pipeline had a
`_staging` folder that meant "built, awaiting Nick", and the root of
`SHORT FORM FINAL` meant "he said yes". On 8/31 the staging step was removed and
builds started landing directly in the root, so that folder now holds approved
shorts, unreviewed builds and shorts Nick killed, mixed together. Anything that
read approval off the path would have been wrong from that day onward.

The `_archive/`, `_rejected_qc/` and `_staging/` subfolders ARE meaningful — they
record a decision that was made — so files there are skipped or registered with a
note, but never treated as approval either.

    python scripts/social/video.py scan          # probe + register everything
    python scripts/social/video.py list          # what is waiting for review
    python scripts/social/video.py show <id>
    python scripts/social/video.py approve <id> --by nick
    python scripts/social/video.py reject <id> --by nick --reason "..."
    python scripts/social/video.py deliver <id>  # upload the approved bytes
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from client import Client, SocialError

SHORTS_DIR = r"D:\Dropbox\SAKE KITTY CARDS PROJECT\SHORT FORM FINAL"

# Subfolders that record a human decision. None of them is an approval; two of
# them are the opposite, and are skipped entirely.
SKIP_DIRS = {"_archive", "_rejected_qc"}
NOTE_DIRS = {"_staging": "was in _staging when scanned"}


def ffprobe_path() -> str:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    guess = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
        r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        r"\ffmpeg-8.1-full_build\bin\ffprobe.exe")
    if os.path.exists(guess):
        return guess
    raise SystemExit("ffprobe not found on PATH")


def ffmpeg_path() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    guess = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
        r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        r"fmpeg-8.1-full_buildinfmpeg.exe")
    if os.path.exists(guess):
        return guess
    raise SystemExit("ffmpeg not found on PATH")


def poster_frame(path: str, at_s: float) -> bytes:
    """A single JPEG frame, for the reviewer to look at.

    Approving a video you cannot see is the exact failure this system exists to
    prevent, so the console has to show something. The frame is taken a little
    way in rather than at 0s — the first frames of these shorts are usually a
    fade-in from black, which would give every row an identical black tile.
    """
    out = subprocess.run(
        [ffmpeg_path(), "-nostdin", "-v", "error", "-ss", f"{at_s:.2f}", "-i", path,
         "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "5", "-f", "image2", "-"],
        capture_output=True)
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(out.stderr.decode(errors="replace")[:200] or "no frame")
    return out.stdout


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    """Hash the whole file.

    Not a sample of it: the whole point is to detect a re-render that changed a
    couple of seconds in the middle, and a head+tail hash would miss exactly
    that edit.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def probe(path: str) -> dict:
    out = subprocess.run(
        [ffprobe_path(), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {out.stderr.strip()[:200]}")
    data = json.loads(out.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})

    fps = None
    if v.get("avg_frame_rate") and "/" in v["avg_frame_rate"]:
        num, den = v["avg_frame_rate"].split("/")
        fps = round(int(num) / int(den), 3) if int(den) else None

    st = os.stat(path)
    digest = sha256_file(path)
    return {
        # The id is derived from the path, not the content: the row must survive
        # a re-render of the same short so the history stays on one asset.
        "id": "vid_" + hashlib.sha256(os.path.abspath(path).lower().encode()).hexdigest()[:20],
        "title": title_from(path),
        "source_path": os.path.abspath(path),
        "final_path": os.path.abspath(path),
        "sha256": digest,
        "bytes": st.st_size,
        "duration_s": round(float(fmt.get("duration", 0)) or 0, 3) or None,
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": fps,
        "vcodec": v.get("codec_name"),
        "acodec": a.get("codec_name") if a else None,
        "container": (fmt.get("format_name") or "").split(",")[0],
        "has_audio": bool(a),
    }


def title_from(path: str) -> str:
    r"""The Nick-facing name. Both naming conventions are live in the folder.

    Current:  `SK 5.17.26 - The Kid's Binder.mp4`   -> "The Kid's Binder"
    Legacy:   `SK_523_06_danny-trade-recap.mp4`     -> "Danny Trade Recap"

    The legacy form is `SK_<MMDD>_<NN>_<slug>`, where MMDD runs together (523 =
    May 23) — which is why a `\d{1,2}[._]\d{1,2}` date pattern misses it and the
    two forms need separate matches.
    """
    stem = os.path.splitext(os.path.basename(path))[0]

    m = re.match(r"^SK[ _]\d{3,4}[_ ](?:[A-Z0-9]{2,6}[_ ])?(.+)$", stem)
    if m:
        return _prettify(m.group(1))

    m = re.match(r"^SK[ _]\d{1,2}[._]\d{1,2}(?:[._]\d{2})?[ _-]+(.+)$", stem)
    if m:
        return _prettify(m.group(1))

    return _prettify(stem)


def _prettify(rest: str) -> str:
    rest = rest.strip(" _-")
    # A hyphen/underscore slug with no spaces is machine-written; a name with
    # spaces was typed by a human and is left exactly as it is.
    if " " not in rest and ("-" in rest or "_" in rest):
        rest = rest.replace("_", " ").replace("-", " ").title()
    return rest or "untitled"


def walk(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        top = rel.split(os.sep)[0] if rel != "." else ""
        if top in SKIP_DIRS:
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.lower().endswith((".mp4", ".mov")):
                yield os.path.join(dirpath, fn), NOTE_DIRS.get(top)


def cmd_scan(args):
    # The client is built after the walk so `--dry-run` works with no token —
    # it is the mode you reach for when checking what the scanner sees.
    root = args.dir or SHORTS_DIR
    if not os.path.isdir(root):
        raise SystemExit(f"not a directory: {root}")

    files = list(walk(root))
    print(f"scanning {root}\n{len(files)} video file(s)\n")

    batch, skipped = [], 0
    for path, note in files:
        try:
            p = probe(path)
        except Exception as e:
            print(f"  !! {os.path.basename(path)}: {e}")
            skipped += 1
            continue
        if note:
            p["note"] = note
        batch.append(p)
        print(f"  {p['title'][:44]:46s} {p['width']}x{p['height']} "
              f"{p['duration_s']:>6.1f}s  {p['sha256'][:10]}")

    if args.dry_run:
        print(f"\n--dry-run: {len(batch)} would be registered (all as REVIEW)")
        return 0

    c = Client()
    res = c.post("/video/register-batch", {"videos": batch, "source": "final-folder-scan"})
    created = sum(1 for r in res["results"] if r.get("created"))
    invalid = [r for r in res["results"] if r.get("invalidated")]
    print(f"\nregistered {len(res['results'])} · {created} new (state REVIEW) · {skipped} unreadable")
    if invalid:
        print(f"\n{len(invalid)} previously-approved video(s) CHANGED ON DISK and were sent back")
        print("to review — their approval no longer applies:")
        for r in invalid:
            print(f"  {r['id']}")
    print("\nNothing here is approved. Approve in the console, or:")
    print("  python scripts/social/video.py approve <id> --by nick")
    return 0


def cmd_posters(args):
    """Generate and attach a poster frame for every video still in REVIEW."""
    c = Client()
    vids = c.get("/video", state="REVIEW")["videos"]
    todo = [v for v in vids if not v.get("cover_media_id")][: args.limit]
    print(f"{len(todo)} video(s) without a poster frame")
    done = 0
    for v in todo:
        path = v.get("final_path") or v["source_path"]
        if not os.path.exists(path):
            print(f"  !! {v['title'][:44]:46s} file is gone")
            continue
        try:
            # A fifth of the way in, capped, so we land on real content.
            at_s = min(max((v.get("duration_s") or 10) * 0.2, 1.5), 12.0)
            jpg = poster_frame(path, at_s)
            import base64
            media = c.post("/media/upload", {
                "data_b64": base64.b64encode(jpg).decode(),
                "kind": "image", "content_type": "image/jpeg",
                "source_kind": "video-poster", "acquisition": "ffmpeg-frame",
                "original_name": os.path.basename(path),
                "provenance": {"video_id": v["id"], "frame_at_s": round(at_s, 2)},
            })["media"]
            c.post("/video/poster", {"id": v["id"], "media_id": media["id"]})
            done += 1
            print(f"  {v['title'][:44]:46s} frame @ {at_s:4.1f}s  {media['id']}")
        except Exception as e:
            print(f"  !! {v['title'][:44]:46s} {e}")
    print(f"{done} poster frame(s) attached — the console can now show what it is asking you to approve.")
    return 0


def cmd_list(args):
    c = Client()
    res = c.get("/video", state=args.state)
    vids = res["videos"]
    if not vids:
        print("nothing registered yet — run: python scripts/social/video.py scan")
        return 0
    for v in vids:
        compat = v["compatibility"]
        flag = "OK " if compat["ok"] else "!! "
        appr = f"approved by {v['approved_by']}" if v.get("approved_by") else ""
        print(f"{flag}{v['state']:20s} {v['title'][:40]:42s} "
              f"{(v.get('duration_s') or 0):>6.1f}s  {v['id']}  {appr}")
        for b in compat["blockers"]:
            print(f"     BLOCKER {b}")
        for w in compat["warnings"]:
            print(f"     warn    {w}")
    return 0


def cmd_show(args):
    c = Client()
    d = c.get("/video/detail", id=args.id)
    v = d["video"]
    print(f"{v['title']}\n{'=' * len(v['title'])}")
    for k in ("id", "state", "source_path", "sha256", "bytes", "duration_s",
              "width", "height", "fps", "vcodec", "acodec", "container",
              "approved_at", "approved_by", "approval_source", "approval_note",
              "approved_sha256", "media_id"):
        print(f"  {k:17s} {v.get(k)}")
    print("\ncompatibility:", "OK" if d["compatibility"]["ok"] else "BLOCKED")
    for b in d["compatibility"]["blockers"]:
        print(f"  BLOCKER {b}")
    for w in d["compatibility"]["warnings"]:
        print(f"  warn    {w}")
    print("\nhistory:")
    for h in d["history"]:
        print(f"  {h['at']}  {h['from_state'] or '-'} -> {h['to_state']:20s} "
              f"{h['source'] or ''} {h['note'] or ''}")
    return 0


def cmd_approve(args):
    c = Client()
    d = c.get("/video/detail", id=args.id)
    v = d["video"]
    compat = d["compatibility"]

    print(f"{v['title']}")
    print(f"  {v['width']}x{v['height']}  {v['duration_s']}s  {v['vcodec']}/{v['acodec']}")
    print(f"  {v['source_path']}")
    print(f"  sha256 {v['sha256']}")
    if compat["blockers"]:
        print("\nInstagram would reject this file:")
        for b in compat["blockers"]:
            print(f"  - {b}")
        if not args.force:
            print("\nRefusing. Fix the file, or pass --force to approve anyway.")
            return 1
    for w in compat["warnings"]:
        print(f"  warn: {w}")

    # `expect_sha256` binds the approval to the bytes just displayed. If the file
    # changed between this print and the call, the worker refuses.
    res = c.post("/video/approve", {
        "id": args.id, "by": args.by, "source": args.source,
        "note": args.note, "expect_sha256": v["sha256"],
    })
    print(f"\nAPPROVED by {args.by}. Bytes pinned to {v['sha256'][:16]}…")
    print("A re-render of this file will drop the approval automatically.")
    print("\nNext: python scripts/social/video.py deliver " + args.id)
    return 0 if res.get("ok") else 1


def cmd_reject(args):
    c = Client()
    c.post("/video/reject", {"id": args.id, "by": args.by, "reason": args.reason})
    print(f"rejected: {args.id}")
    return 0


def cmd_deliver(args):
    """Upload the approved bytes so Instagram has something to fetch.

    The worker re-checks the hash on arrival and refuses anything that is not
    the approved file, so this cannot be used to slip a different cut through.
    """
    c = Client()
    d = c.get("/video/detail", id=args.id)
    v = d["video"]
    if not v.get("approved_at"):
        print(f"{v['title']} is {v['state']} — approve it first.")
        return 1

    path = v["final_path"] or v["source_path"]
    print(f"uploading {os.path.basename(path)} ({v['bytes'] / 1e6:.1f} MB)…")
    live = sha256_file(path)
    if live != v["approved_sha256"]:
        print("the file on disk no longer matches what was approved:")
        print(f"  approved {v['approved_sha256'][:24]}…")
        print(f"  on disk  {live[:24]}…")
        print("Re-run `scan` — the worker will drop the approval and it can be re-reviewed.")
        return 1

    media = c.upload_video(path, provenance={"video_id": args.id, "approved_by": v["approved_by"]})
    c.post("/video/attach-media", {"id": args.id, "media_id": media["id"]})
    print(f"delivered. media {media['id']} · state READY_FOR_INSTAGRAM")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan"); s.add_argument("--dir"); s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("posters"); s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_posters)
    s = sub.add_parser("list"); s.add_argument("--state"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("show"); s.add_argument("id"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("approve")
    s.add_argument("id"); s.add_argument("--by", required=True)
    s.add_argument("--source", default="cli"); s.add_argument("--note")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("reject")
    s.add_argument("id"); s.add_argument("--by", required=True); s.add_argument("--reason")
    s.set_defaults(fn=cmd_reject)
    s = sub.add_parser("deliver"); s.add_argument("id"); s.set_defaults(fn=cmd_deliver)

    args = ap.parse_args()
    try:
        return args.fn(args)
    except SocialError as e:
        print(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
