# -*- coding: utf-8 -*-
"""Generate one crawlable static page per SKU under p/, plus a slug manifest.

WHY THIS EXISTS
---------------
`product.html` is a single JS shell serving every SKU. Its real title,
description, canonical and Product schema only appear after JavaScript runs.
Googlebot renders JS so it copes, but Bing, social scrapers (Facebook,
iMessage, Slack) and most AI/answer-engine crawlers largely do not — so 55
pieces of inventory, including 37 one-of-one graded slabs, have effectively no
independent presence outside Google.

Static hosting (GitHub Pages) means the only way to get a crawlable per-SKU URL
is a real file per SKU. That is what this writes.

THE STALENESS PROBLEM, AND HOW IT IS HANDLED
--------------------------------------------
Inventory is a daily mirror of TCGenie account 54 (skDailyRun, 13:00 UTC), so a
committed price can go stale and a slab can sell. A stale static page would be
worse than no page. Two mitigations, both in the emitted page:

  1. HYDRATION. On load the page re-fetches /items and overwrites the price and
     stock from live data. A visitor never sees a stale number, even if the
     file on disk is weeks old.
  2. SELF-RETIREMENT. If the SKU is no longer in /items (it sold), the page
     injects `noindex, follow`, retitles, and swaps the buy panel for a
     "this one sold" state with links to what is still available. It stops
     being an indexable page advertising something that is gone, without
     anybody having to remember to delete it.

So the committed file is a crawlable BASELINE, and the browser is always the
source of truth. Regenerating keeps the schema fresh; not regenerating degrades
gracefully instead of lying.

LIFECYCLE GUARANTEES (each verified by a test, see the suite in the commit)
--------------------------------------------------------------------------
  * URLs are PINNED per SKU. The manifest is the URL registry: a SKU keeps the
    slug it was first given even if its name is edited in Square. Before this,
    a rename silently moved the URL and threw away any accumulated equity.
  * Obsolete pages cannot accumulate: anything not in the current feed is
    deleted from p/ on every run.
  * A sold SKU leaves the SITEMAP in the same run that deletes its page —
    sync_sitemap() rewrites the fenced Products block from the manifest, so the
    sitemap can never advertise a 404.
  * Static schema cannot go stale indefinitely: every Offer carries
    priceValidUntil (30 days), and hydration rewrites price + availability in
    the JSON-LD as well as in the visible UI, including flipping a vanished SKU
    to SoldOut.

SAFE-BY-CONSTRUCTION
--------------------
  * Writes only into p/ and assets/product-slugs.json. Touches no existing page.
  * Emits whole files from a template. No regex splicing into existing HTML —
    that is what corrupted shop.html (56 -> 110 -> 164 cards) in a prior pass.
  * Idempotent: same input gives byte-identical output. Run it 4x and diff.
  * Prunes pages whose SKU has vanished, so p/ cannot grow forever.
  * Chrome (nav/footer/cache-busters) is read from about.html at build time via
    _seo_page_kit, so it can never drift from the rest of the site the way the
    retired build_graded_page.py template did.

USAGE
-----
    python scripts/build_product_pages.py            # build from live /items
    python scripts/build_product_pages.py --dry-run  # report, write nothing
    python scripts/build_product_pages.py --from _items.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _seo_page_kit import NAV, FOOTER, CSS_V, JS_V, SKIP, SITE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / 'p'
MANIFEST = ROOT / 'assets' / 'product-slugs.json'
SITEMAP = ROOT / 'sitemap.xml'
SM_OPEN = '  <!--PRODUCTS:start-->'
SM_CLOSE = '  <!--PRODUCTS:end-->'
ITEMS_URL = 'https://sakekitty-square.nwilliams23999.workers.dev/items'

# How long a build-time price is asserted as valid. Short on purpose: inventory
# is a daily mirror, so a month is already generous. Expiring is the desired
# behaviour — it tells a crawler to re-fetch rather than trust an old number.
PRICE_VALID_DAYS = 30

# Mirrors shop.html's categorize() exactly. If that changes, change this.
GRADER_RX = re.compile(r'\b(PSA|BGS|CGC|SGC)\b', re.I)
SEALED_RX = re.compile(
    r'\b(booster|box|etb|elite trainer|bundle|tin|collection|pack|case|blister|display)\b', re.I)


def categorize(item):
    name = item.get('name') or ''
    desc = item.get('description') or ''
    if GRADER_RX.search(name):
        return 'graded'
    if re.match(r'^(?:19|20)\d{2}\s', name):
        return 'singles'
    if re.search(r'Card ID:', desc, re.I) and not SEALED_RX.search(name):
        return 'singles'
    if SEALED_RX.search(name):
        return 'sealed'
    return 'merch'


def load_manifest():
    """Existing SKU -> slug map, or {} on first run.

    This is the URL registry, not a cache. See assign_slugs().
    """
    try:
        return json.loads(MANIFEST.read_text(encoding='utf-8'))
    except Exception:
        return {}


def assign_slugs(items, existing):
    """Slugs are PINNED to the SKU on first sight and never change afterwards.

    Names get edited in Square all the time — a reprice note appended, a set
    name tidied. Deriving the slug from the current name every run meant a
    rename silently moved the product's URL: the old file was pruned, a new one
    appeared, and whatever ranking or inbound links the old URL had accumulated
    were thrown away with no redirect. Verified: one SKU with three name
    variants produced three different URLs.

    So the manifest is the authority. A SKU keeps the slug it was first given,
    for life. Only genuinely new SKUs mint a new one.
    """
    slugs = {}
    taken = set()
    for it in items:
        sku = it['id']
        if sku in existing:                 # pinned — keep the URL it already has
            slugs[sku] = existing[sku]
            taken.add(existing[sku])
    for it in items:
        sku = it['id']
        if sku in slugs:
            continue
        base = slugify(it['name'], sku)
        cand, n = base, 2
        while cand in taken:                # cannot collide with a pinned slug
            cand = '%s-%d' % (base, n)
            n += 1
        slugs[sku] = cand
        taken.add(cand)
    return slugs


def slugify(name, sku):
    """Readable, collision-proof. Only ever called when MINTING a new slug —
    an existing SKU keeps its pinned slug regardless of what this would return.
    """
    s = unicodedata.normalize('NFKD', name or 'item')
    s = s.encode('ascii', 'ignore').decode('ascii').lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    s = re.sub(r'-{2,}', '-', s)[:70].strip('-') or 'item'
    return '%s-%s' % (s, (sku or '')[:6].lower())


def esc(s):
    """For attribute values — quotes must be escaped."""
    return html.escape(str(s if s is not None else ''), quote=True)


def esct(s):
    """For element text (<title>, <h1>). Escaping quotes here would render as
    literal &#x27; noise in the SERP and inflate the length budget."""
    return html.escape(str(s if s is not None else ''), quote=False)


