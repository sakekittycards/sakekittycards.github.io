"""Adds the image-fix columns to the Sealed Inventory Airtable table and
populates current_image_url from live Square data.

Adds two URL fields:
  - current_image_url  (snapshot of what Square shows now — read-only reference)
  - new_image_url      (you fill this in to queue an image swap)

Then for each existing Airtable row, looks up the matching Square item by
name and fills in current_image_url. new_image_url is left blank so you
can decide which rows to update.

Once you've filled in new_image_url for the rows you want to swap, run
the apply-script (apply_image_fix_from_airtable.py — will land next).

Requires env vars:
  AIRTABLE_TOKEN  — PAT with schema.bases:write + data.records:write on the base

Re-runs are safe: skips fields that already exist, only updates
current_image_url where it differs.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

TABLE_NAME = "Sealed Inventory"
BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "appG9mKWxmwq9ZbTq")
TOKEN = os.environ.get("AIRTABLE_TOKEN", "").strip()
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"

API = "https://api.airtable.com/v0"

NEW_FIELDS = [
    {"name": "current_image_url", "type": "url",
     "description": "Snapshot of the Square product image. Reference column — don't edit. "
                    "Used to compare against new_image_url when staging a swap."},
    {"name": "new_image_url", "type": "url",
     "description": "Paste a replacement image URL here to queue a swap. "
                    "Leave blank to skip. Apply-script reads any row with a value set."},
]


def api(method, path, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, data=data, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", "replace")
        print(f"  HTTP {e.code} {method} {path}: {body_txt[:400]}")
        return {"_error": True, "_status": e.code, "_body": body_txt}


def get_table_id(name):
    res = api("GET", f"/meta/bases/{BASE_ID}/tables")
    if res.get("_error"):
        sys.exit("FATAL: couldn't list tables")
    for t in res.get("tables", []):
        if t["name"] == name:
            return t["id"], {f["name"]: f for f in t.get("fields", [])}
    return None, None


def add_field(table_id, field_spec):
    res = api("POST", f"/meta/bases/{BASE_ID}/tables/{table_id}/fields", field_spec)
    if res.get("_error"):
        print(f"    ! add field {field_spec['name']!r} failed")
        return False
    print(f"    + added field {field_spec['name']!r} ({field_spec['type']})")
    return True


def fetch_square_items():
    """Live snapshot of all Square items with image URLs."""
    req = urllib.request.Request(f"{WORKER_BASE}/items")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("items", [])


def fetch_airtable_rows(table_id):
    """All sealed-inventory rows. Paginates."""
    out = []
    offset = ""
    while True:
        path = f"/{BASE_ID}/{table_id}?pageSize=100"
        if offset:
            path += f"&offset={offset}"
        res = api("GET", path)
        if res.get("_error"):
            sys.exit("FATAL: couldn't list rows")
        out.extend(res.get("records", []))
        offset = res.get("offset", "")
        if not offset:
            break
    return out


def patch_rows(table_id, updates):
    """Batch-PATCH up to 10 rows at a time."""
    if not updates:
        print("  No rows needed updating.")
        return
    print(f"  Patching {len(updates)} rows ...")
    for i in range(0, len(updates), 10):
        batch = updates[i:i + 10]
        res = api("PATCH", f"/{BASE_ID}/{table_id}",
                  {"records": batch, "typecast": True})
        if res.get("_error"):
            print(f"    batch {i//10+1} failed")
        else:
            print(f"    batch {i//10+1}: +{len(res.get('records', []))} rows")
        time.sleep(0.25)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not TOKEN:
        sys.exit("ERROR: AIRTABLE_TOKEN env var not set")
    print(f"Target base: {BASE_ID}")
    print(f"Target table: {TABLE_NAME!r}")

    table_id, existing_fields = get_table_id(TABLE_NAME)
    if table_id is None:
        sys.exit(f"ERROR: table {TABLE_NAME!r} doesn't exist — run _setup_airtable_table.py first")
    print(f"Table id: {table_id}")

    # Step 1 — add missing fields
    print("\nEnsuring image-fix fields exist ...")
    for f in NEW_FIELDS:
        if f["name"] in existing_fields:
            print(f"    = field {f['name']!r} already present")
        else:
            add_field(table_id, f)

    # Step 2 — pull live Square items so we can map by name
    print("\nFetching live Square sealed items ...")
    sq_items = fetch_square_items()
    sq_by_name = {it.get("name", "").strip().lower(): it for it in sq_items}
    print(f"  {len(sq_items)} Square items total")

    # Step 3 — pull current Airtable rows
    print("\nFetching Airtable rows ...")
    at_rows = fetch_airtable_rows(table_id)
    print(f"  {len(at_rows)} rows in Sealed Inventory")

    # Step 4 — build updates: where current_image_url is missing or stale
    updates = []
    matched = 0
    unmatched = []
    for row in at_rows:
        f = row.get("fields", {})
        name = (f.get("product_name") or "").strip().lower()
        if not name:
            continue
        sq = sq_by_name.get(name)
        if not sq:
            unmatched.append(f.get("product_name"))
            continue
        matched += 1
        current = f.get("current_image_url") or ""
        live = sq.get("imageUrl") or ""
        if current != live and live:
            updates.append({
                "id": row["id"],
                "fields": {"current_image_url": live},
            })

    print(f"\nMatched {matched} of {len(at_rows)} Airtable rows to Square items by name.")
    if unmatched:
        print("Unmatched (no Square item with this name):")
        for n in unmatched:
            print(f"    - {n}")

    patch_rows(table_id, updates)

    print()
    print("DONE. Open the Sealed Inventory table in Airtable —")
    print("you'll see current_image_url populated and new_image_url ready for input.")


if __name__ == "__main__":
    main()
