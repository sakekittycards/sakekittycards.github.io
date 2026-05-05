"""
Delete Square graded items that are NOT in the current Card Ladder inventory.

Uses the same direct (grade, number, year-fuzzy) match the price-update flow
uses, so the delete list is consistent with what _match_square_to_card_ladder.py
classified as "DELETE" in its report.

Run with --dry-run to preview the targets without making any API calls.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LADDER_CSV = HERE / "_card_ladder_prices.csv"
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"

# Re-import the helper functions from the match script so we stay in sync.
sys.path.insert(0, str(HERE))
from _match_square_to_card_ladder import (
    fetch_square, is_graded, parse_square_item, normalize_grade, normalize_number,
)


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


def delete_item(item_id: str, token: str) -> tuple[bool, str]:
    body = json.dumps({"item_id": item_id}).encode("utf-8")
    req = urllib.request.Request(
        f"{WORKER_BASE}/admin/delete-item",
        method="POST", data=body,
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = get_token()
    if not token: print("[del] SK_ADMIN_TOKEN not set"); return 1
    if not LADDER_CSV.exists(): print(f"[del] {LADDER_CSV} not found — run _apply_card_ladder_prices.py first"); return 1

    # Build CL index keyed by (grade, number) — same as match script.
    ladder = list(csv.DictReader(LADDER_CSV.open("r", encoding="utf-8")))
    cl_idx: dict[tuple, list[dict]] = {}
    for row in ladder:
        key = (normalize_grade(row.get("grade") or ""),
               normalize_number(row.get("number") or ""))
        cl_idx.setdefault(key, []).append(row)

    items = fetch_square(token)
    graded = [it for it in items if is_graded(it)]
    print(f"[del] Square: {len(items)} items, {len(graded)} graded")

    used_cl = set()
    delete_targets = []
    for it in graded:
        sq = parse_square_item(it)
        if not sq["number_norm"]:
            delete_targets.append(sq); continue
        candidates = cl_idx.get((sq["grade_norm"], sq["number_norm"]), [])
        try: sq_year = int(sq["year"]) if sq["year"] else None
        except: sq_year = None
        best = None; best_diff = 99
        for c in candidates:
            cid = id(c)
            if cid in used_cl: continue
            try: cl_year = int((c.get("year") or "").strip())
            except: cl_year = None
            diff = abs(cl_year - sq_year) if (cl_year and sq_year) else 99
            if diff < best_diff:
                best, best_diff = c, diff
        if best is not None and best_diff <= 5:
            used_cl.add(id(best))
        else:
            delete_targets.append(sq)

    print(f"[del] {len(delete_targets)} items not in Card Ladder match — delete targets:")
    for sq in delete_targets:
        print(f"        - {sq['name'][:80]}  (cert {sq['cert'] or '?'})")

    if args.dry_run:
        print("[del] DRY RUN — no changes made")
        return 0

    print()
    ok = fail = 0
    for i, sq in enumerate(delete_targets, 1):
        success, err = delete_item(sq["id"], token)
        if success:
            ok += 1
            print(f"[del] {i:>2}/{len(delete_targets)} OK  {sq['name'][:70]}")
        else:
            fail += 1
            print(f"[del] {i:>2}/{len(delete_targets)} ERR {sq['name'][:70]}  {err}")
        time.sleep(0.3)

    print()
    print(f"[del] done — {ok} deleted, {fail} failed")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