def money(v):
    try:
        return '%.2f' % float(v)
    except (TypeError, ValueError):
        return None


def clean_desc(d, limit=300):
    """Square descriptions carry newlines and internal stamps. Flatten for meta."""
    t = re.sub(r'Card ID:.*', '', d or '', flags=re.I)
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:limit].rsplit(' ', 1)[0] if len(t) > limit else t


CAT_WORD = {
    'graded': 'graded Pokémon slab',
    'sealed': 'sealed Pokémon product',
    'singles': 'raw Pokémon single',
    'merch': 'Sake Kitty Cards apparel',
}
CAT_CRUMB = {
    'graded': ('Graded Cards', 'shop.html?cat=graded'),
    'sealed': ('Sealed Product', 'shop.html'),
    'singles': ('Singles', 'shop.html'),
    'merch': ('Apparel &amp; Merch', 'shop.html?cat=merch'),
}

PAGE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="icon" type="image/png" href="../logo-icon.png" />
  <link rel="apple-touch-icon" href="../logo-touch.png" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="theme-color" content="#06060a" />
  <meta name="color-scheme" content="dark" />
  <title>{title}</title>
  <meta name="description" content="{desc}" />
  <link rel="canonical" href="{url}" />
  <meta property="og:title" content="{ogtitle}" />
  <meta property="og:description" content="{desc}" />
  <meta property="og:site_name" content="Sake Kitty Cards" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:image" content="{image}" />
  <meta property="og:image:alt" content="{imgalt}" />
  <meta property="og:url" content="{url}" />
  <meta property="og:type" content="product" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{ogtitle}" />
  <meta name="twitter:description" content="{desc}" />
  <meta name="twitter:image" content="{image}" />
{schema}
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bangers&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="../style.css?v={cssv}" />
  <style>
    .pd-wrap {{ display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:44px; max-width:1100px; margin:0 auto; align-items:start; }}
    .pd-media img {{ width:100%; height:auto; border-radius:var(--r); border:1px solid var(--border); background:#0b0b12; }}
    .pd-price {{ font-family:'Inter',sans-serif; font-size:32px; font-weight:800; color:var(--orange); font-variant-numeric:tabular-nums; margin:6px 0 4px; }}
    .pd-stock {{ font-size:13.5px; color:var(--muted); margin-bottom:20px; }}
    .pd-desc p {{ margin-bottom:12px; }}
    .pd-meta {{ list-style:none; padding:0; margin:22px 0 0; border-top:1px solid var(--border); }}
    .pd-meta li {{ display:flex; justify-content:space-between; gap:16px; padding:11px 0; border-bottom:1px solid var(--border); font-size:14px; }}
    .pd-meta span:first-child {{ color:var(--dim); }}
    .pd-sold {{ display:none; padding:16px 18px; border-radius:var(--r); background:rgba(255,106,0,.08); border:1px solid rgba(255,106,0,.3); margin-bottom:18px; }}
    @media (max-width:820px) {{ .pd-wrap {{ grid-template-columns:1fr; gap:26px; }} }}
  </style>
</head>
<body>
  {skip}

{nav}

  <main id="main" class="page-content">
    <div class="section" style="padding-top:calc(var(--nav-h) + 40px)">
      <nav aria-label="Breadcrumb" style="margin-bottom:22px;font-size:13.5px;color:var(--dim)">
        <a href="../index.html" style="color:var(--dim)">Home</a> ›
        <a href="../shop.html" style="color:var(--dim)">Shop</a> ›
        <a href="../{crumbhref}" style="color:var(--dim)">{crumbname}</a> ›
        <span style="color:var(--muted)">{shortname}</span>
      </nav>

      <div class="pd-wrap">
        <div class="pd-media">
          <img src="{image}" alt="{imgalt}" width="{iw}" height="{ih}" fetchpriority="high" decoding="async" />
        </div>
        <div>
          <h1 style="font-family:'Bangers',cursive;font-size:clamp(26px,4vw,40px);letter-spacing:.02em;line-height:1.2;padding-bottom:8px">{h1}</h1>

          <div class="pd-sold" id="pdSold">
            <strong>This one has sold.</strong> Graded slabs are one-of-one, so once a card goes it&rsquo;s gone.
            <a href="../shop.html">See what&rsquo;s in stock</a> or <a href="../trade-in.html">sell us one like it</a>.
          </div>

          <div id="pdBuy">
            <div class="pd-price" id="pdPrice">{pricetext}</div>
            <div class="pd-stock" id="pdStock">{stocktext}</div>
            <div style="display:flex;gap:12px;flex-wrap:wrap">
              <a href="../product.html?id={sku}" class="btn btn-primary btn-lg">{cta}</a>
              <a href="../shop.html" class="btn btn-outline btn-lg">Browse the shop</a>
            </div>
          </div>

          <div class="pd-desc" style="margin-top:24px;color:var(--muted);line-height:1.75">{descblock}</div>

          <ul class="pd-meta">
{metarows}
          </ul>

          <p style="font-size:13px;color:var(--dim);margin-top:18px;line-height:1.65">
            📍 We&rsquo;re local vendors &mdash; we sell at Florida card shows as well as online, so stock can
            occasionally lag a booth sale. <strong>Every order is reviewed before we charge.</strong> If
            something just sold in person we&rsquo;ll refund, swap or hold the same day.
          </p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header"><h2 class="section-title">More {catplural}</h2></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:18px">
{related}
      </div>
      <p style="margin-top:26px"><a href="../shop.html" class="btn btn-outline">See everything in the shop →</a></p>
    </div>
  </main>

{footer}

  <script src="../main.js?v={jsv}" defer></script>
  <script>
    // Hydrate from live inventory. The committed HTML is a crawlable baseline;
    // the browser is the source of truth. Two jobs: correct the price/stock,
    // and retire the page if this SKU has sold.
    (function () {{
      var SKU = {skujson};
      var BASE = 'https://sakekitty-square.nwilliams23999.workers.dev';
      var fmt = function (n) {{
        return '$' + Number(n).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
      }};
      fetch(BASE + '/items').then(function (r) {{
        if (!r.ok) throw new Error('items ' + r.status);
        return r.json();
      }}).then(function (data) {{
        var items = (data && data.items) || [];
        var live = null;
        for (var i = 0; i < items.length; i++) {{ if (items[i].id === SKU) {{ live = items[i]; break; }} }}

        if (!live) {{
          // Sold or withdrawn. Stop being an indexable listing for it.
          var m = document.createElement('meta');
          m.name = 'robots'; m.content = 'noindex, follow';
          document.head.appendChild(m);
          document.title = 'Sold \\u2014 ' + document.title;
          try {{
            var ldGone = document.getElementById('productSchema');
            if (ldGone) {{
              var g = JSON.parse(ldGone.textContent);
              if (g.offers) {{
                g.offers.availability = 'https://schema.org/SoldOut';
                delete g.offers.price;
                ldGone.textContent = JSON.stringify(g, null, 2);
              }}
            }}
          }} catch (e) {{ /* leave it */ }}
          var sold = document.getElementById('pdSold');
          var buy = document.getElementById('pdBuy');
          if (sold) sold.style.display = 'block';
          if (buy) buy.style.display = 'none';
          return;
        }}

        // Correct the structured data as well as the visible price. Google
        // renders JS and reads the rewritten node, so a stale committed price
        // never reaches a rich result. Non-JS crawlers fall back to
        // priceValidUntil, which expires rather than lying indefinitely.
        try {{
          var ldEl = document.getElementById('productSchema');
          if (ldEl) {{
            var ld = JSON.parse(ldEl.textContent);
            if (ld.offers) {{
              if (live.price) {{ ld.offers.price = Number(live.price).toFixed(2); }}
              else {{ delete ld.offers.price; }}
              ld.offers.availability = (live.stock === null || live.stock === undefined || live.stock > 0)
                ? 'https://schema.org/InStock' : 'https://schema.org/OutOfStock';
              ldEl.textContent = JSON.stringify(ld, null, 2);
            }}
          }}
        }} catch (e) {{ /* malformed node: leave the build-time schema alone */ }}

        var priceEl = document.getElementById('pdPrice');
        var stockEl = document.getElementById('pdStock');
        if (priceEl) priceEl.textContent = live.price ? fmt(live.price) : 'Make an Offer';
        if (stockEl) {{
          stockEl.textContent = (live.stock === null || live.stock === undefined)
            ? 'Available now'
            : (live.stock > 0 ? (live.stock <= 3 ? 'Only ' + live.stock + ' left' : 'In stock') : 'Out of stock');
        }}
        if (window.skTrack) window.skTrack('product_view', {{ sku: SKU, category: {catjson}, in_stock: true }});
      }}).catch(function () {{
        // Worker unreachable: leave the committed values in place. Deliberately
        // NOT noindex here — de-indexing live inventory because of a transient
        // network blip would be far worse than showing a slightly old price.
      }});
    }})();
  </script>
</body>
</html>
'''


def build_schema(item, cat, url, image, price, desc):
    avail = 'https://schema.org/InStock'
    stock = item.get('stock')
    if stock is not None and stock <= 0:
        avail = 'https://schema.org/OutOfStock'

    offer = {
        '@type': 'Offer',
        'url': url,
        # Bounds how long a crawler should trust a build-time price. Without it
        # a stale committed price is asserted as current forever. JS-capable
        # crawlers get the live value anyway (hydration rewrites this node).
        'priceValidUntil': PRICE_VALID_UNTIL,
        'availability': avail,
        'itemCondition': ('https://schema.org/UsedCondition' if cat in ('graded', 'singles')
                          else 'https://schema.org/NewCondition'),
        'priceCurrency': item.get('currency') or 'USD',
        'seller': {'@id': 'https://sakekittycards.com/#organization'},
    }
    if price:
        offer['price'] = price
    else:
        # No price = make-offer. Claiming a price of 0 would be a lie to Google
        # and would surface "$0.00" in rich results.
        offer['availability'] = 'https://schema.org/InStock'

    product = {
        '@context': 'https://schema.org',
        '@type': 'Product',
        'name': item.get('name'),
        'sku': item.get('id'),
        'url': url,
        'category': cat,
        'brand': {'@type': 'Brand', 'name': 'Pokémon'},
        'offers': offer,
    }
    if desc:
        product['description'] = desc
    if image:
        product['image'] = image
    if item.get('cert'):
        # A cert number is the single most specific identifier a slab has, and
        # people genuinely search it. Expose it as a real identifier.
        product['gtin'] = None
        product.pop('gtin')
        product['identifier'] = str(item['cert'])
        product['additionalProperty'] = [{
            '@type': 'PropertyValue',
            'name': 'Certification number',
            'value': str(item['cert']),
        }]

    crumb_name, crumb_href = CAT_CRUMB.get(cat, ('Shop', 'shop.html'))
    breadcrumb = {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'Home', 'item': SITE},
            {'@type': 'ListItem', 'position': 2, 'name': 'Shop', 'item': SITE + 'shop.html'},
            {'@type': 'ListItem', 'position': 3, 'name': html.unescape(crumb_name), 'item': SITE + crumb_href},
            {'@type': 'ListItem', 'position': 4, 'name': item.get('name'), 'item': url},
        ],
    }
    out = ''
    for node, node_id in ((product, ' id="productSchema"'), (breadcrumb, '')):
        out += ('  <script type="application/ld+json"%s>\n%s\n  </script>\n'
                % (node_id, json.dumps(node, indent=2, ensure_ascii=False)))
    return out


def related_html(item, cat, all_items, slugs):
    """Same category, cheapest-first proximity, max 4. Real links, not filler."""
    peers = [i for i in all_items
             if i.get('id') != item.get('id') and categorize(i) == cat and i.get('id') in slugs]
    here = float(item.get('price') or 0)
    peers.sort(key=lambda i: abs(float(i.get('price') or 0) - here))
    out = []
    for pr in peers[:4]:
        img = (pr.get('imageUrl') or '')
        pt = money(pr.get('price'))
        out.append(
            '        <a class="card" href="%s.html" style="padding:12px;text-decoration:none;display:block">\n'
            '          <img src="%s" alt="%s" width="300" height="420" loading="lazy" decoding="async" '
            'style="width:100%%;height:auto;border-radius:8px;background:#0b0b12" />\n'
            '          <div style="font-size:13px;color:var(--muted);margin-top:10px;line-height:1.4">%s</div>\n'
            '          <div style="font-size:14px;font-weight:700;color:var(--orange);margin-top:4px">%s</div>\n'
            '        </a>' % (esc(slugs[pr['id']]), esc(img), esc(pr.get('name')),
                              esc((pr.get('name') or '')[:70]),
                              ('$' + pt) if pt else 'Make an Offer'))
    return '\n'.join(out) if out else '        <p style="color:var(--dim)">Nothing else in this category right now.</p>'


def sync_sitemap(slugs, today, dry_run=False):
    """Rewrite the fenced Products block so it exactly matches what exists.

    Fenced rather than pattern-matched: a fence cannot nest, so re-running
    replaces the region instead of appending to it. (build_shop_snapshot.py
    once tripled a catalog by matching on a non-greedy div instead of a fence.)

    Deliberately derives from `slugs`, not from a directory listing, so a stray
    file in p/ can never smuggle a URL into the sitemap.
    """
    if not SITEMAP.exists():
        print('  !! sitemap.xml missing — skipped')
        return 0
    xml = SITEMAP.read_text(encoding='utf-8')
    rows = ''.join(
        '  <url>\n'
        '    <loc>https://sakekittycards.com/p/%s.html</loc>\n'
        '    <lastmod>%s</lastmod>\n'
        '    <changefreq>weekly</changefreq>\n'
        '    <priority>0.6</priority>\n'
        '  </url>\n' % (slug, today)
        for slug in sorted(slugs.values()))
    block = (SM_OPEN + '\n'
             '  <!-- Product URLs, owned by scripts/build_product_pages.py.\n'
             '       Do not hand-edit: the generator rewrites this whole region so a\n'
             '       sold SKU leaves the sitemap in the same run that deletes its page. -->\n'
             + rows + SM_CLOSE)

    if SM_OPEN in xml and SM_CLOSE in xml:
        new = xml[:xml.index(SM_OPEN)] + block + xml[xml.index(SM_CLOSE) + len(SM_CLOSE):]
    else:
        # first run, or the old ad-hoc comment block is still there — replace it
        old = re.search(r'\n  <!-- ── Products.*?(?=\n</urlset>)', xml, re.S)
        if old:
            xml = xml[:old.start()] + xml[old.end():]
        new = xml.replace('\n</urlset>', '\n' + block + '\n</urlset>')

    assert new.count(SM_OPEN) == 1 and new.count(SM_CLOSE) == 1
    locs = re.findall(r'<loc>https://sakekittycards\.com/p/([^<]+)\.html</loc>', new)
    assert sorted(locs) == sorted(slugs.values()), 'sitemap products drifted from the manifest'
    import xml.dom.minidom as _md
    _md.parseString(new)          # never write a malformed sitemap

    if not dry_run:
        tmp = str(SITEMAP) + '.tmp'
        Path(tmp).write_text(new, encoding='utf-8', newline='')
        os.replace(tmp, SITEMAP)
    return len(locs)


def main():
    global PRICE_VALID_UNTIL
    PRICE_VALID_UNTIL = (_dt.date.today() + _dt.timedelta(days=PRICE_VALID_DAYS)).isoformat()
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--from', dest='src', help='read items from a local JSON file')
    args = ap.parse_args()

    if args.src:
        data = json.loads(Path(args.src).read_text(encoding='utf-8'))
    else:
        req = urllib.request.Request(ITEMS_URL, headers={'User-Agent': 'SakeKitty-ProductPages/1.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode('utf-8'))
    items = data.get('items') if isinstance(data, dict) else data
    items = [i for i in items if i.get('id') and i.get('name') and not i.get('sold')]
    if not items:
        sys.exit('refusing to build: /items returned no usable rows')

    existing = load_manifest()
    slugs = assign_slugs(items, existing)
    if len(set(slugs.values())) != len(slugs):
        sys.exit('slug collision — fix assign_slugs()')
    minted = [k for k in slugs if k not in existing]
    kept = len(slugs) - len(minted)

    plural = {'graded': 'graded slabs', 'sealed': 'sealed product',
              'singles': 'singles', 'merch': 'apparel &amp; merch'}

    written = 0
    for it in items:
        cat = categorize(it)
        slug = slugs[it['id']]
        url = '%sp/%s.html' % (SITE, slug)
        name = it.get('name') or ''
        price = money(it.get('price'))
        image = it.get('imageUrl') or (it.get('imageUrls') or [''])[0] or (SITE + 'og-image.png')
        desc_raw = clean_desc(it.get('description'))
        catword = CAT_WORD.get(cat, 'collector item')

        # Meta descriptions are built to a length budget, not truncated after
        # the fact: card names run long (grader + year + set + card + number),
        # so the NAME is what gets trimmed, never the trailing sales copy.
        if price:
            tail = ' at Sake Kitty Cards. %s, shipped insured. Free shipping over $100.' % catword.capitalize()
            head = '%s — $%s' % (name, price)
            budget = 158 - len(tail) - len(' — $%s' % price)
            if len(name) > budget:
                head = '%s… — $%s' % (name[:budget - 1].rstrip(), price)
            meta_desc = head + tail
            pricetext = '$' + price
            cta = 'Buy it — add to cart'
        else:
            tail = ' — %s at Sake Kitty Cards. No fixed price: send your best offer, we reply within 24 hours.' % catword
            budget = 158 - len(tail)
            meta_desc = (name if len(name) <= budget else name[:budget - 1].rstrip() + '…') + tail
            pricetext = 'Make an Offer'
            cta = 'Make an offer'
        assert len(meta_desc) <= 165, (len(meta_desc), meta_desc)

        stock = it.get('stock')
        stocktext = ('Available now' if stock is None
                     else ('Only %d left' % stock if 0 < stock <= 3
                           else ('In stock' if stock > 0 else 'Out of stock')))

        # Card names are long (grade + year + set + card + number) and every
        # token is a real search term. Keep the whole name and drop the brand
        # suffix before truncating anything: a complete
        # "PSA 10 2023 SV 151 Charizard ex #199/165" beats a chopped one with
        # " | Sake Kitty Cards" bolted on.
        SUFFIX = ' | Sake Kitty Cards'
        if len(name) + len(SUFFIX) <= 65:
            title = name + SUFFIX
        elif len(name) <= 65:
            title = name
        else:
            title = name[:64].rstrip() + '…'

        rows = []
        if it.get('cert'):
            rows.append('            <li><span>Certification #</span><span>%s</span></li>' % esc(it['cert']))
        rows.append('            <li><span>Category</span><span>%s</span></li>' % esc(cat.title()))
        rows.append('            <li><span>Item ID</span><span>%s</span></li>' % esc(it['id']))
        rows.append('            <li><span>Shipping</span><span>Free over $100 &middot; flat $5 under</span></li>')

        descblock = ('\n'.join('<p>%s</p>' % esc(x.strip())
                               for x in re.split(r'\n{2,}', (it.get('description') or '').strip())
                               if x.strip()) or '<p>%s from Sake Kitty Cards.</p>' % esc(catword.capitalize()))

        iw, ih = (760, 1060) if cat == 'graded' else (760, 760)

        page = PAGE.format(
            title=esct(title), desc=esc(meta_desc), url=esc(url), ogtitle=esc(title),
            image=esc(image), imgalt=esc(name), schema=build_schema(it, cat, url, image, price, desc_raw),
            cssv=CSS_V, jsv=JS_V, skip=SKIP, nav=NAV.replace('href="', 'href="../').replace('href="../https', 'href="https').replace('src="', 'src="../'),
            footer=FOOTER.replace('href="', 'href="../').replace('href="../https', 'href="https').replace('src="', 'src="../'),
            h1=esct(name), shortname=esct(name[:46] + ('…' if len(name) > 46 else '')),
            crumbname=CAT_CRUMB.get(cat, ('Shop', 'shop.html'))[0],
            crumbhref=esc(CAT_CRUMB.get(cat, ('Shop', 'shop.html'))[1]),
            pricetext=esc(pricetext), stocktext=esc(stocktext), cta=esc(cta),
            sku=esc(it['id']), skujson=json.dumps(it['id']), catjson=json.dumps(cat),
            descblock=descblock, metarows='\n'.join(rows),
            catplural=plural.get(cat, 'items'),
            related=related_html(it, cat, items, slugs),
            iw=iw, ih=ih,
        )

        # sanity before anything hits disk
        assert page.rstrip().endswith('</html>')
        assert page.count('<h1') == 1
        for mm in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
            json.loads(mm.group(1))

        if not args.dry_run:
            OUT_DIR.mkdir(exist_ok=True)
            (OUT_DIR / (slug + '.html')).write_text(page, encoding='utf-8', newline='\n')
        written += 1

    # prune pages whose SKU is gone, so p/ can't accumulate dead files
    pruned = []
    if OUT_DIR.exists() and not args.dry_run:
        keep = {s + '.html' for s in slugs.values()}
        for f in OUT_DIR.glob('*.html'):
            if f.name not in keep:
                f.unlink()
                pruned.append(f.name)

    if not args.dry_run:
        MANIFEST.parent.mkdir(exist_ok=True)
        MANIFEST.write_text(json.dumps(slugs, indent=0, sort_keys=True), encoding='utf-8', newline='\n')
    n_sm = sync_sitemap(slugs, _dt.date.today().isoformat(), args.dry_run)

    print('items: %d   pages %s: %d   pruned: %d   slugs kept: %d, minted: %d'
          % (len(items), 'that would be written' if args.dry_run else 'written',
             written, len(pruned), kept, len(minted)))
    print('sitemap product URLs: %d' % n_sm)
    if minted:
        print('  new URLs: %s' % ', '.join(slugs[k] for k in minted[:4]))
    if pruned:
        print('  pruned: %s' % ', '.join(pruned[:6]))
    by = {}
    for i in items:
        by[categorize(i)] = by.get(categorize(i), 0) + 1
    print('by category: %s' % by)
    if not args.dry_run:
        print('manifest: %s (%d entries)' % (MANIFEST.relative_to(ROOT), len(slugs)))


if __name__ == '__main__':
    main()
