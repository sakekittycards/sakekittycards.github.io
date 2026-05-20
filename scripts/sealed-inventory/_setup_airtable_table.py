"""One-shot: create the "Sealed Inventory" table in the existing Sake Kitty
Grading Tracker base (appG9mKWxmwq9ZbTq), add all fields with correct types
+ formulas, then import the 13 seed SKUs from _initial_import.csv.

Requires env vars:
  AIRTABLE_TOKEN  - pat... PAT with schema.bases:write + data.records:write
  AIRTABLE_BASE_ID - target base id (defaults to grading base if unset)

Re-running is safe: if the table already exists, the script skips creation
and only adds any missing fields, then upserts records by `sku`.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "_initial_import.csv"

TABLE_NAME = "Sealed Inventory"
BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "appG9mKWxmwq9ZbTq")
TOKEN = os.environ.get("AIRTABLE_TOKEN", "").strip()

API = "https://api.airtable.com/v0"

# ─── Field schema ─────────────────────────────────────────────────────────
# Order matters for formulas (must come AFTER fields they reference).

LANG_CHOICES = ["EN", "JP"]
PRODUCT_TYPE_CHOICES = [
    "BoosterBox", "ETB", "Bundle", "Blister", "Tin", "Pack",
    "Deck", "CollectionBox", "Promo", "Accessory",
]
TIER_CHOICES = ["High", "Medium", "Low", "Collector"]
ASSIGNMENT_CHOICES = ["Website", "TCGplayer", "Both", "ShowOnly"]
LOCATION_CHOICES = ["Storage A", "Storage B", "Booth", "In-Transit"]


def select_field(name, choices):
    return {
        "name": name,
        "type": "singleSelect",
        "options": {"choices": [{"name": c} for c in choices]},
    }


def int_field(name):
    return {"name": name, "type": "number", "options": {"precision": 0}}


def currency_field(name):
    return {
        "name": name,
        "type": "currency",
        "options": {"precision": 2, "symbol": "$"},
    }


def percent_field(name):
    return {"name": name, "type": "percent", "options": {"precision": 0}}


def text_field(name, multi=False):
    return {"name": name, "type": "multilineText" if multi else "singleLineText"}


def checkbox_field(name):
    return {"name": name, "type": "checkbox",
            "options": {"icon": "check", "color": "greenBright"}}


def date_field(name):
    return {"name": name, "type": "date",
            "options": {"dateFormat": {"name": "iso"}}}


def formula_field(name, formula):
    return {"name": name, "type": "formula", "options": {"formula": formula}}


# Non-formula fields create the table; formula fields added after.
BASE_FIELDS = [
    text_field("sku"),  # primary
    text_field("product_name"),
    text_field("set"),
    select_field("language", LANG_CHOICES),
    select_field("product_type", PRODUCT_TYPE_CHOICES),
    int_field("on_hand"),
    int_field("website_alloc"),
    int_field("tcgplayer_alloc"),
    int_field("show_reserve"),
    currency_field("cost_basis"),
    currency_field("tcg_market_price"),
    select_field("liquidity_tier", TIER_CHOICES),
    select_field("platform_assignment", ASSIGNMENT_CHOICES),
    checkbox_field("is_homepage_featured"),
    percent_field("target_roi_pct"),
    currency_field("manual_price_override"),
    select_field("location", LOCATION_CHOICES),
    date_field("received_date"),
    # NOTE: lastModifiedTime fields can't be created via Airtable Metadata API
    # (known limitation). Add `last_updated` manually in the UI if you want it:
    #   Field type: "Last modified time" / set to "Track all editable fields"
    text_field("notes", multi=True),
    checkbox_field("published"),
]

WEBSITE_PRICE_FORMULA = (
    'IF({manual_price_override}, {manual_price_override}, '
    'IF({liquidity_tier} = "High", {tcg_market_price} * 1.10, '
    'IF({liquidity_tier} = "Medium", {tcg_market_price} * 1.15, '
    'IF({liquidity_tier} = "Low", {tcg_market_price} * 1.25, '
    '{tcg_market_price} * 1.30))))'
)

TCGPLAYER_PRICE_FORMULA = (
    'IF({manual_price_override}, {manual_price_override}, '
    'IF({liquidity_tier} = "High", {tcg_market_price} * 1.00, '
    'IF({liquidity_tier} = "Medium", {tcg_market_price} * 1.05, '
    'IF({liquidity_tier} = "Low", {tcg_market_price} * 1.10, '
    'BLANK()))))'
)

ALLOC_DRIFT_FORMULA = (
    'IF({website_alloc} + {tcgplayer_alloc} + {show_reserve} > {on_hand}, '
    '"⚠️ OVER", "OK")'
)

FORMULA_FIELDS = [
    formula_field("website_price", WEBSITE_PRICE_FORMULA),
    formula_field("tcgplayer_price", TCGPLAYER_PRICE_FORMULA),
    formula_field("alloc_drift", ALLOC_DRIFT_FORMULA),
]


# ─── HTTP helpers ─────────────────────────────────────────────────────────
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
        sys.exit(f"FATAL: couldn't list tables: {res.get('_body','')[:200]}")
    for t in res.get("tables", []):
        if t["name"] == name:
            return t["id"], {f["name"]: f for f in t.get("fields", [])}
    return None, None


def create_table_with_base_fields():
    body = {
        "name": TABLE_NAME,
        "description": ("Master ledger for sealed-product inventory. "
                        "Split across website (Square) + TCGplayer with per-platform "
                        "allocation buckets. See scripts/sealed-inventory/README.md."),
        "fields": BASE_FIELDS,
    }
    res = api("POST", f"/meta/bases/{BASE_ID}/tables", body)
    if res.get("_error"):
        sys.exit(f"FATAL: create table failed.")
    print(f"  Created table {TABLE_NAME!r} -> id {res['id']}")
    return res["id"], {f["name"]: f for f in res.get("fields", [])}


def add_field(table_id, field_spec):
    res = api("POST", f"/meta/bases/{BASE_ID}/tables/{table_id}/fields", field_spec)
    if res.get("_error"):
        print(f"    ! add field {field_spec['name']!r} failed")
        return False
    print(f"    + added field {field_spec['name']!r} ({field_spec['type']})")
    return True


# ─── CSV → records ─────────────────────────────────────────────────────────
INT_FIELDS = {"on_hand", "website_alloc", "tcgplayer_alloc", "show_reserve"}
NUM_FIELDS = {"cost_basis", "tcg_market_price", "target_roi_pct",
              "manual_price_override"}
BOOL_FIELDS = {"is_homepage_featured", "published"}


def coerce(field, value):
    if value is None or value == "":
        return None  # skip absent
    if field in BOOL_FIELDS:
        return str(value).lower() in ("true", "1", "yes")
    if field in INT_FIELDS:
        try: return int(value)
        except ValueError: return None
    if field in NUM_FIELDS:
        try:
            v = float(value)
            # percent stored as decimal (0.25 = 25%)
            if field == "target_roi_pct":
                v = v / 100.0
            return v
        except ValueError: return None
    return value  # text, select, date


def load_records():
    rows = []
    with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            fields = {}
            for k, v in r.items():
                cv = coerce(k, v)
                if cv is None: continue
                fields[k] = cv
            rows.append({"fields": fields})
    return rows


def insert_records(table_id, records):
    """Insert in batches of 10. Skips records whose sku already exists."""
    # Check existing
    res = api("GET", f"/{BASE_ID}/{table_id}?fields[]=sku&pageSize=100")
    existing = set()
    if not res.get("_error"):
        for r in res.get("records", []):
            sku = r.get("fields", {}).get("sku")
            if sku: existing.add(sku)
        print(f"  Found {len(existing)} existing rows by sku")

    to_create = [r for r in records if r["fields"].get("sku") not in existing]
    if not to_create:
        print("  Nothing new to insert.")
        return
    print(f"  Inserting {len(to_create)} new records ({len(records)-len(to_create)} already present) ...")
    for i in range(0, len(to_create), 10):
        batch = to_create[i:i+10]
        res = api("POST", f"/{BASE_ID}/{table_id}",
                  {"records": batch, "typecast": True})
        if res.get("_error"):
            print(f"    batch {i//10+1} failed")
        else:
            print(f"    batch {i//10+1}: +{len(res.get('records',[]))} records")
        time.sleep(0.25)


# ─── Main ─────────────────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not TOKEN:
        sys.exit("ERROR: AIRTABLE_TOKEN env var not set")
    print(f"Target base: {BASE_ID}")
    print(f"Target table: {TABLE_NAME!r}")

    table_id, existing_fields = get_table_id(TABLE_NAME)
    if table_id is None:
        print(f"Table not found, creating ...")
        table_id, existing_fields = create_table_with_base_fields()
    else:
        print(f"Table exists -> {table_id}; will only add missing fields.")
        # Add any base fields that don't exist yet
        for f in BASE_FIELDS:
            if f["name"] not in existing_fields:
                add_field(table_id, f)

    # Add formula fields (always idempotent — skip if name exists)
    print("Adding formula fields ...")
    # Refresh field list
    _, existing_fields = get_table_id(TABLE_NAME)
    for f in FORMULA_FIELDS:
        if f["name"] in existing_fields:
            print(f"    = formula {f['name']!r} already present")
            continue
        add_field(table_id, f)

    # Import seed records
    print("Loading seed records from _initial_import.csv ...")
    records = load_records()
    print(f"  Parsed {len(records)} rows")
    insert_records(table_id, records)

    print()
    print(f"DONE. Base {BASE_ID}, table {TABLE_NAME!r} ({table_id})")


if __name__ == "__main__":
    main()
