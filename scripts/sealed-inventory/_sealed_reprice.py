"""Hourly sealed reprice — pulls each published sealed item's current tcgsearch
market price (tcgsearch.com's pricing data via its public Supabase API, the same
numbers the site shows) and writes it to Airtable manual_price_override, then
syncs to Square so the website price tracks tcgsearch every hour.

Run by Windows Task Scheduler (SakeKitty-SealedReprice). DRY_RUN=1 to preview.
Env: AIRTABLE_TOKEN, SK_ADMIN_TOKEN (read from User env if not in process env)."""
import os, subprocess, json, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE = 'appG9mKWxmwq9ZbTq'; TBL = 'tblBj9IL9cmrmUCoP'
WORKER = 'https://sakekitty-square.nwilliams23999.workers.dev'
SB = 'https://kwuqqoyuksvlnbgzaaim.supabase.co'
SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt3dXFxb3l1a3N2bG5iZ3phYWltIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Mzk0NzA1NTIsImV4cCI6MjA1NTA0NjU1Mn0.DIwS7KTAkLADALR8LMuzMvMP9Q3ErZgWsc3IWjMcjIs'
HERE = Path(__file__).resolve().parent
LOG = HERE / '_sealed_reprice.log'
DRY = os.environ.get('DRY_RUN') == '1'

def ue(n):
    try:
        return subprocess.run(['powershell', '-NoProfile', '-Command',
            f"[Environment]::GetEnvironmentVariable('{n}','User')"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ''
AIR = os.environ.get('AIRTABLE_TOKEN') or ue('AIRTABLE_TOKEN')
ADMIN = os.environ.get('SK_ADMIN_TOKEN') or ue('SK_ADMIN_TOKEN')

def log(m):
    print(m)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(m + '\n')

def air(method, path='', body=None):
    req = urllib.request.Request(f'https://api.airtable.com/v0/{BASE}/{TBL}' + path,
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={'Authorization': 'Bearer ' + AIR, 'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

def sb_price(pid):
    u = SB + '/rest/v1/cards?tcgplayer_product_id=eq.' + str(pid) + '&select=tcgplayer_market_price&limit=1'
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u,
            headers={'apikey': SB_KEY, 'Authorization': 'Bearer ' + SB_KEY, 'User-Agent': UA}), timeout=25).read())
        return float(d[0]['tcgplayer_market_price']) if d and d[0].get('tcgplayer_market_price') else None
    except Exception:
        return None

def recent_sold(pid):
    """TCGplayer mpapi recent sold avg (last-5 outlier-trimmed). None if unavailable."""
    try:
        req = urllib.request.Request(f'https://mpapi.tcgplayer.com/v2/product/{pid}/latestsales',
            method='POST', data=json.dumps({'listingType': 'ListingWithoutPhotos', 'limit': 25, 'offset': 0}).encode(),
            headers={'User-Agent': UA, 'Origin': 'https://www.tcgplayer.com', 'Referer': 'https://www.tcgplayer.com/',
                     'Accept': 'application/json', 'Content-Type': 'application/json'})
        sales = json.loads(urllib.request.urlopen(req, timeout=20).read()).get('data') or []
    except Exception:
        return None
    p = [float(s['purchasePrice']) for s in sales if s.get('purchasePrice')][:5]  # 5 most recent
    if not p: return None
    p = sorted(p)
    if len(p) >= 5: p = p[1:-1]   # drop high+low outlier
    return round(sum(p) / len(p), 2)

def worker(path):
    req = urllib.request.Request(WORKER + path, data=b'{}', method='POST',
        headers={'Content-Type': 'application/json', 'X-Sake-Admin-Token': ADMIN, 'User-Agent': 'Mozilla/5.0'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=120).read())
    except urllib.error.HTTPError as e:
        return {'http_error': e.code, 'body': e.read().decode('utf-8', 'replace')[:200]}

def main():
    import sys
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass
    log(f"\n===== sealed-reprice {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ} DRY={DRY} =====")
    rows = []
    off = None
    while True:
        d = air('GET', '?pageSize=100' + (f'&offset={off}' if off else ''))
        rows += d['records']; off = d.get('offset')
        if not off: break
    pub = [r for r in rows if r['fields'].get('published') and r['fields'].get('tcgplayer_product_id')]
    log(f'[reprice] {len(pub)} published sealed rows')
    changed = 0
    for r in pub:
        f = r['fields']; sku = f.get('sku'); pid = f.get('tcgplayer_product_id')
        cur = f.get('manual_price_override')
        mkt = sb_price(pid)
        if mkt is None:
            log(f'  {sku:18} pid={pid} | no tcgsearch price — hold ${cur}'); continue
        rec = recent_sold(pid)   # mpapi recent-sold avg (higher of market vs sold wins)
        price = round(max(mkt, rec or 0) * 1.03, 2)
        src = f'max(mkt {mkt:.2f}, sold {rec})x1.03' if rec else f'mkt {mkt:.2f}x1.03 (no sold)'
        if cur is not None and abs(float(cur) - price) < 0.01:
            log(f'  {sku:18} ${cur} == ${price} (no change)'); continue
        log(f'  {sku:18} ${cur} -> ${price}  [{src}]')
        if not DRY:
            try:
                air('PATCH', body={'records': [{'id': r['id'], 'fields': {'manual_price_override': price}}]})
                changed += 1
            except Exception as e:
                log(f'    PATCH ERR {e!r}')
        time.sleep(0.2)
    if changed and not DRY:
        log('[reprice] syncing to Square ...')
        log('  ' + json.dumps(worker('/admin/sync-sealed-inventory'))[:300])
    log(f'[reprice] done — {changed} repriced.')

if __name__ == '__main__':
    main()
