"""
Replace the raw inbox JPGs currently on Square (for the 3 cards we
force-uploaded earlier) with the processed images from finished/<slug>/.

Reads finished/{slug}-cert{cert}/{slug}-cert{cert}-{front,back}.jpg, base64-
encodes them, posts to /admin/replace-graded-images with cert + new images.
The worker deletes the old images and attaches the new ones (front primary).

Run after _process_3_pending.py finishes generating the processed JPGs.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"

CARDS = [
    ("139036804",  "zapdos-holo-cert139036804"),
    ("147655076",  "pikachu-vmax-cert147655076"),
    ("4321131035", "blastoise-ex-sar-cert4321131035"),
]


def get_token() -> str | None:
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t: return t.strip()
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return r.stdout.strip() or None
    except Exception: return None


def b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode("ascii")


def main() -> int:
    token = get_token()
    if not token: print("[repl] SK_ADMIN_TOKEN not set"); return 1
    finished_root = HERE / "finished"
    for cert, slug in CARDS:
        folder = finished_root / slug
        front = folder / f"{slug}-front.jpg"
        back  = folder / f"{slug}-back.jpg"
        if not front.exists():
            print(f"[repl] skip cert {cert}: {front.name} missing"); continue
        body = {
            "cert":                  cert,
            "image_base64":          b64(front),
            "image_filename":        front.name,
        }
        if back.exists():
            body["back_image_base64"]   = b64(back)
            body["back_image_filename"] = back.name
        req = urllib.request.Request(
            f"{WORKER_BASE}/admin/replace-graded-images",
            method="POST",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Sake-Admin-Token": token,
                "User-Agent": "Mozilla/5.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read())
            print(f"[repl] cert {cert}  OK  {resp.get('item_id', '?')}")
        except urllib.error.HTTPError as e:
            print(f"[repl] cert {cert}  HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
        except Exception as e:
            print(f"[repl] cert {cert}  ERR {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
