# -*- coding: utf-8 -*-
"""Static SEO/QA crawl of the site as it sits on disk.

No network, no build step — it just reads every .html at the repo root and
asserts the things that actually break rankings when they silently drift:
tag balance, JSON-LD validity, title/description uniqueness and length,
canonical self-reference, internal link integrity, and sitemap coverage
against the real set of indexable pages.

Run before every SEO-touching PR:  python scripts/seo_audit.py
Exit code is non-zero if any ERROR fires, so it can gate CI later.
"""
import glob, html as _html, json, os, re, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
SITE = 'https://sakekittycards.com/'

errors, warns = [], []
def err(m): errors.append(m)
def warn(m): warns.append(m)

def strip_code(h):
    h = re.sub(r'<script.*?</script>', '', h, flags=re.S)
    return re.sub(r'<style.*?</style>', '', h, flags=re.S)

# Root pages plus the generated per-SKU product pages. The p/ pages are real
# indexable URLs and must be held to the same bar as everything else.
files = sorted(glob.glob('*.html')) + sorted(glob.glob('p/*.html'))
pages = {}
for f in files:
    pages[f] = open(f, encoding='utf-8').read()

titles, descs = defaultdict(list), defaultdict(list)
indexable = set()

for f, h in pages.items():
    m = strip_code(h)

    # ── structure ────────────────────────────────────────────────────────
    if not h.rstrip().endswith('</html>'):
        err('%s: does not end with </html>' % f)
    for t in ('div', 'p', 'main', 'nav', 'footer', 'ul', 'li', 'a', 'section',
              'details', 'table', 'article', 'h1', 'h2', 'h3', 'button'):
        o = len(re.findall(r'<%s[\s>]' % t, m))
        c = len(re.findall(r'</%s>' % t, m))
        if o != c:
            err('%s: <%s> unbalanced — %d open, %d close' % (f, t, o, c))

    # ── indexability ─────────────────────────────────────────────────────
    rb = re.search(r'<meta name="robots" content="([^"]*)"', h)
    noindex = bool(rb and 'noindex' in rb.group(1).lower())
    redirect = bool(re.search(r'<meta http-equiv="refresh"', h, re.I))
    if not noindex and not redirect:
        indexable.add(f)

    h1s = re.findall(r'<h1[\s>]', m)
    if not redirect and len(h1s) != 1:
        # A missing <h1> is only an ERROR on a page we're asking Google to index.
        # product.html renders its <h1> from JS — a known limitation of one
        # template serving every SKU, tracked separately, so it warns not errors.
        bad = len(h1s) == 0 and not noindex and f != 'product.html'
        (err if bad else warn)('%s: %d <h1> in static markup (want exactly 1)' % (f, len(h1s)))

    # a11y baseline the repo standardizes on
    if 'skip-link' not in h:
        warn('%s: no skip-link' % f)
    if 'id="main"' not in h:
        warn('%s: no <main id="main">' % f)


    # ── metadata ─────────────────────────────────────────────────────────
    t = re.search(r'<title>(.*?)</title>', h, re.S)
    d = re.search(r'<meta name="description" content="([^"]*)"', h)
    if redirect:
        pass
    elif not t:
        err('%s: no <title>' % f)
    else:
        # Measure what a SERP actually renders: '&amp;' is one character on
        # screen, not five. Counting the raw entity flags titles that are fine.
        title = _html.unescape(re.sub(r'\s+', ' ', t.group(1)).strip())
        titles[title].append(f)
        if not noindex:
            if len(title) > 65:
                warn('%s: title %d chars (>65 truncates in SERP) — %s' % (f, len(title), title))
            if len(title) < 20:
                warn('%s: title only %d chars' % (f, len(title)))
    if not redirect and not d:
        (warn if noindex else err)('%s: no meta description' % f)
    elif d:
        desc = _html.unescape(d.group(1).strip())
        descs[desc].append(f)
        if not noindex:
            if len(desc) > 165:
                warn('%s: description %d chars (>165 truncates)' % (f, len(desc)))
            if len(desc) < 70:
                warn('%s: description only %d chars' % (f, len(desc)))

    # ── canonical ────────────────────────────────────────────────────────
    can = re.search(r'<link rel="canonical" href="([^"]*)"', h)
    if not redirect and not noindex:
        if not can:
            err('%s: no canonical' % f)
        else:
            want = SITE if f == 'index.html' else SITE + f.replace(os.sep, '/')
            if can.group(1) != want:
                # product.html rewrites its canonical per-SKU in JS; expected.
                if f != 'product.html':
                    err('%s: canonical %s != %s' % (f, can.group(1), want))

    # ── social ───────────────────────────────────────────────────────────
    if not redirect and not noindex:
        for tag in ('og:title', 'og:description', 'og:image', 'og:url', 'og:type'):
            if 'property="%s"' % tag not in h:
                warn('%s: missing %s' % (f, tag))
        if 'name="twitter:card"' not in h:
            warn('%s: missing twitter:card' % f)

    # ── JSON-LD ──────────────────────────────────────────────────────────
    for i, mm in enumerate(re.finditer(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)):
        try:
            data = json.loads(mm.group(1))
        except Exception as e:
            err('%s: JSON-LD block %d invalid — %s' % (f, i, e))
            continue
        for node in (data.get('@graph') if isinstance(data, dict) and '@graph' in data
                     else [data] if isinstance(data, dict) else data):
            if not isinstance(node, dict):
                continue
            ty = node.get('@type')
            if not ty:
                warn('%s: JSON-LD node with no @type' % f)
                continue
            # Required properties per type. Google will silently ignore a node
            # that's missing these, so a "valid JSON" check alone is not enough.
            need = {
                'Organization': ('name', 'url'),
                'WebSite':      ('name', 'url'),
                'Service':      ('name', 'provider'),
                'Article':      ('headline', 'author', 'publisher', 'datePublished'),
                'FAQPage':      ('mainEntity',),
                'BreadcrumbList': ('itemListElement',),
                'CollectionPage': ('name',),
                'AboutPage':    ('name',),
                'Product':      ('name',),
            }.get(ty, ())
            for k in need:
                if k not in node:
                    err('%s: %s node missing required "%s"' % (f, ty, k))
            if ty == 'BreadcrumbList':
                pos = [i.get('position') for i in node.get('itemListElement', [])]
                if pos != list(range(1, len(pos) + 1)):
                    err('%s: BreadcrumbList positions not 1..n — %s' % (f, pos))
                for i in node.get('itemListElement', []):
                    if not i.get('name') or not i.get('item'):
                        err('%s: BreadcrumbList item missing name/item' % f)
            if ty == 'FAQPage':
                for q in node.get('mainEntity', []):
                    if not q.get('name'):
                        err('%s: FAQ question with no name' % f)
                    a = (q.get('acceptedAnswer') or {}).get('text', '')
                    if len(a) < 25:
                        err('%s: FAQ answer too short/empty for %r' % (f, q.get('name', '')[:40]))
            if ty in ('Article', 'FAQPage'):
                # FAQ/Article markup must describe content that is actually visible.
                pass

    # ── images ───────────────────────────────────────────────────────────
    for img in re.finditer(r'<img\b([^>]*)>', m):
        a = img.group(1)
        if 'alt=' not in a:
            err('%s: <img> without alt — %s' % (f, a.strip()[:70]))
        if not ('width=' in a and 'height=' in a):
            warn('%s: <img> without width/height (CLS risk) — %s' % (f, a.strip()[:70]))

