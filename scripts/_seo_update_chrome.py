"""One-shot: rewrite the shared nav + footer on every chrome page.

Nav goes from 11 flat top-level items to 8 intent-grouped ones so the new
commercial landing pages get a real crawlable link from every page without
making the bar longer. Footer picks up the same pages.

Idempotent: re-running finds the NEW blocks already in place and no-ops.
Preserves the per-page aria-current="page" marker.
"""
import re, os, sys, glob

NAV = '''<ul class="nav-links" id="navLinks">
        <li><a href="index.html">Home</a></li>
        <li class="nav-dropdown">
          <a href="shop.html">Shop</a>
          <ul class="nav-dropdown-menu" aria-label="Shop categories">
            <li><a href="shop.html?cat=graded">Graded Cards</a></li>
            <li><a href="graded.html">Graded Vault</a></li>
            <li><a href="shop.html?cat=merch">Apparel &amp; Merch</a></li>
            <li><a href="wholesale-pokemon.html">Wholesale &amp; B2B</a></li>
          </ul>
        </li>
        <li class="nav-dropdown">
          <a href="trade-in.html">Sell / Trade</a>
          <ul class="nav-dropdown-menu" aria-label="Ways to sell your cards">
            <li><a href="sell-pokemon-collection.html">Sell a Collection</a></li>
            <li><a href="sell-graded-pokemon-cards.html">Sell Graded Slabs</a></li>
            <li><a href="pokemon-card-appraisal.html">Card Appraisal</a></li>
            <li><a href="pokemon-card-buyer-florida.html">Selling in Florida</a></li>
          </ul>
        </li>
        <li><a href="grading-prep.html">Grading Prep</a></li>
        <li><a href="events.html">Events</a></li>
        <li class="nav-dropdown">
          <a href="resources.html">Resources</a>
          <ul class="nav-dropdown-menu" aria-label="Guides and resources">
            <li><a href="guide-should-you-grade.html">Should You Grade?</a></li>
            <li><a href="guide-what-dealers-pay.html">What Dealers Pay</a></li>
            <li><a href="shipping.html">Shipping &amp; Packing</a></li>
            <li><a href="faq.html">FAQ</a></li>
          </ul>
        </li>
        <li class="nav-dropdown">
          <a href="about.html">About</a>
          <ul class="nav-dropdown-menu" aria-label="About Sake Kitty Cards">
            <li><a href="team.html">Our Team</a></li>
            <li><a href="reviews.html">Reviews</a></li>
            <li><a href="watch.html">Watch</a></li>
          </ul>
        </li>
        <li><a href="contact.html" class="nav-cta">Contact</a></li>
      </ul>
    </div>
  </nav>'''

FOOTER = '''<nav class="footer-nav">
        <a href="shop.html">Shop</a>
        <a href="graded.html">Graded Vault</a>
        <a href="wholesale-pokemon.html">Wholesale</a>
        <a href="events.html">Events</a>
        <a href="trade-in.html">Sell / Trade</a>
        <a href="sell-pokemon-collection.html">Sell a Collection</a>
        <a href="sell-graded-pokemon-cards.html">Sell Graded Slabs</a>
        <a href="pokemon-card-appraisal.html">Card Appraisal</a>
        <a href="pokemon-card-buyer-florida.html">Selling in Florida</a>
        <a href="grading-prep.html">Grading Prep</a>
        <a href="resources.html">Guides</a>
        <a href="shipping.html">Shipping Guide</a>
        <a href="faq.html">FAQ</a>
        <a href="about.html">About</a>
        <a href="team.html">Our Team</a>
        <a href="reviews.html">Reviews</a>
        <a href="watch.html">Watch</a>
        <a href="contact.html">Contact</a>
        <a href="track.html">Track Order</a>
        <a href="gift-cards.html">Gift Cards</a>
      </nav>'''

NAVPAT = re.compile(r'<ul class="nav-links" id="navLinks">.*?</ul>\s*\n\s*</div>\s*\n\s*</nav>', re.S)
FTPAT  = re.compile(r'<nav class="footer-nav">.*?</nav>', re.S)

def balanced(h, f):
    """Cheap structural assertions — catches a botched splice."""
    assert h.rstrip().endswith('</html>'), f'{f}: does not end with </html>'
    for tag in ('nav', 'main', 'footer', 'body', 'html', 'ul'):
        o = len(re.findall(r'<%s[\s>]' % tag, h)); c = len(re.findall(r'</%s>' % tag, h))
        assert o == c, f'{f}: <{tag}> {o} open vs {c} close'

changed = []
for f in sorted(glob.glob('*.html')):
    h = open(f, encoding='utf-8', newline='').read()
    if not NAVPAT.search(h) or not FTPAT.search(h):
        continue
    nav = NAV
    # keep the page's own aria-current marker
    m = re.search(r'<a href="([^"]+)" aria-current="page">', NAVPAT.search(h).group(0))
    if m:
        href = m.group(1)
        nav = nav.replace('<a href="%s">' % href, '<a href="%s" aria-current="page">' % href, 1)
    new = FTPAT.sub(lambda _: FOOTER, NAVPAT.sub(lambda _: nav, h, count=1), count=1)
    if new == h:
        continue
    balanced(new, f)
    tmp = f + '.tmp'
    open(tmp, 'w', encoding='utf-8', newline='').write(new)
    os.replace(tmp, f)
    changed.append(f)

print('updated %d files:' % len(changed))
print('  ' + ' '.join(changed))
