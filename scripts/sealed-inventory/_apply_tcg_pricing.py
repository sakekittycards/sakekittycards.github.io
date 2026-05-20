"""Resolve TCGplayer productId + Market price for each Sealed Inventory row
and write back to Airtable. Re-runnable: skips rows that already have a
fresh productId and only updates market price (cheap call) on subsequent runs.

Pipeline (mirrors scripts/sealed/_build_nexus_planning_sheet.py):
  1. tcgcsv.com/tcgplayer/{categoryId}/groups  -> all groups for EN(3) or JP(85)
  2. Fuzzy-match by set name to find the right group
  3. tcgcsv.com/tcgplayer/{categoryId}/{groupId}/products  -> products in group
  4. Match product by product_type token ("booster box", "elite trainer box", etc.)
  5. https://sakekitty-prices.nwilliams23999.workers.dev/tcg/market?productId=
     -> TCGplayer published Market Price (edge-cached 6h)

Requires AIRTABLE_TOKEN env var.
"""
from __future__ import annotations
import json, os, re, sys, time, urllib.error, urllib.request
from pathlib import Path

BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "appG9mKWxmwq9ZbTq")
TABLE_ID = "tblBj9IL9cmrmUCoP"  # Sealed Inventory
TOKEN = os.environ.get("AIRTABLE_TOKEN", "").strip()
AT_API = "https://api.airtable.com/v0"
PRICES = "https://sakekitty-prices.nwilliams23999.workers.dev"
TCGCSV = "https://tcgcsv.com/tcgplayer"
SAKE_UA = "Mozilla/5.0 SakeKittyCards-SealedPricing/1.0 (sakekittycards.com)"

# Map our product_type values -> regex patterns that should match the
# TCGplayer product NAME within a group. Order matters (most specific first).
PRODUCT_NAME_PATTERNS = {
    "BoosterBox":     [r"\bbooster\s*box\b"],
    "ETB":            [r"\belite\s*trainer\s*box\b", r"\beTB\b"],
    "Bundle":         [r"\bbooster\s*bundle\b", r"\bbundle\b"],
    "Blister":        [r"\bblister\b"],
    "Tin":            [r"\bmini\s*tin\b", r"\btin\b"],
    "Pack":           [r"\bpack\b"],
    "Deck":           [r"\bbattle\s*deck\b", r"\bdeck\b"],
    "CollectionBox":  [r"\bcollection\s*box\b", r"\bex\s*box\b", r"\bbox\b"],
    "Promo":          [r"\bpromo\b"],
}

# Hard-coded hints. Used when the auto fuzzy match needs help or the set
# name in CL doesn't match TCGplayer's exact group name. Maps SKU ->
# (categoryId, group_name_match_lower).
SKU_HINTS = {
    "SEAL-ASCH-ETB":      (3,  "ascended heroes"),
    "SEAL-DR-ETB":        (3,  "destined rivals"),
    "SEAL-DR-BB":         (3,  "destined rivals"),
    "SEAL-PRE-ETB":       (3,  "prismatic evolutions"),
    "SEAL-FS-BLISTER":    (3,  "fusion strike"),
    "SEAL-151-BUND":      (3,  "151"),  # picks "Scarlet & Violet 151"
    "SEAL-151-MTIN":      (3,  "151"),
    "SEAL-FP-PACK":       (3,  "first partner pack"),
    "SEAL-M2INF-BB":      (85, "inferno"),         # M2 / Mega Evolution Inferno X
    "SEAL-NINJA-BB":      (85, "ninja"),
}

# Explicit (and AUTHORITATIVE) productId overrides for SKUs where the group
# heuristic doesn't find the right product. Format: SKU -> productId.
# These win over any cached `tcgplayer_product_id` already on the Airtable
# row, so re-running fixes wrong picks from earlier resolver runs.
SKU_PID_OVERRIDES = {
    # Lives in Ascended Heroes group, not Mega Evolution — heuristic mismatched.
    "SEAL-MFERA-BOX":  672735,  # Ascended Heroes Mega Feraligatr ex Box (EN)
    # One Piece TCG, NOT Pokemon. Category 68. (per user 2026-05-20)
    "SEAL-KAMI-BB":    682057,  # Adventure on Kami's Island Booster Box (One Piece OP-15)
    # SEAL-MDIANCIE-DECK: Mega Battle Deck not yet listed on TCGplayer.
    # Leave blank — set manual_price_override on the Airtable row instead.
}

