"""
Push fresh Card Ladder prices to existing Square graded items.

Reads pricing.csv. For every row with a numeric your_price (no [uploaded]
prefix) AND a cert number, calls /admin/update-graded-price with
{cert, price_cents}. Marks the row [uploaded]<price> on success.

Does NOT delete anything. Does NOT touch images. Only price changes.

Usage:
    python _run_price_updates.py            # actually updates
    python _run_price_updates.py --dry-run  # preview
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
PRICING_CSV = HERE / "pricing.csv"
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"
ENDPOINT = f"{WORKER_BASE}/admin/update-graded-price"


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


def parse_price_to_cents(raw: str) -> int | None:
    if not raw: return None
    s = raw.strip()
    if s.startswith("[uploaded]"): return None
    s = s.lstrip("$").replace(",", "").strip()
    if not s: return None
    try: return int(round(float(s) * 100))
    except ValueError: return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = get_token()
    if not token: print("[upd] SK_ADMIN_TOKEN not set"); return 1
    if not PRICING_CSV.exists(): print(f"[upd] {PRICING_CSV} not found"); return 1

    rows = list(csv.DictReader(PRICING_CSV.open("r", encoding="utf-8")))
    fields = list(rows[0].keys()) if rows else []

    todo = []
    for r in rows:
        cents = parse_price_to_cents(r.get("your_price", ""))
        cert  = (r.get("cert") or "").strip()
        if cents and cert:
            todo.append((cert, cents, r.get("name", ""), r))

    print(f"[upd] {len(todo)} cards to update")
    if args.dry_run:
        for cert, cents, name, _ in todo[:30]:
            print(f"  cert {cert}  ${cents/100:>6.2f}  {name[:70]}")
        if len(todo) > 30: print(f"  ... and {len(todo)-30} more")
        return 0

    ok = 0
    fail = 0
    for i, (cert, cents, name, row) in enumerate(todo, 1):
        body = json.dumps({"cert": cert, "price_cents": cents}).encode("utf-8")
        req = urllib.request.Request(
            ENDPOINT, method="POST", data=body,
            headers={
                "Content-Type": "application/json",
                "X-Sake-Admin-Token": token,
                "User-Agent": "Mozilla/5.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read())
                if resp.get("ok"):
                    ok += 1
                    cur = (row.get("your_price") or "").strip()
                    if not cur.startswith("[uploaded]"):
                        row["your_price"] = f"[uploaded]{cur}"
                    print(f"[upd] {i:>2}/{len(todo)} OK  cert {cert}  ${cents/100:>6.2f}  {name[:55]}")
                else:
                    fail += 1
                    print(f"[upd] {i:>2}/{len(todo)} ERR cert {cert}  {resp.get('error','?')}")
        except urllib.error.HTTPError as e:
            fail += 1
            body_text = e.read().decode("utf-8", errors="replace")[:200]
            print(f"[upd] {i:>2}/{len(todo)} HTTP{e.code} cert {cert}  {body_text}")
        except Exception as e:
            fail += 1
            print(f"[upd] {i:>2}/{len(todo)} EXC cert {cert}  {e}")
        time.sleep(0.4)

    # Save pricing.csv with [uploaded] markers
    with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows: w.writerow(r)

    print()
    print(f"[upd] done — {ok} OK, {fail} failed")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
