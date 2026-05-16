"""One-shot: pull recent eBay sold comps for cert 148877417
(2022 VSTAR Universe FA Pikachu #205 PSA 10) and report a trend.

Policy carve-out from feedback_sync_square_first.md: that rule exists to
avoid Apifying cards we've already SOLD (no longer live certs). This card
is about to be ADDED to inventory — it's a live cert by definition.
Apifying it for an accurate sticker is the right call.
"""
from __future__ import annotations
import statistics
import sys
from datetime import datetime
from _ebay_apify import fetch_apify, _grade_in_title

CARD = '2022 Pikachu VSTAR Universe Full Art #205 PSA 10'

# Multiple keyword variants to maximize recall
KEYWORDS = [
    'pikachu vstar universe full art 205 psa 10',
    'pikachu vstar universe 205 psa 10',
    'pikachu full art vstar universe psa 10 japanese',
]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print(f'Querying eBay (Apify) for: {CARD}')
    print(f'Keywords: {KEYWORDS}\n')

    grouped = fetch_apify(KEYWORDS)

    # Dedupe + collate
    seen_ids = set()
    items = []
    for kw, lst in grouped.items():
        for it in lst:
            iid = it.get('itemId') or (it.get('title','') + str(it.get('endedAt','')))
            if iid in seen_ids:
                continue
            seen_ids.add(iid)
            items.append(it)

    print(f'\nTotal unique items returned: {len(items)}')

    # Filter to PSA 10 in title
    psa10 = [it for it in items if _grade_in_title(it.get('title',''), 'PSA 10')]
    print(f'After PSA 10 title filter: {len(psa10)}')

    # Filter to ones that mention Pikachu and VSTAR Universe or related set tokens
    def looks_relevant(it):
        t = it.get('title','').lower()
        if 'pikachu' not in t:
            return False
        # Must indicate VSTAR Universe / s12a / 205
        if 'vstar universe' in t or 's12a' in t or '#205' in t or ' 205 ' in t or 'v-star universe' in t:
            return True
        return False
    relevant = [it for it in psa10 if looks_relevant(it)]
    print(f'After Pikachu + VSTAR-Universe relevance filter: {len(relevant)}\n')

    # Sort by endedAt desc
    def ended(it):
        return it.get('endedAt','')
    relevant.sort(key=ended, reverse=True)

    if not relevant:
        print('NO RELEVANT COMPS — printing top 15 PSA 10 candidates so you can eyeball.')
        for it in psa10[:15]:
            tp = it.get('totalPrice') or it.get('soldPrice')
            print(f"  ${tp}  {it.get('endedAt','')}  {it.get('title','')[:90]}")
        return 0

    # Display + analyze
    prices_by_date = []
    print(f'{"#":>2}  {"endedAt":<22} {"total":>7}  title')
    print('-' * 130)
    for i, it in enumerate(relevant[:30], 1):
        tp = it.get('totalPrice') or it.get('soldPrice') or 0
        try:
            tp_f = float(tp)
        except (TypeError, ValueError):
            tp_f = 0.0
        ea = it.get('endedAt','')
        title = it.get('title','')[:95]
        print(f'  {i:>2}  {ea:<22} ${tp_f:>6.0f}  {title}')
        if tp_f > 0 and ea:
            prices_by_date.append((ea, tp_f, it.get('itemUrl','')))

    if not prices_by_date:
        print('\nNo prices to analyze.')
        return 0

    print()
    print('=' * 60)
    print('TREND ANALYSIS')
    print('=' * 60)

    prices_only = [p for _, p, _ in prices_by_date]
    print(f'Sample size: {len(prices_only)} sold listings')
    print(f'Min  ${min(prices_only):,.0f}')
    print(f'Max  ${max(prices_only):,.0f}')
    print(f'Mean ${statistics.mean(prices_only):,.0f}')
    print(f'Median ${statistics.median(prices_only):,.0f}')

    # Split recent half vs older half
    if len(prices_only) >= 4:
        mid = len(prices_by_date) // 2
        recent = [p for _, p, _ in prices_by_date[:mid]]
        older = [p for _, p, _ in prices_by_date[mid:]]
        print(f'\nRecent half ({len(recent)} sales): avg ${statistics.mean(recent):,.0f}  median ${statistics.median(recent):,.0f}')
        print(f'Older half  ({len(older)} sales): avg ${statistics.mean(older):,.0f}  median ${statistics.median(older):,.0f}')
        delta = (statistics.mean(recent) - statistics.mean(older)) / statistics.mean(older) * 100
        print(f'Trend: {delta:+.1f}% (recent vs older)')

    # Drop high/low outliers and avg the rest
    if len(prices_only) >= 5:
        trimmed = sorted(prices_only)[1:-1]
        print(f'\nTrimmed mean (drop high+low): ${statistics.mean(trimmed):,.0f}')

    # last 5
    last5 = prices_only[:5]
    if len(last5) >= 3:
        print(f'\nLast 5 sold avg: ${statistics.mean(last5):,.0f}')

    print()
    print('=' * 60)
    print('FORMULA APPLIED')
    print('=' * 60)
    cl = 730.52
    pc = 667.50
    if prices_only:
        ebay_last5 = statistics.mean(prices_only[:5]) if len(prices_only) >= 5 else statistics.mean(prices_only)
        base = max(cl, pc, ebay_last5)
        print(f'  CL CV:           ${cl:.2f}')
        print(f'  PC PSA 10:       ${pc:.2f}')
        print(f'  eBay last-5 avg: ${ebay_last5:.2f}')
        print(f'  -> max anchor:   ${base:.2f}')
        # Tier 2 (200-999) markup: base * 1.10 + 10, snap to nearest $5
        if base < 200:
            marked = base * 1.15 + 3
        elif base < 1000:
            marked = base * 1.10 + 10
        else:
            marked = base * 1.08
        snap = int(round(marked / 5.0) * 5)
        floor = int(round(snap * 0.92 / 5.0) * 5)
        print(f'  -> markup:       ${marked:.2f}')
        print(f'  -> sticker:      ${snap}')
        print(f'  -> floor:        ${floor}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
