"""Shared page kit for the SEO landing pages + guides (2026-09-01 SEO overhaul).

Emits a full static page carrying the exact sitewide chrome: head/meta/OG/Twitter
baseline, skip-link, nav, footer, main.js. Read the nav + footer straight out of
`about.html` at build time, so this file can NEVER drift from the live chrome the
way scripts/build_graded_page.py did (see project_sk_seo_audit_2026-08 memory).

One-shot scaffolder: `emit()` refuses to clobber an existing file unless force=True.
After a page is emitted it is hand-maintained like every other page in the repo.
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = 'https://sakekittycards.com/'

_about = open(os.path.join(ROOT, 'about.html'), encoding='utf-8').read()
NAV = re.search(r'  <nav class="site-nav".*?</nav>', _about, re.S).group(0)
FOOTER = re.search(r'  <footer class="site-footer">.*?</footer>', _about, re.S).group(0)
CSS_V = re.search(r'style\.css\?v=(\d+)', _about).group(1)
JS_V = re.search(r'main\.js\?v=(\d+)', _about).group(1)
SKIP = re.search(r'<a class="skip-link"[^>]*>.*?</a>', _about, re.S)
SKIP = SKIP.group(0) if SKIP else '<a class="skip-link" href="#main">Skip to main content</a>'


def breadcrumbs(trail):
    """trail: [(name, path_or_None)] — last item is the current page."""
    items = []
    for i, (name, path) in enumerate(trail, start=1):
        items.append(
            '      { "@type": "ListItem", "position": %d, "name": %s, "item": "%s" }'
            % (i, _j(name), SITE + (path or ''))
        )
    return ('  {\n    "@context": "https://schema.org",\n'
            '    "@type": "BreadcrumbList",\n    "itemListElement": [\n'
            + ',\n'.join(items) + '\n    ]\n  }')


def _j(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ') + '"'


def faq_schema(pairs):
    qs = []
    for q, a in pairs:
        a_txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', a)).strip()
        qs.append('      {\n        "@type": "Question",\n        "name": %s,\n'
                  '        "acceptedAnswer": { "@type": "Answer", "text": %s }\n      }'
                  % (_j(q), _j(a_txt)))
    return ('  {\n    "@context": "https://schema.org",\n    "@type": "FAQPage",\n'
            '    "mainEntity": [\n' + ',\n'.join(qs) + '\n    ]\n  }')


def faq_html(pairs):
    out = ['      <div class="faq-list">']
    for q, a in pairs:
        out.append('        <details class="faq-item">')
        out.append('          <summary class="faq-q">%s <span class="faq-icon">+</span></summary>' % q)
        out.append('          <div class="faq-a">%s</div>' % a)
        out.append('        </details>')
    out.append('      </div>')
    return '\n'.join(out)


PAGE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="icon" type="image/png" href="logo-icon.png" />
  <link rel="apple-touch-icon" href="logo-touch.png" />
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
  <meta property="og:image" content="https://sakekittycards.com/og-image.png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt" content="Sake Kitty Cards — Pokemon card vendor" />
  <meta property="og:url" content="{url}" />
  <meta property="og:type" content="{ogtype}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{ogtitle}" />
  <meta name="twitter:description" content="{desc}" />
  <meta name="twitter:image" content="https://sakekittycards.com/og-image.png" />
{schema}
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bangers&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="style.css?v={cssv}" />
{style}</head>
<body>
  {skip}

{nav}

  <main id="main" class="page-content">
{body}
  </main>

{footer}

  <script src="main.js?v={jsv}" defer></script>
</body>
</html>
'''


def emit(filename, *, title, desc, body, schema=(), ogtitle=None, ogtype='website',
         style='', force=False):
    path = os.path.join(ROOT, filename)
    if os.path.exists(path) and not force:
        print('  SKIP (exists): %s' % filename)
        return False
    blocks = ''
    for s in schema:
        blocks += '  <script type="application/ld+json">\n%s\n  </script>\n' % s
    if style:
        style = '  <style>\n%s\n  </style>\n' % style
    html = PAGE.format(
        title=title, desc=desc, url=SITE + filename, ogtitle=ogtitle or title,
        ogtype=ogtype, schema=blocks, cssv=CSS_V, jsv=JS_V, skip=SKIP,
        nav=NAV, footer=FOOTER, body=body, style=style,
    )
    _assert_sound(html, filename)
    tmp = path + '.tmp'
    open(tmp, 'w', encoding='utf-8', newline='').write(html)
    os.replace(tmp, path)
    print('  wrote %-40s %6d bytes' % (filename, len(html)))
    return True


def _assert_sound(h, name):
    assert h.rstrip().endswith('</html>'), '%s: missing </html>' % name
    for tag in ('nav', 'main', 'footer', 'body', 'html', 'ul', 'section', 'table',
                'details', 'div', 'p', 'h1', 'h2', 'h3'):
        o = len(re.findall(r'<%s[\s>]' % tag, h))
        c = len(re.findall(r'</%s>' % tag, h))
        assert o == c, '%s: <%s> %d open vs %d close' % (name, tag, o, c)
    assert h.count('<h1') == 1, '%s: needs exactly one h1' % name
    import json
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        try:
            json.loads(m.group(1))
        except Exception as e:
            raise AssertionError('%s: invalid JSON-LD — %s' % (name, e))
