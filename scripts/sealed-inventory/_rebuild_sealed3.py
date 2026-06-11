"""Phase 3 — finish the sealed rebuild. website_price is a formula that honors
manual_price_override, so set THAT for exact prices. Clear square ids on the 9
(items were deleted) so sync recreates fresh, then sync + attach photos."""
import os, subprocess, json, urllib.request, urllib.error

BASE = 'appG9mKWxmwq9ZbTq'; TBL = 'tblBj9IL9cmrmUCoP'
WORKER = 'https://sakekitty-square.nwilliams23999.workers.dev'
def ue(n):
    return subprocess.run(['powershell','-NoProfile','-Command',
        f"[Environment]::GetEnvironmentVariable('{n}','User')"], capture_output=True, text=True, timeout=10).stdout.strip()
AIR = os.environ.get('AIRTABLE_TOKEN') or ue('AIRTABLE_TOKEN')
ADMIN = os.environ.get('SK_ADMIN_TOKEN') or ue('SK_ADMIN_TOKEN')

def air(method, path='', body=None):
    req = urllib.request.Request(f'https://api.airtable.com/v0/{BASE}/{TBL}' + path,
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={'Authorization': 'Bearer ' + AIR, 'Content-Type': 'application/json'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read()), None
    except urllib.error.HTTPError as e:
        return None, f'{e.code} {e.read().decode("utf-8","replace")[:200]}'

def worker(path, body=None):
    req = urllib.request.Request(WORKER + path, data=json.dumps(body or {}).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'X-Sake-Admin-Token': ADMIN, 'User-Agent': 'Mozilla/5.0'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=120).read())
    except urllib.error.HTTPError as e:
        return {'http_error': e.code, 'body': e.read().decode('utf-8', 'replace')[:400]}

# sku -> (price, alloc).  price -> manual_price_override
UPDATES = {'SEAL-M2INF-BB': (136.27, 15), 'SEAL-PHANT-BB': (457.67, 1),
           'SEAL-DR-ETB': (204.11, 2), 'SEAL-NINJA-BB': (110.59, 14), 'SEAL-DR-BB': (601.00, 2)}
CREATES = [
    {'sku': 'SEAL-MDREAM-BB', 'product_name': 'Mega Dream ex Booster Box', 'set': 'M2a: High Class Pack: MEGA Dream ex', 'language': 'JP', 'product_type': 'BoosterBox', 'website_alloc': 16, 'on_hand': 16, 'manual_price_override': 122.19, 'tcgplayer_product_id': 666254, 'platform_assignment': 'Website', 'published': True},
    {'sku': 'SEAL-TFEST-BB', 'product_name': 'Terastal Fest ex Booster Box', 'set': 'SV8a: Terastal Fest ex', 'language': 'JP', 'product_type': 'BoosterBox', 'website_alloc': 6, 'on_hand': 6, 'manual_price_override': 126.34, 'tcgplayer_product_id': 603428, 'platform_assignment': 'Website', 'published': True},
    {'sku': 'SEAL-PHANT-PC-ETB', 'product_name': 'Phantasmal Flames Pokemon Center Elite Trainer Box (Exclusive)', 'set': 'ME02: Phantasmal Flames', 'language': 'EN', 'product_type': 'ETB', 'website_alloc': 1, 'on_hand': 1, 'manual_price_override': 347.07, 'tcgplayer_product_id': 654135, 'platform_assignment': 'Website', 'published': True},
    {'sku': 'SEAL-151-ETB', 'product_name': '151 Elite Trainer Box', 'set': 'SV: Scarlet & Violet 151', 'language': 'EN', 'product_type': 'ETB', 'website_alloc': 1, 'on_hand': 1, 'manual_price_override': 604.01, 'tcgplayer_product_id': 503313, 'platform_assignment': 'Website', 'published': True},
]

rows, offset = [], None
while True:
    d, _ = air('GET', '?pageSize=100' + (f'&offset={offset}' if offset else ''))
    rows += d['records']; offset = d.get('offset')
    if not offset: break
by_sku = {r['fields'].get('sku'): r for r in rows}

# patch the 5 kept rows (clear square ids so sync recreates)
for sku, (price, alloc) in UPDATES.items():
    r = by_sku.get(sku)
    if not r: print('  MISSING kept row', sku); continue
    f = {'manual_price_override': price, 'website_alloc': alloc, 'published': True,
         'square_item_id': '', 'square_variation_id': ''}
    _, err = air('PATCH', body={'records': [{'id': r['id'], 'fields': f}]})
    print(' update', sku, '->', 'OK' if not err else err)

# create the 4 new
for c in CREATES:
    if c['sku'] in by_sku:
        r = by_sku[c['sku']]
        _, err = air('PATCH', body={'records': [{'id': r['id'], 'fields': {**c, 'square_item_id': '', 'square_variation_id': ''}}]})
        print(' recreate(existing)', c['sku'], '->', 'OK' if not err else err)
    else:
        _, err = air('POST', body={'records': [{'fields': c}]})
        print(' create', c['sku'], '->', 'OK' if not err else err)

print('sync ...'); print('  ', json.dumps(worker('/admin/sync-sealed-inventory'))[:700])
print('images ...'); print('  ', json.dumps(worker('/admin/fix-sealed-images?limit=20'))[:500])
print('done')
