"""Re-title Square graded items so their names match the Card Ladder CSV.

For each cert in the Card Ladder export, build the canonical Square title
(`<grader> <grade> <year> <set sans 'Pokemon'> <player> #<number>`) and POST
to the worker's /admin/update-graded endpoint to overwrite the Square item's
title/description.

Skips items whose current Square title already matches the desired title.

Run with --dry-run to preview without changes.
"""
from __future__ import annotations

import argparse
import csv
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
CARD_LADDER_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder.csv")
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT_URL = f"{WORKER_BASE}/admin/inspect?types=ITEM"
UPDATE_URL = f"{WORKER_BASE}/admin/update-graded"


def get_token() -> str | None:
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


def split_grader(condition: str) -> tuple[str, str]:
    """'PSA 9' -> ('PSA', '9'); 'CGC 10 Pristine' -> ('CGC', '10 Pristine')."""
    s = (condition or "").strip()
    if not s:
        return "", ""
    parts = s.split(None, 1)
    grader = parts[0].upper() if parts else ""
    grade = parts[1] if len(parts) > 1 else ""
    return grader, grade


def clean_set(set_str: str) -> str:
    """Strip leading 'Pokemon ' (redundant in title)."""
    s = (set_str or "").strip()
    return re.sub(r"^Pokemon\s+", "", s, flags=re.I).strip()


def build_title(row: dict) -> str:
    grader, grade = split_grader(row.get("Condition", ""))
    year = (row.get("Year") or "").strip()
    set_name = clean_set(row.get("Set", ""))
    name = (row.get("Player") or "").strip()
    number = (row.get("Number") or "").strip()

    parts = []
    if grader and grade:
        parts.append(f"{grader} {grade}")
    elif grader:
        parts.append(grader)
    if year:
        parts.append(year)
    if set_name:
        parts.append(set_name)
    if name:
        parts.append(name)
    if number:
        parts.append(f"#{number}")
    return " ".join(parts).strip()


def cert_from_description(item: dict) -> str | None:
    desc = (item.get("item_data") or {}).get("description", "") or ""
    m = re.search(r"Cert #:\s*(\d+)", desc)
    return m.group(1) if m else None


def is_graded_item(item: dict) -> bool:
    data = item.get("item_data") or {}
    name = (data.get("name") or "").lower()
    desc = (data.get("description") or "").lower()
    if "cert #" in desc:
        return True
    return any(k in name for k in (" psa ", " cgc ", " bgs ", " sgc ")) \
        or name.startswith(("psa ", "cgc ", "bgs ", "sgc "))


def get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "X-Sake-Admin-Token": token,
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def post_update(cert: str, row: dict, token: str) -> tuple[bool, dict | str]:
    grader, grade = split_grader(row.get("Condition", ""))
    payload = {
        "cert": cert,
        "card": {
            "grader": grader,
            "grade": grade,
            "year": (row.get("Year") or "").strip(),
            "set_name": clean_set(row.get("Set", "")),
            "name": (row.get("Player") or "").strip(),
            "card_number": (row.get("Number") or "").strip(),
        },
    }
    req = urllib.request.Request(
        UPDATE_URL, method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Sake-Admin-Token": token,
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return True, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return False, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return False, str(e)


def cert_key(s: str) -> str:
    return (s or "").strip().lstrip("0")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                     help="Push update for every cert, even if the title already "
                          "matches. Use after worker description changes so the "
                          "new description format propagates to existing listings.")
    args = ap.parse_args()

    token = get_token()
    if not token:
        print("[names] SK_ADMIN_TOKEN missing")
        return 1

    if not CARD_LADDER_CSV.exists():
        print(f"[names] CL CSV not found: {CARD_LADDER_CSV}")
        return 1

    cl_rows = list(csv.DictReader(CARD_LADDER_CSV.open("r", encoding="utf-8-sig", newline="")))
    cl_by_cert: dict[str, dict] = {}
    for r in cl_rows:
        ck = cert_key(r.get("Slab Serial #", ""))
        if ck:
            cl_by_cert[ck] = r
    print(f"[names] CL CSV: {len(cl_rows)} rows -> {len(cl_by_cert)} unique certs")

    print(f"[names] inspecting Square catalog...")
    inv = get_json(INSPECT_URL, token)
    items = inv.get("objects", [])
    graded = [i for i in items if is_graded_item(i)]
    print(f"[names] Square has {len(graded)} graded items")

    diffs = []
    no_match = []
    for it in graded:
        cert_str = cert_from_description(it) or ""
        cert_k = cert_key(cert_str)
        cl_row = cl_by_cert.get(cert_k)
        cur_name = (it.get("item_data") or {}).get("name", "")
        if not cl_row:
            no_match.append((cert_str, cur_name))
            continue
        desired = build_title(cl_row)
        if cur_name.strip() == desired.strip() and not args.force:
            continue  # already in sync — but --force pushes anyway
        diffs.append({
            "cert": cert_str,
            "cur": cur_name,
            "new": desired,
            "row": cl_row,
        })

    print(f"[names] {len(diffs)} items will be re-titled")
    print(f"[names] {len(no_match)} Square items not in CL (skipped)")

    safe = lambda s: s.encode("ascii", "replace").decode("ascii")
    print("\n=== TITLE DIFFS ===")
    for d in diffs:
        print(f"  cert {d['cert']:>12}")
        print(f"    OLD: {safe(d['cur'])}")
        print(f"    NEW: {safe(d['new'])}")

    if args.dry_run:
        print("\n[names] DRY RUN — no changes made")
        return 0

    if not diffs:
        print("[names] nothing to update")
        return 0

    print(f"\n[names] === Posting updates ===")
    ok, fail = 0, 0
    for d in diffs:
        success, resp = post_update(d["cert"], d["row"], token)
        if success and isinstance(resp, dict) and resp.get("ok"):
            ok += 1
            print(f"  OK   cert {d['cert']}  -> {safe(d['new'])}")
        else:
            fail += 1
            err = resp if isinstance(resp, str) else resp.get("error", "?")
            print(f"  ERR  cert {d['cert']}  {err}")
        time.sleep(0.5)

    print(f"\n[names] done — {ok}/{len(diffs)} updated, {fail} failed")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
