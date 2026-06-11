r"""
Render singles.html from assets/singles/singles_data.json.

Top-50 "Make Offer" gallery — no prices. Each card links to a prefilled
mailto offer to nick@sakekittycards.com. Static HTML (SEO-friendly), matches
the site's nav/footer/head conventions. Unlinked page (not added to nav).

    py -3 scripts/render_singles_page.py
"""
from __future__ import annotations
import html, json, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "assets" / "singles" / "singles_data.json").read_text(encoding="utf-8"))
OUT = ROOT / "singles.html"
EMAIL = "nick@sakekittycards.com"

COND_CLASS = {"near mint": "nm", "lightly played": "lp", "moderately played": "mp",
              "heavily played": "hp", "damaged": "dmg"}


def cond_class(cond):
    c = (cond or "").lower()
    for k, v in COND_CLASS.items():
        if c.startswith(k):
            return v
    return "nm"


def card_html(c):
    name = c["name"]
    setn = c["set"]
    num = c["number"]
    cond = c["condition"]
    lang = c.get("lang", "English")
    img = c.get("img")
    qty = c.get("qty", 1)
    label = f"{name} — {num}"
    subject = f"Offer: {label} ({setn})"
    body = (f"Hi Nick,\n\nI'd like to make an offer on this single:\n\n"
            f"Card: {name} {num}\nSet: {setn}\nCondition: {cond}\n\nMy offer: $")
    mailto = (f"mailto:{EMAIL}?subject={urllib.parse.quote(subject)}"
              f"&body={urllib.parse.quote(body)}")
    e = html.escape
    img_tag = (f'<img src="{e(img)}" alt="{e(name)} {e(num)} — {e(setn)}" '
               f'loading="lazy" decoding="async" width="400" height="558" />'
               if img else '<div class="single-noimg">No image</div>')
    lang_badge = '<span class="single-lang jp">JP</span>' if lang == "Japanese" else ""
    qty_badge = f'<span class="single-qty">{qty} avail</span>' if qty > 1 else ""
    ph_badge = '<span class="single-ph">Placeholder photo</span>' if c.get("placeholder") else ""
    return f"""        <article class="single-card">
          <a class="single-imgwrap" href="{e(mailto)}" aria-label="Make an offer on {e(name)} {e(num)}">
            {img_tag}{lang_badge}{ph_badge}
          </a>
          <div class="single-meta">
            <h3 class="single-name">{e(name)}</h3>
            <p class="single-sub">{e(setn)} · #{e(num)}</p>
            <div class="single-tags">
              <span class="single-cond cond-{cond_class(cond)}">{e(cond)}</span>{qty_badge}
            </div>
            <a class="btn make-offer" href="{e(mailto)}">Make Offer</a>
          </div>
        </article>"""


cards = "\n".join(card_html(c) for c in DATA)

HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="icon" type="image/png" href="logo.png" />
  <link rel="apple-touch-icon" href="logo.png" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="theme-color" content="#06060a" />
  <meta name="color-scheme" content="dark" />
  <title>Featured Singles — Make an Offer | Sake Kitty Cards</title>
  <meta name="description" content="A rotating selection of our top Pokémon singles — graded-worthy chase cards, vintage holos, and modern alt arts. No fixed price: send your best offer and we'll reply." />

  <link rel="canonical" href="https://sakekittycards.com/singles.html" />
  <meta property="og:title" content="Featured Singles — Make an Offer | Sake Kitty Cards" />
  <meta property="og:description" content="A rotating selection of our top Pokémon singles. No fixed price — send your best offer and we'll reply." />
  <meta property="og:site_name" content="Sake Kitty Cards" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:image" content="https://sakekittycards.com/og-image.png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:url" content="https://sakekittycards.com/singles.html" />
  <meta property="og:type" content="website" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Featured Singles — Make an Offer | Sake Kitty Cards" />
  <meta name="twitter:description" content="A rotating selection of our top Pokémon singles. No fixed price — send your best offer and we'll reply." />
  <meta name="twitter:image" content="https://sakekittycards.com/og-image.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bangers&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="style.css?v=170" />
  <style>
    .page-singles .page-hero {{ padding-bottom: 18px; }}
    .page-singles .page-hero h1 {{ font-size: clamp(38px, 7vw, 60px); }}
    .singles-tagline {{
      font-family: 'Inter', sans-serif; font-weight: 700;
      font-size: clamp(13px, 2.2vw, 16px); letter-spacing: 0.05em;
      text-transform: uppercase; margin-top: 12px;
    }}
    .singles-tagline .ok {{ color: var(--cyan); }}
    .singles-tagline .pop {{ color: var(--pink); }}
    .singles-note {{
      display: flex; gap: 10px; align-items: flex-start;
      max-width: 760px; margin: 16px auto 0;
      padding: 12px 16px; border-radius: 12px;
      background: rgba(0,212,255,0.08); border: 1px solid rgba(0,212,255,0.28);
      color: rgba(255,255,255,0.88); font-size: 14px; line-height: 1.55; text-align: left;
    }}
    .singles-note strong {{ color: var(--cyan); }}

    .singles-grid {{
      display: grid; gap: 18px;
      grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    }}
    .single-card {{
      display: flex; flex-direction: column;
      background: var(--panel, #12121c); border: 1px solid var(--border);
      border-radius: 14px; overflow: hidden;
      transition: transform .2s ease, border-color .2s, box-shadow .2s;
    }}
    .single-card:hover {{
      transform: translateY(-4px); border-color: rgba(255,106,0,0.55);
      box-shadow: 0 14px 34px rgba(255,106,0,0.18), 0 0 26px rgba(123,47,255,0.12);
    }}
    .single-imgwrap {{
      position: relative; display: block; padding: 16px 16px 8px;
      background: radial-gradient(circle at 50% 35%, rgba(123,47,255,0.14), transparent 70%);
    }}
    .single-imgwrap img {{
      display: block; width: 100%; height: auto; border-radius: 8px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.45);
    }}
    .single-lang {{
      position: absolute; top: 22px; right: 22px;
      font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 6px;
      background: #4a2540; color: #ffb6e6;
    }}
    .single-ph {{
      position: absolute; top: 22px; left: 22px;
      font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 6px;
      background: rgba(0,0,0,0.74); color: #ffd27a; letter-spacing: .02em;
    }}
    .singles-tcg {{
      max-width: 720px; margin: 30px auto 0; padding: 22px 24px; border-radius: 16px;
      text-align: center;
      background: linear-gradient(135deg, rgba(255,106,0,0.12), rgba(123,47,255,0.12));
      border: 1px solid rgba(255,106,0,0.35);
    }}
    .singles-tcg h2 {{ margin: 0 0 6px; font-size: clamp(20px,4vw,26px); }}
    .singles-tcg p {{ margin: 0 0 14px; color: var(--muted); font-size: 14px; line-height: 1.5; }}
    .single-meta {{ padding: 4px 16px 16px; display: flex; flex-direction: column; gap: 8px; flex: 1; }}
    .single-name {{ font-size: 16px; font-weight: 700; margin: 0; line-height: 1.2; }}
    .single-sub {{ font-size: 12.5px; color: var(--dim); margin: 0; }}
    .single-tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 2px; }}
    .single-cond {{
      font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px;
      background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.9);
    }}
    .single-cond.cond-nm {{ background: rgba(80,220,140,0.16); color: #6ee7b7; }}
    .single-cond.cond-lp {{ background: rgba(0,212,255,0.16); color: #67d8ff; }}
    .single-cond.cond-mp {{ background: rgba(255,184,77,0.16); color: #ffce85; }}
    .single-cond.cond-hp,
    .single-cond.cond-dmg {{ background: rgba(255,0,128,0.16); color: #ff7ab0; }}
    .single-qty {{
      font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 6px;
      background: rgba(255,255,255,0.06); color: var(--dim);
    }}
    .make-offer {{ margin-top: auto; width: 100%; justify-content: center; }}
    @media (max-width: 560px) {{
      .singles-grid {{ grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }}
      .single-name {{ font-size: 15px; }}
    }}
  </style>
</head>
<body class="page-singles">
  <a class="skip-link" href="#main">Skip to main content</a>
  <div class="bg-blob bg-blob-1"></div>
  <div class="bg-blob bg-blob-2"></div>

  <nav class="site-nav" id="siteNav">
    <div class="nav-inner">
      <a href="index.html" class="nav-logo">
        <img width="32" height="32" src="logo.png" alt="Sake Kitty Cards" />
        <span>Sake Kitty Cards</span>
      </a>
      <button class="nav-toggle" id="navToggle" aria-label="Toggle menu" aria-expanded="false" aria-controls="navLinks">
        <span></span><span></span><span></span>
      </button>
      <ul class="nav-links" id="navLinks">
        <li><a href="index.html">Home</a></li>
        <li class="nav-dropdown">
          <a href="shop.html">Shop</a>
          <ul class="nav-dropdown-menu" aria-label="Shop categories">
            <li><a href="shop.html?cat=graded">Graded Cards</a></li>
            <li><a href="shop.html?cat=sealed">Sealed</a></li>
            <li><a href="shop.html?cat=singles">Singles</a></li>
            <li><a href="shop.html?cat=merch">Apparel &amp; Merch</a></li>
          </ul>
        </li>
        <li><a href="trade-in.html">Sell / Trade</a></li>
        <li><a href="grading-prep.html">Grading Prep</a></li>
        <li><a href="events.html">Events</a></li>
        <li><a href="team.html">Our Team</a></li>
        <li><a href="about.html">About</a></li>
        <li><a href="reviews.html">Reviews</a></li>
        <li class="nav-dropdown">
          <a href="resources.html">Resources</a>
          <ul class="nav-dropdown-menu" aria-label="Resources">
            <li><a href="shipping.html">Shipping &amp; Packing</a></li>
            <li><a href="faq.html">FAQ</a></li>
          </ul>
        </li>
        <li><a href="contact.html" class="nav-cta">Contact</a></li>
      </ul>
    </div>
  </nav>

  <main id="main" class="page-content">
    <div class="page-hero">
      <h1>Today's Singles</h1>
      <p>Today's top picks from our inventory — vintage holos, chase alt arts, and modern hits. No fixed price: send your best offer, or buy now on TCGplayer.</p>
      <p class="singles-tagline">Today's <span class="ok">Picks</span> · Best <span class="pop">Offer</span></p>
      <div class="singles-note">
        <span aria-hidden="true">📍</span>
        <span>We're local vendors — these also sell in person and at shows, so availability can change. <strong>We'll confirm a card is still here before anything's finalized.</strong> Tap any card to send an offer straight to Nick.</span>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="singles-grid">
{cards}
      </div>
      <div class="singles-tcg">
        <h2>Want the full list?</h2>
        <p>These are just today's picks. Browse our entire inventory — and buy now at a set price — on our TCGplayer store.</p>
        <a class="btn btn-lg" href="https://www.tcgplayer.com/sellers/Sake-Kitty-Cards/cb1bc211" target="_blank" rel="noopener">Shop our TCGplayer store →</a>
      </div>
    </div>
  </main>

  <footer class="site-footer">
    <div class="footer-inner">
      <div class="footer-brand">
        <img width="44" height="44" src="logo.png" alt="Sake Kitty Cards" class="footer-logo-img" />
        <a href="https://www.instagram.com/sakekittycards" target="_blank" rel="noopener" class="footer-ig">
          <svg viewBox="0 0 24 24"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/></svg>
          @sakekittycards
        </a>
        <a href="https://www.youtube.com/@SakeKittyCards" target="_blank" rel="noopener" class="footer-yt">
          <svg viewBox="0 0 24 24"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
          @SakeKittyCards
        </a>
      </div>
      <nav class="footer-nav">
        <a href="shop.html">Shop</a>
        <a href="events.html">Events</a>
        <a href="team.html">Our Team</a>
        <a href="trade-in.html">Sell / Trade</a>
        <a href="grading-prep.html">Grading Prep</a>
        <a href="reviews.html">Reviews</a>
        <a href="resources.html">Resources</a>
        <a href="shipping.html">Shipping Guide</a>
        <a href="faq.html">FAQ</a>
        <a href="about.html">About</a>
        <a href="contact.html">Contact</a>
        <a href="track.html">Track Order</a>
        <a href="gift-cards.html">Gift Cards</a>
      </nav>
    </div>
    <p class="footer-copy">© 2026 Sake Kitty Cards. All rights reserved. · <a href="grading-terms.html" style="color:var(--dim)">Grading Prep Terms</a></p>
  </footer>

  <script src="main.js?v=63" defer></script>
</body>
</html>
"""

OUT.write_text(HTML, encoding="utf-8")
print(f"wrote {OUT} ({len(DATA)} cards, {sum(1 for c in DATA if c.get('img'))} with images)")
