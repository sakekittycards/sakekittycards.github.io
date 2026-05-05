"""
Delete every Square graded item whose cert is NOT in _owned_certs.txt.

_owned_certs.txt is the OCR-derived ground truth from the Graded Pic folder
(D:\\Dropbox\\Personal Use\\Graded Pic). Anything currently listed on Square
that isn't in that file = the user no longer owns it = delist.

Run with --dry-run to preview targets first.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWNED_PATH = HERE / "_owned_certs.txt"
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"


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


def fetch_square(token: str) -> list[dict]:
    req = urllib.request.Request(
        f"{WORKER_BASE}/admin/inspect?types=ITEM",
        headers={"X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("objects", [])


def is_graded(item: dict) -> bool:
    data = item.get("item_data") or {}
    name = (data.get("name") or "").lower()
    desc = (data.get("description") or "").lower()
    if "cert #" in desc: return True
    return any(k in name for k in (" psa ", " cgc ", " bgs ", " sgc ")) \
        or name.startswith(("psa ", "cgc ", "bgs ", "sgc "))


def cert_from_description(item: dict) -> str | None:
    desc = (item.get("item_data") or {}).get("description", "") or ""
    m = re.search(r"Cert #:\s*(\d+)", desc)
    return m.group(1) if m else None


def delete_item(item_id: str, token: str) -> tuple[bool, str]:
    body = json.dumps({"item_id": item_id}).encode("utf-8")
    req = urllib.request.Request(
        f"{WORKER_BASE}/admin/delete-item",
        method="POST", data=body,
        headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token,
                 "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = get_token()
    if not token: print("[del] SK_ADMIN_TOKEN not set"); return 1
    if not OWNED_PATH.exists(): print(f"[del] {OWNED_PATH} not found — run _ocr_inventory.py first"); return 1

    owned = {ln.strip() for ln in OWNED_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()}
    # Owned certs may have leading-zero variants from BGS slabs. Strip leading
    # zeros for a secondary lookup so "0014250139" matches "14250139" if Square
    # stored it without the zeros.
    owned_stripped = {c.lstrip("0") for c in owned}

    print(f"[del] {len(owned)} owned certs from {OWNED_PATH.name}")

    items = fetch_square(token)
    graded = [it for it in items if is_graded(it)]
    print(f"[del] Square: {len(items)} items, {len(graded)} graded")

    keep, delete = [], []
    for it in graded:
        cert = cert_from_description(it)
        name = (it.get("item_data") or {}).get("name", "")
        if cert and (cert in owned or cert.lstrip("0") in owned_stripped):
            keep.append((cert, it.get("id"), name))
        else:
            delete.append((cert, it.get("id"), name))

    print(f"[del]   keep (cert in owned set): {len(keep)}")
    print(f"[del]   delete (cert NOT in owned set): {len(delete)}")
    print()

    if args.dry_run:
        print("Targets:")
        for cert, _id, name in delete:
            print(f"  cert {cert or '?'}  {name[:80]}")
        print("\n[del] DRY RUN — no changes")
        return 0

    print("Deleting:")
    ok = fail = 0
    for i, (cert, item_id, name) in enumerate(delete, 1):
        success, err = delete_item(item_id, token)
        if success:
            ok += 1
            print(f"[del] {i:>2}/{len(delete)} OK  cert {cert or '?'}  {name[:65]}")
        else:
            fail += 1
            print(f"[del] {i:>2}/{len(delete)} ERR cert {cert or '?'}  {err}")
        time.sleep(0.3)

    print()
    print(f"[del] done — {ok} deleted, {fail} failed")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