# Market-price floor rules: enforce `market = max(own_market, floor_pid_market × multiplier)`.
# Use when a multipack product can be cheaper than its parts (e.g. mini tins
# that hold N packs — never list below 2× pack market). The blended value
# is what gets written to `tcg_market_price` so the existing tier markup
# formulas still apply on top.
SKU_MARKET_FLOOR = {
    # 151 Mini Tin = 2 booster packs. Never list below 2× pack market.
    # User rule 2026-05-20.
    "SEAL-151-MTIN": (504467, 2.0, "151 Booster Pack"),
    # 151 Booster Bundle = 6 booster packs (factory pack count).
    # Belt-and-suspenders floor — bundle market usually higher anyway, but
    # cap it from undershooting.
    "SEAL-151-BUND": (504467, 6.0, "151 Booster Pack"),
}


def http_json(url, headers=None, timeout=30):
    hdrs = {"User-Agent": SAKE_UA}
    if headers: hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace")
        print(f"    HTTP {e.code} {url}: {body}")
        return None
    except Exception as e:
        print(f"    ERR {url}: {e}")
        return None


# ---------- TCGplayer group / product / market resolver ----------

_groups_cache: dict[int, list[dict]] = {}
_products_cache: dict[tuple[int, int], list[dict]] = {}


def get_groups(category_id):
    if category_id in _groups_cache:
        return _groups_cache[category_id]
    data = http_json(f"{TCGCSV}/{category_id}/groups")
    groups = (data or {}).get("results", []) if data else []
    _groups_cache[category_id] = groups
    print(f"  [tcgcsv] cat {category_id}: {len(groups)} groups")
    return groups


def get_products(category_id, group_id):
    key = (category_id, group_id)
    if key in _products_cache:
        return _products_cache[key]
    data = http_json(f"{TCGCSV}/{category_id}/{group_id}/products")
    products = (data or {}).get("results", []) if data else []
    _products_cache[key] = products
    return products


def find_group(category_id, name_hint_lower):
    groups = get_groups(category_id)
    matches = []
    for g in groups:
        name = (g.get("name") or "").lower()
        if name_hint_lower in name:
            matches.append(g)
    if not matches:
        return None
    # Prefer the shortest name (most specific exact set, not a special "promo" group)
    matches.sort(key=lambda g: len(g.get("name", "")))
    return matches[0]


def find_product(products, product_type):
    patterns = PRODUCT_NAME_PATTERNS.get(product_type, [])
    if not patterns:
        return None
    for pat in patterns:
        rx = re.compile(pat, re.I)
        candidates = [p for p in products if rx.search(p.get("name", ""))]
        # Drop any "case", "case of", "display" matches (not single units)
        candidates = [p for p in candidates
                      if "case" not in p.get("name", "").lower()
                      and "display" not in p.get("name", "").lower()]
        if not candidates: continue
        # Prefer products without "(Japanese)" / "(EN)" qualifiers that would
        # indicate a translated cross-listing; pick the shortest name.
        candidates.sort(key=lambda p: len(p.get("name", "")))
        return candidates[0]
    return None


def fetch_market(product_id):
    data = http_json(f"{PRICES}/tcg/market?productId={product_id}")
    if not data: return None
    m = data.get("market")
    if m is not None:
        try: return float(m)
        except (TypeError, ValueError): pass
    for p in data.get("printings", []) or []:
        try:
            mv = float(p.get("market") or 0)
            if mv > 0: return mv
        except (TypeError, ValueError): pass
    return None


def fetch_lastsold(product_id):
    """TCGplayer recent sold trimmed avg via mpapi /latestsales.
    Worker returns {ok, productId, sales, avgPrice, samples}."""
    data = http_json(f"{PRICES}/tcg/lastsold?productId={product_id}")
    if not data: return None
    avg = data.get("avgPrice")
    sales = data.get("sales") or 0
    # Require >=2 sales for the avg to be meaningful (single sale is noise)
    if avg is None or sales < 2: return None
    try: return float(avg)
    except (TypeError, ValueError): return None


# ---------- Airtable ----------

def at_get_table_fields():
    res = http_json(f"{AT_API}/meta/bases/{BASE_ID}/tables",
                    headers={"Authorization": f"Bearer {TOKEN}"})
    if not res: return None, {}
    for t in res.get("tables", []):
        if t["id"] == TABLE_ID:
            return t, {f["name"]: f for f in t["fields"]}
    return None, {}


def at_add_field(field_spec):
    url = f"{AT_API}/meta/bases/{BASE_ID}/tables/{TABLE_ID}/fields"
    data = json.dumps(field_spec).encode()
    req = urllib.request.Request(url, method="POST", data=data, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"  + added field {field_spec['name']!r}")
            return True
    except urllib.error.HTTPError as e:
        print(f"  ! add field {field_spec['name']!r} failed: {e.code} {e.read()[:200].decode()}")
        return False


def at_get_records():
    out = []
    offset = None
    while True:
        url = f"{AT_API}/{BASE_ID}/{TABLE_ID}?pageSize=100"
        if offset: url += f"&offset={offset}"
        res = http_json(url, headers={"Authorization": f"Bearer {TOKEN}"})
        if not res: break
        out.extend(res.get("records", []))
        offset = res.get("offset")
        if not offset: break
    return out


