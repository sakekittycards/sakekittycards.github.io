# -*- coding: utf-8 -*-
"""Re-measure the PSA 10 : Grade 9 price multiple published on
guide-should-you-grade.html, from the raw PriceCharting Pokemon CSV.

Exists so the number on the page is reproducible rather than remembered.
Run it, read the block it prints, and make the page match. If the page and
this script disagree, the script wins.

  python scripts/verify_psa_multiple.py

PriceCharting's published column mapping for the trading-card category:
    loose-price       Ungraded
    cib-price         Grade 7
    new-price         Grade 8
    graded-price      Grade 9      <- denominator
    box-only-price    Grade 9.5
    manual-only-price PSA 10       <- numerator
    bgs-10-price      BGS 10

NOTE the asymmetry: `graded-price` is a generic Grade 9 (PSA/BGS/CGC blended),
while `manual-only-price` is specifically PSA 10. So this is a
PSA-10-to-Grade-9 ratio, NOT a strict PSA-10-to-PSA-9 ratio. The page must say
Grade 9, not PSA 9.
"""
import csv, json, statistics as st, sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_all_cards_index import PRICECHARTING_CSV

MODERN_FROM = 2020   # inclusive
VINTAGE_TO = 2003    # inclusive (i.e. "pre-2004")


def money(s):
    if not s:
        return None
    s = s.strip().replace('$', '').replace(',', '')
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return float('nan')
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def describe(rows, label):
    """rows = [(g9, psa10, ratio, volume)]"""
    if not rows:
        return None
    r = [x[2] for x in rows]
    vol = sum(x[3] for x in rows)
    # volume-weighted median: expand by sales-volume rank, done as a weighted
    # percentile so a single high-volume card can't dominate the list length.
    sw = sorted(rows, key=lambda x: x[2])
    half, acc, vw = vol / 2.0, 0.0, sw[-1][2]
    for g9, p10, ratio, v in sw:
        acc += v
        if acc >= half:
            vw = ratio
            break
    return dict(label=label, n=len(rows), median=st.median(r),
                q25=pct(r, .25), q75=pct(r, .75), volwtd=vw,
                volume=int(vol))


def main():
    path = Path(PRICECHARTING_CSV)
    if not path.exists():
        sys.exit('No CSV at %s — run a build_*_index.py first to fetch one.' % path)

    total = 0
    genres = Counter()
    pairs = []            # all usable pairs
    no_date = 0
    dated = 0
    skipped_ratio = []    # implausible ratios, for the exclusions note
    era = {'modern': [], 'vintage': [], 'middle': []}

    with open(path, encoding='utf-8', newline='') as fh:
        for row in csv.DictReader(fh):
            total += 1
            genres[row.get('genre') or '(blank)'] += 1
            g9 = money(row.get('graded-price'))
            p10 = money(row.get('manual-only-price'))
            if not g9 or not p10:
                continue
            ratio = p10 / g9
            # A PSA 10 below its own Grade 9, or more than 100x it, is a data
            # artifact (stale one-off sale, mispriced row), not a market signal.
            if ratio < 1.0 or ratio > 100:
                skipped_ratio.append(ratio)
                continue
            vol = money(row.get('sales-volume')) or 0.0
            rec = (g9, p10, ratio, vol)
            pairs.append(rec)

            rd = (row.get('release-date') or '').strip()
            if len(rd) >= 4 and rd[:4].isdigit():
                dated += 1
                y = int(rd[:4])
                if y >= MODERN_FROM:
                    era['modern'].append(rec)
                elif y <= VINTAGE_TO:
                    era['vintage'].append(rec)
                else:
                    era['middle'].append(rec)
            else:
                no_date += 1

    out = []
    out.append(describe(pairs, 'ALL'))
    out.append(describe(era['modern'], 'MODERN (%d+)' % MODERN_FROM))
    out.append(describe(era['vintage'], 'VINTAGE (pre-%d)' % (VINTAGE_TO + 1)))
    out.append(describe(era['middle'], 'MIDDLE (%d-%d)' % (VINTAGE_TO + 1, MODERN_FROM - 1)))
    for lo, hi, lab in ((10, 25, 'G9 $10-25'), (25, 50, 'G9 $25-50'),
                        (50, 100, 'G9 $50-100'), (100, 250, 'G9 $100-250'),
                        (250, 10 ** 12, 'G9 $250+')):
        out.append(describe([x for x in pairs if lo <= x[0] < hi], lab))

    print('SOURCE      %s' % path)
    print('CSV rows    %d' % total)
    print('genres      %s' % dict(genres.most_common(5)))
    print('usable pairs (graded-price AND manual-only-price both > 0, 1<=ratio<=100): %d' % len(pairs))
    print('excluded as implausible ratio: %d' % len(skipped_ratio))
    print('with release-date: %d   without: %d (%.1f%% undated)'
          % (dated, no_date, 100.0 * no_date / max(1, len(pairs))))
    print()
    print('%-22s %8s %9s %9s %9s %10s' % ('SEGMENT', 'n', 'median', 'q25', 'q75', 'vol-wtd'))
    for d in out:
        if not d:
            continue
        print('%-22s %8d %8.2fx %8.2fx %8.2fx %9.2fx'
              % (d['label'], d['n'], d['median'], d['q25'], d['q75'], d['volwtd']))
    print()
    cov = 100.0 * (len(era['modern']) + len(era['vintage'])) / max(1, len(pairs))
    print('era coverage: modern+vintage = %.1f%% of all pairs; the rest is '
          '%d middle-era and %d undated.' % (cov, len(era['middle']), no_date))

    Path(__file__).with_name('_psa_multiple_last_run.json').write_text(
        json.dumps({'source': str(path), 'csv_rows': total, 'pairs': len(pairs),
                    'segments': [d for d in out if d]}, indent=2), encoding='utf-8')
    print('\nwrote scripts/_psa_multiple_last_run.json')


if __name__ == '__main__':
    main()
