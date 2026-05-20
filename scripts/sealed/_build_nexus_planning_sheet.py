"""Transform Nexus wholesale CSV → Sake Kitty sealed-planning sheet.

Source: _nexus_wholesale_<date>.csv (yen prices, awkward layout)
Output: sake_kitty_sealed_plan_<date>.csv (USD, TCGplayer Market matched,
        margin computed, with notes column for ordering decisions)

What it does:
  - Converts ¥ -> USD at Nexus's own rate (1 USD = ¥158.83 on 5/19/2026)
  - Adds landed-cost estimate (DDP duty + shipping factor)
  - Maps Nexus set names to TCGplayer JP group abbreviations
  - Fetches TCGplayer Market for each booster box productId
  - Computes margin % and $ on shrink price (resale grade)
  - Tags each row: anchor / hype / skip / pre-order / underwater
  - Normalizes weird Nexus names (e.g. "Munikis Zero" -> "Nihil Zero",
    "Super Charged Breaker" -> "Super Electric Breaker")

Re-run weekly or when Nexus posts a new sheet.
"""
from __future__ import annotations
import csv
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / '_nexus_wholesale_2026-05-19.csv'
OUT = HERE / 'sake_kitty_sealed_plan_2026-05-19.csv'

YEN_PER_USD = 158.83          # Nexus's stated rate, top of source CSV
DDP_DUTY = 0.05               # ENISHI-style ~5% US duty bundled in
SHIPPING_PER_BOX = 8.0        # rough Japan→FL air freight per box (par for our volumes)

# TCGplayer JP group lookup. Keys are normalized Nexus item names; values
# are (groupId, tcg_set_label) for reporting. None = no TCG match (skip mkt fetch).
NEXUS_TO_TCG = {
    'Abyss Eye M5':              None,  # pre-order, not on TCG yet
    'Ninja Spinner M4':          (24653, 'M4 Ninja Spinner'),
    'Munikis Zero M3':           (24600, 'M3 Nihil Zero'),
    'MEGA Dream ex M2a':         (24499, 'M2a MEGA Dream ex'),
    'Inferno X M2':              None,  # need to find
    'Mega Brave M1L':            (24399, 'm1L Mega Brave'),
    'Mega Symphonia M1S':        (24400, 'm1S Mega Symphonia'),
    'White Flare sv11W (Deluxe Gym Exclusive)': None,
    'Black Bolt sv11B (Deluxe Gym Exclusive)':  None,
    'White Flare sv11W':         None,
    'Black Bolt sv11B':          None,
    'Glory of Team Rocket sv10': None,
    'Hot Air Arena sv9a':        None,
    'Battle Partners sv9':       (24173, 'SV9 Battle Partners'),
    'Terrastal Festival ex sv8a': None,
    'Super Charged Breaker sv8': (23777, 'SV8 Super Electric Breaker'),
    'Paradise dragona sv7a':     (23604, 'SV7a Paradise Dragona'),
    'Stellar Miracle sv7':       (23615, 'SV7 Stellar Miracle'),
    'Night Wanderer sv6a':       None,
    'Mask Of Change sv6':        (23614, 'SV6 Transformation Mask'),
    'Crimson Haze sv5a':         (23602, 'SV5a Crimson Haze'),
    'Wild Force sv5k':           (23612, 'SV5K Wild Force'),
    'Cyber Judge sv5m':          (23613, 'SV5M Cyber Judge'),
    'Shiny Treasure sv4a':       (23601, 'SV4a Shiny Treasure ex'),
    'Ancient Roar sv4k':         None,
    'Flash of the Future sv4m':  None,
    'Raging Surf sv3a':          None,
    'Black Flame Ruler sv3':     None,
    '151 sv2a':                  (23599, 'SV2a 151'),
    'Snow Hazard sv2p':          None,
    'Clay Burst sv2d':           None,
    'Triplet Beat sv1a':         None,
    'Scarlet ex sv1s':           None,
    'Violet ex sv1v':            None,
    'VSTAR Universe s12a':       (23645, 'S12a VSTAR Universe'),
    'Paradigm Trigger s12':      None,
    'Incandescent Arcana':       None,
    'Lost Abyss s11':            None,
    'Starbirth s9':              None,
    'VMAX Climax s8b':           None,
    '25th Anniversary Collection s8a': None,
    'Blue Sky Stream s7r':       None,
    'Eevee Heroes s6a':          (23637, 'S6a Eevee Heroes'),
}