def at_patch_records(updates):
    """updates = [{id, fields}, ...]. Batches of 10."""
    ok = fail = 0
    for i in range(0, len(updates), 10):
        batch = updates[i:i+10]
        body = json.dumps({"records": batch, "typecast": True}).encode()
        url = f"{AT_API}/{BASE_ID}/{TABLE_ID}"
        req = urllib.request.Request(url, method="PATCH", data=body, headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                ok += len(batch)
        except urllib.error.HTTPError as e:
            fail += len(batch)
            print(f"  PATCH batch {i//10+1} failed: {e.code} {e.read()[:200].decode()}")
        time.sleep(0.25)
    return ok, fail


# ---------- Main ----------

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not TOKEN:
        sys.exit("ERROR: AIRTABLE_TOKEN not set")

    # 1. Ensure tcgplayer_product_id field exists
    table, fields = at_get_table_fields()
    if not table:
        sys.exit(f"ERROR: table {TABLE_ID} not found in base {BASE_ID}")
    if "tcgplayer_product_id" not in fields:
        print("Adding tcgplayer_product_id field ...")
        at_add_field({
            "name": "tcgplayer_product_id",
            "type": "number",
            "options": {"precision": 0},
        })

    # 2. Load records
    print("Fetching Sealed Inventory rows ...")
    records = at_get_records()
    print(f"  {len(records)} rows")

    # 3. For each, resolve pid + market, prepare update
    updates = []
    for rec in records:
        rid = rec["id"]
        f = rec["fields"]
        sku = f.get("sku", "")
        ptype = f.get("product_type", "")
        existing_pid = f.get("tcgplayer_product_id")
        existing_price = f.get("tcg_market_price")

        print(f"\n[{sku}] type={ptype}")

        # Resolve productId. Priority: explicit override > cached on row > hint+heuristic.
        override_pid = SKU_PID_OVERRIDES.get(sku)
        if override_pid:
            pid = int(override_pid)
            if existing_pid and int(existing_pid) != pid:
                print(f"  OVERRIDE pid={pid} (was cached as {existing_pid} — wrong)")
            else:
                print(f"  pid={pid} (override)")
        elif existing_pid:
            pid = int(existing_pid)
            print(f"  pid={pid} (cached on row)")
        else:
            hint = SKU_HINTS.get(sku)
            if not hint:
                print(f"  no hint, skipping")
                continue
            cat_id, name_hint = hint
            group = find_group(cat_id, name_hint)
            if not group:
                print(f"  no group match for {name_hint!r} in cat {cat_id}")
                continue
            print(f"  group: {group['name']} (id={group['groupId']})")
            products = get_products(cat_id, group["groupId"])
            product = find_product(products, ptype)
            if not product:
                print(f"  no product match for type={ptype} in {group['name']}")
                continue
            pid = product["productId"]
            print(f"  product: {product['name']!r} -> pid={pid}")

        # Fetch market + last-sold
        market = fetch_market(pid)
        if market is None:
            print(f"  no market data for pid {pid}")
            if not existing_pid:
                updates.append({"id": rid, "fields": {"tcgplayer_product_id": pid}})
            continue
        print(f"  TCG market = ${market:.2f}")

        lastsold = fetch_lastsold(pid)
        if lastsold is not None:
            print(f"  TCG last-sold avg = ${lastsold:.2f}")
        else:
            print(f"  TCG last-sold: no recent sales (>=2 needed)")
        time.sleep(0.2)

        # Apply market-floor rule (e.g. tin must be >= 2x pack)
        floor = SKU_MARKET_FLOOR.get(sku)
        if floor:
            floor_pid, multiplier, label = floor
            floor_market = fetch_market(floor_pid)
            if floor_market is not None:
                floor_value = floor_market * multiplier
                if floor_value > market:
                    print(f"  FLOOR APPLIED: {multiplier}x {label} = ${floor_value:.2f} > tin ${market:.2f}")
                    market = floor_value
                else:
                    print(f"  floor ok ({multiplier}x {label} = ${floor_value:.2f} <= tin ${market:.2f})")
            time.sleep(0.2)

        upd = {"tcg_market_price": market}
        if lastsold is not None:
            upd["tcg_last_sold"] = lastsold
        # Write the pid if it's new OR if an override is replacing a stale cache.
        if (not existing_pid) or (override_pid and int(existing_pid) != pid):
            upd["tcgplayer_product_id"] = pid
        updates.append({"id": rid, "fields": upd})
        time.sleep(0.3)

    # 4. Push updates
    if not updates:
        print("\nNothing to update.")
        return 0
    print(f"\nPatching {len(updates)} rows in Airtable ...")
    ok, fail = at_patch_records(updates)
    print(f"  {ok} updated, {fail} failed")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
