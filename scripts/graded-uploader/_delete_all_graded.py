"""
Delete every graded item currently on the Square catalog.

Identifies "graded" by the same heuristic the inspect route uses:
- name contains PSA / CGC / BGS / SGC, OR
- description contains "Cert #"

Merch (hats, t-shirts, mouse pads, etc.) is never matched and stays untouched.

Auth: SK_ADMIN_TOKEN env var (User-scope on Windows). Worker enforces.
Endpoint: POST /admin/delete-item with body {"item_id": "..."}.

Usage:
    python _delete_all_graded.py             # actually deletes
    python _delete_all_graded.py --dry-run   # lists what would be deleted, no API calls
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT_URL = f"{WORKER_BASE}/admin/inspect?types=ITEM"
DELETE_URL  = f"{WORKER_BASE}/admin/delete-item"


def get_admin_token() -> str | None:
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t:
        return t.strip()
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def is_graded(item: dict) -> bool:
    data = item.get("item_data") or {}
    name = (data.get("name") or "").lower()
    desc = (data.get("description") or "").lower()
    if "cert #" in desc:
        return True
    return any(k in name for k in (" psa ", " cgc ", " bgs ", " sgc ")) \
        or name.startswith(("psa ", "cgc ", "bgs ", "sgc "))


def fetch_all_items(token: str) -> list[dict]:
    req = urllib.request.Request(
        INSPECT_URL,
        headers={
            "X-Sake-Admin-Token": token,
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    return d.get("objects", [])


def delete_item(item_id: str, token: str) -> tuple[bool, str]:
    body = json.dumps({"item_id": item_id}).encode("utf-8")
    req = urllib.request.Request(
        DELETE_URL,
        method="POST",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Sake-Admin-Token": token,
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="list targets only")
    args = p.parse_args()

    token = get_admin_token()
    if not token:
        print("[delete] SK_ADMIN_TOKEN not set"); return 1

    items = fetch_all_items(token)
    graded = [it for it in items if is_graded(it)]
    other  = [it for it in items if not is_graded(it)]

    print(f"[delete] {len(items)} catalog items: {len(graded)} graded, {len(other)} other")
    print(f"[delete] {len(other)} non-graded (merch etc.) will be IGNORED:")
    for it in other:
        print(f"           - {(it.get('item_data') or {}).get('name','')[:80]}")
    print()

    if args.dry_run:
        print(f"[delete] DRY RUN — would delete {len(graded)} graded items:")
        for it in graded:
            print(f"           - {(it.get('item_data') or {}).get('name','')[:80]}  ({it.get('id')})")
        return 0

    ok = 0
    fail = 0
    for i, it in enumerate(graded, 1):
        item_id = it.get("id", "")
        name = (it.get("item_data") or {}).get("name", "")[:80]
        success, err = delete_item(item_id, token)
        if success:
            ok += 1
            print(f"[delete] {i:>2}/{len(graded)} OK  {item_id}  {name}")
        else:
            fail += 1
            print(f"[delete] {i:>2}/{len(graded)} ERR {item_id}  {err}")
        time.sleep(0.3)  # be polite to the worker / Square

    print()
    print(f"[delete] done — {ok} deleted, {fail} failed")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