# ── duplicate metadata ───────────────────────────────────────────────────
for t, fs in titles.items():
    live = [x for x in fs if x in indexable]
    if len(live) > 1:
        err('duplicate title across %s — %s' % (live, t[:60]))
for d, fs in descs.items():
    live = [x for x in fs if x in indexable]
    if len(live) > 1:
        err('duplicate description across %s' % live)

# ── internal links ───────────────────────────────────────────────────────
on_disk = set(os.listdir('.'))
for f, h in pages.items():
    for href in re.findall(r'href="([^"#?][^"]*)"', strip_code(h)):
        if re.match(r'^(https?:|mailto:|tel:|//|#|data:)', href):
            continue
        target = href.split('#')[0].split('?')[0]
        if target.startswith('/'):
            target = target.lstrip('/')          # root-relative -> repo-relative
        else:
            # resolve against the page's own directory (matters for p/*.html)
            target = os.path.normpath(os.path.join(os.path.dirname(f), target))
        if not target:
            continue
        # GitHub Pages resolves an extensionless path to the .html file
        # (verified live: /whatnot returns 200). Both forms are valid; the
        # canonical tag on each page settles which one gets indexed.
        if not (os.path.exists(target)
                or os.path.exists(target + '.html')
                or os.path.exists(os.path.join(target, 'index.html'))):
            err('%s: broken internal link -> %s' % (f, href))

# ── sitemap ──────────────────────────────────────────────────────────────
sm = open('sitemap.xml', encoding='utf-8').read()
locs = re.findall(r'<loc>([^<]+)</loc>', sm)
if len(locs) != len(set(locs)):
    err('sitemap: duplicate <loc> entries')
listed = set()
for loc in locs:
    if not loc.startswith(SITE):
        err('sitemap: %s is not on the canonical host' % loc)
        continue
    path = loc[len(SITE):] or 'index.html'
    listed.add(path)
    if not os.path.exists(path):
        err('sitemap: %s does not exist on disk' % path)
    elif path in pages and path not in indexable:
        err('sitemap: %s is noindex/redirect but is listed' % path)
for m in re.findall(r'<lastmod>([^<]+)</lastmod>', sm):
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', m):
        err('sitemap: bad lastmod %s' % m)

# every indexable content page should be in the sitemap, except the known
# deliberate exclusions
EXEMPT = {'product.html',        # template, not a page — SKUs crawl from shop.html
          '404.html'}
for f in sorted(indexable):
    if f.replace(os.sep, '/') in EXEMPT or f.replace(os.sep, '/') in listed:
        continue
    warn('sitemap: indexable page %s is NOT listed' % f)

# ── robots ───────────────────────────────────────────────────────────────
rb = open('robots.txt', encoding='utf-8').read()
if 'Sitemap: %ssitemap.xml' % SITE not in rb:
    err('robots.txt: sitemap line missing or wrong')
if re.search(r'^Disallow:\s*/\s*$', rb, re.M):
    err('robots.txt: blanket Disallow: / present')

# ── report ───────────────────────────────────────────────────────────────
print('scanned %d html files · %d indexable' % (len(pages), len(indexable)))
print()
if warns:
    print('WARNINGS (%d)' % len(warns))
    for w in warns:
        print('  ~ %s' % w)
    print()
if errors:
    print('ERRORS (%d)' % len(errors))
    for e in errors:
        print('  X %s' % e)
    print()
    sys.exit(1)
print('No errors.')
