"""
Option C executor: surgical update + selective delete on the Square graded
catalog using Card Ladder pricing.

Steps:
  1. Read pricing.csv. Identify rows whose your_price was just updated by
     _match_card_ladder_to_pricing.py (have a numeric your_price WITHOUT
     the [uploaded] prefix). These are the 22 cards we matched.
  2. For each, POST /admin/update-graded-price with {cert, price_cents}.
     Marks pricing.csv your_price with [uploaded]<price> on success.
  3. Inspect Square. For every graded item whose cert is NOT in the matched
     set, DELETE it. (These are sold-inventory stragglers no longer in
     Card Ladder.) Merch is never touched.

Run with --dry-run to preview without making any changes to Square.

Env: SK_ADMIN_TOKEN (User-scope on Windows).
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
PRICING_CSV = HERE / "pricing.csv"
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"

INSPECT_URL          = f"{WORKER_BASE}/admin/inspect?types=ITEM"
UPDATE_PRICE_URL     = f"{WORKER_BASE}/admin/update-graded-price"
DELETE_URL           = f"{WORKER_BASE}/admin/delete-item"


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


def post_json(url: str, body: dict, token: str) -> tuple[bool, dict | str]:
    req = urllib.request.Request(
        url, method="POST",
        data=json.dumps(body).encode("utf-8"),
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


def get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0", "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def parse_price_to_cents(raw: str) -> int | None:
    if not raw: return None
    s = raw.strip()
    if s.startswith("[uploaded]"): return None  # already pushed
    s = s.lstrip("$").replace(",", "").strip()
    if not s: return None
    try: return int(round(float(s) * 100))
    except ValueError: return None


def is_graded_item(item: dict) -> bool:
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


def mark_uploaded(rows: list[dict], cert: str) -> None:
    for r in rows:
        if (r.get("cert") or "") == cert:
            cur = (r.get("your_price") or "").strip()
            if not cur.startswith("[uploaded]"):
                r["your_price"] = f"[uploaded]{cur}"
            return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = get_token()
    if not token: print("[c] SK_ADMIN_TOKEN not set"); return 1

    if not PRICING_CSV.exists(): print(f"[c] {PRICING_CSV} not found"); return 1
    rows = list(csv.DictReader(PRICING_CSV.open("r", encoding="utf-8")))
    fields = list(rows[0].keys()) if rows else []

    # Build matched set: rows with a numeric your_price (no [uploaded] prefix)
    to_update = []
    for r in rows:
        cents = parse_price_to_cents(r.get("your_price", ""))
        cert  = (r.get("cert") or "").strip()
        if cents is not None and cert:
            to_update.append((cert, cents, r.get("name", ""), r.get("set", ""), r.get("grade", "")))
    matched_certs = {c for c, _, _, _, _ in to_update}
    print(f"[c] {len(to_update)} pricing.csv rows ready to update on Square (matched to Card Ladder)")

    # Inspect Square
    print(f"[c] inspecting Square catalog...")
    inv = get_json(INSPECT_URL, token)
    items = inv.get("objects", [])
    graded = [i for i in items if is_graded_item(i)]
    other  = [i for i in items if not is_graded_item(i)]
    print(f"[c] Square has {len(items)} items: {len(graded)} graded, {len(other)} merch/other (untouched)")

    # Bucket graded into KEEP-AND-UPDATE vs DELETE
    keep = []  # (cert, item_id, name)
    delete = []  # (cert_or_none, item_id, name)
    for it in graded:
        cert = cert_from_description(it)
        name = (it.get("item_data") or {}).get("name", "")
        if cert and cert in matched_certs:
            keep.append((cert, it.get("id"), name))
        else:
            delete.append((cert, it.get("id"), name))
    print(f"[c]   keep + update price: {len(keep)}")
    print(f"[c]   delete (sold / not in CL match): {len(delete)}")

    if args.dry_run:
        print()
        print("=== KEEP & UPDATE PRICE ===")
        for cert, _id, name in keep[:20]:
            row = next((r for r in rows if (r.get("cert") or "") == cert), {})
            new_p = (row.get("your_price") or "").strip()
            print(f"  cert {cert}  ${new_p:<6}  {name[:80]}")
        print()
        print("=== DELETE ===")
        for cert, _id, name in delete[:20]:
            print(f"  cert {cert or '?'}  {name[:80]}")
        if len(delete) > 20: print(f"  ... and {len(delete)-20} more")
        print("\n[c] DRY RUN — no changes made")
        return 0

    # ===== EXECUTE =====
    print()
    print("[c] === Updating prices on matched cards ===")
    ok_updates, fail_updates = 0, 0
    for cert, cents, name, set_, grade in to_update:
        ok, resp = post_json(UPDATE_PRICE_URL, {"cert": cert, "price_cents": cents}, token)
        if ok and isinstance(resp, dict) and resp.get("ok"):
            ok_updates += 1
            mark_uploaded(rows, cert)
            print(f"[c] OK  cert {cert}  ${cents/100:>6.2f}  {name[:60]}")
        else:
            fail_updates += 1
            print(f"[c] ERR cert {cert}  {resp if isinstance(resp, str) else resp.get('error','?')}")
        time.sleep(0.4)

    # Persist [uploaded] marks
    with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows: w.writerow(r)

    print()
    print("[c] === Deleting unmatched graded items ===")
    ok_deletes, fail_deletes = 0, 0
    for cert, item_id, name in delete:
        ok, resp = post_json(DELETE_URL, {"item_id": item_id}, token)
        if ok:
            ok_deletes += 1
            print(f"[c] DEL {item_id}  {name[:60]}")
        else:
            fail_deletes += 1
            print(f"[c] ERR {item_id}  {resp if isinstance(resp, str) else resp.get('error','?')}")
        time.sleep(0.3)

    print()
    print(f"[c] done — updated {ok_updates}/{len(to_update)} prices, deleted {ok_deletes}/{len(delete)} items")
    if fail_updates or fail_deletes:
        print(f"[c]    failures: {fail_updates} update + {fail_deletes} delete")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