# Normalize Nexus name → canonical key (collapses ship-date variants, drops parens text)
def normalize_item_name(raw: str) -> str:
    n = re.sub(r'\s+', ' ', raw.replace('\n', ' ')).strip()
    # Drop "(Scheduled to ship on May Xst)" suffixes
    n = re.sub(r'\s*\(Scheduled to ship.*?\)', '', n, flags=re.I)
    # Collapse double spaces
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def parse_yen(s: str) -> float | None:
    if not s or s.lower() in ('coming soon', ''):
        return None
    m = re.search(r'¥?([\d,]+)', s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', ''))
    except ValueError:
        return None


def parse_stock(s: str) -> int | None:
    if not s:
        return None
    m = re.search(r'(\d+)', s)
    return int(m.group(1)) if m else None


UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/131.0.0.0 Safari/537.36')
SAKE_UA = 'Mozilla/5.0 SakeKittyCards-JPIndex/1.0 (sakekittycards.com)'


def find_booster_box_pid(group_id: int) -> tuple[int | None, float | None]:
    """Find Booster Box productId in a JP group, then fetch TCG Market price."""
    url = f'https://tcgcsv.com/tcgplayer/85/{group_id}/products'
    req = urllib.request.Request(url, headers={'User-Agent': SAKE_UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f'  [{group_id}] products fetch err: {e}')
        return (None, None)

    pid = None
    for p in data.get('results', []):
        n = p['name'].lower()
        if 'booster box' in n and 'case' not in n and 'deck' not in n:
            pid = p['productId']
            break
    if pid is None:
        return (None, None)

    mkt_url = f'https://sakekitty-prices.nwilliams23999.workers.dev/tcg/market?productId={pid}'
    mreq = urllib.request.Request(mkt_url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(mreq, timeout=20) as r:
            d = json.loads(r.read())
        return (pid, d.get('market'))
    except Exception as e:
        print(f'  [{pid}] market fetch err: {e}')
        return (pid, None)


def category(landed_usd: float | None, tcg_mkt: float | None,
             status: str, stock_shrink: int | None) -> str:
    """Classify the row: anchor / hype / skip / pre-order / underwater / no-data."""
    if status == 'Pre-order':
        return 'pre-order'
    if landed_usd is None:
        return 'no-cost'
    if tcg_mkt is None:
        return 'no-tcg-data'
    margin_pct = (tcg_mkt - landed_usd) / landed_usd
    if margin_pct < 0:
        return 'underwater'
    if margin_pct < 0.10:
        return 'thin'
    if tcg_mkt >= 200 and margin_pct >= 0.20:
        return 'anchor'
    if margin_pct >= 0.25:
        return 'hype'
    return 'mid'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if not SRC.exists():
        print(f'Source missing: {SRC}')
        return 1

    rows_in = []
    with SRC.open('r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        for r in reader:
            if not r or not r[0].strip():
                continue
            # Skip rows that are conversion-rate notes leaking from col H/I/J
            raw_name = normalize_item_name(r[0])
            yen_shrink = parse_yen(r[1]) if len(r) > 1 else None
            yen_no_shrink = parse_yen(r[2]) if len(r) > 2 else None
            if yen_shrink is None and yen_no_shrink is None:
                continue
            status = (r[3] if len(r) > 3 else '').strip() or 'unknown'
            stock_shrink = parse_stock(r[4]) if len(r) > 4 else None
            stock_no_shrink = parse_stock(r[5]) if len(r) > 5 else None

            # Apply known-name normalizations
            display_name = raw_name
            for tag in [' Expansion Pack Deluxe Gym Exclusive']:
                if tag in display_name:
                    display_name = display_name.replace(tag, ' (Deluxe Gym Exclusive)').strip()

            rows_in.append({
                'raw_name': raw_name,
                'display_name': display_name,
                'yen_shrink': yen_shrink,
                'yen_no_shrink': yen_no_shrink,
                'status': status,
                'stock_shrink': stock_shrink,
                'stock_no_shrink': stock_no_shrink,
            })

    print(f'Parsed {len(rows_in)} Nexus rows.\n')

    # Resolve TCG productIds + market for groups we know
    pid_cache: dict[int, tuple[int | None, float | None]] = {}

    out_rows = []
    for r in rows_in:
        key = r['display_name']
        tcg = NEXUS_TO_TCG.get(key)
        tcg_label = ''
        tcg_pid = None
        tcg_mkt = None
        if tcg:
            gid, tcg_label = tcg
            if gid not in pid_cache:
                pid_cache[gid] = find_booster_box_pid(gid)
                time.sleep(0.4)
            tcg_pid, tcg_mkt = pid_cache[gid]

        # USD conversion. Shrink is the resale-grade SKU (collectors want shrink).
        # No-shrink is the discount lane (deal hunters / openers).
        usd_shrink = r['yen_shrink'] / YEN_PER_USD if r['yen_shrink'] else None
        usd_no_shrink = r['yen_no_shrink'] / YEN_PER_USD if r['yen_no_shrink'] else None

        # Landed cost (shrink): wholesale + DDP duty + per-box freight
        landed_shrink = None
        if usd_shrink is not None:
            landed_shrink = usd_shrink * (1 + DDP_DUTY) + SHIPPING_PER_BOX

        margin_pct = None
        margin_usd = None
        if landed_shrink is not None and tcg_mkt is not None and landed_shrink > 0:
            margin_pct = (tcg_mkt - landed_shrink) / landed_shrink
            margin_usd = tcg_mkt - landed_shrink

        cat = category(landed_shrink, tcg_mkt, r['status'], r['stock_shrink'])

        out_rows.append({
            'product': r['display_name'],
            'status': r['status'],
            'nexus_yen_shrink':     int(r['yen_shrink']) if r['yen_shrink'] else '',
            'nexus_yen_no_shrink':  int(r['yen_no_shrink']) if r['yen_no_shrink'] else '',
            'nexus_usd_shrink':     f'{usd_shrink:.2f}' if usd_shrink else '',
            'nexus_usd_no_shrink':  f'{usd_no_shrink:.2f}' if usd_no_shrink else '',
            'landed_usd_shrink':    f'{landed_shrink:.2f}' if landed_shrink else '',
            'tcg_set':              tcg_label,
            'tcg_pid':               tcg_pid or '',
            'tcg_market_usd':       f'{tcg_mkt:.2f}' if tcg_mkt else '',
            'margin_usd':           f'{margin_usd:.2f}' if margin_usd is not None else '',
            'margin_pct':           f'{margin_pct*100:.1f}%' if margin_pct is not None else '',
            'category':             cat,
            'nexus_stock_shrink':   r['stock_shrink'] if r['stock_shrink'] is not None else '',
            'nexus_stock_no_shrink': r['stock_no_shrink'] if r['stock_no_shrink'] is not None else '',
            'sk_par_target':        '',
            'notes':                '',
        })

    # Sort: anchors first, then hype, then mid, etc., then by margin desc
    cat_order = {'anchor':0,'hype':1,'mid':2,'thin':3,'underwater':4,
                 'no-tcg-data':5,'pre-order':6,'no-cost':7}
    def sort_key(r):
        c = cat_order.get(r['category'], 9)
        m = float(r['margin_pct'].rstrip('%')) if r['margin_pct'] else -999
        return (c, -m)
    out_rows.sort(key=sort_key)

    fields = ['product','status','category',
              'nexus_yen_shrink','nexus_yen_no_shrink',
              'nexus_usd_shrink','nexus_usd_no_shrink',
              'landed_usd_shrink','tcg_market_usd','margin_usd','margin_pct',
              'tcg_set','tcg_pid',
              'nexus_stock_shrink','nexus_stock_no_shrink',
              'sk_par_target','notes']
    with OUT.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f'\nWrote {OUT.name} ({len(out_rows)} rows)')

    # Summary
    buckets = {}
    for r in out_rows:
        buckets.setdefault(r['category'], 0)
        buckets[r['category']] += 1
    print('\nCategory breakdown:')
    for cat in cat_order:
        if buckets.get(cat):
            print(f'  {cat:<14} {buckets[cat]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
