"""Build graded.html — the Graded Vault make-offer gallery.

Reads assets/graded-slabs.json (slab manifest: cert, grader, grade, name, set,
number, variant, lang) + the processed slab photos (front/back, named
<cert>F.jpg / <cert>B.jpg), resizes them into assets/graded/, and emits the
static graded.html page. Same make-offer model as singles.html: no prices,
prefilled mailto to nick@sakekittycards.com.

Photos come from the SK Graded Photos pipeline (crop + deskew + logo). Point
PROCESSED_DIR at the shoot's _processed folder before running.

Usage: python scripts/build_graded_page.py
"""
import json
import html
import urllib.parse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = Path(r"D:\Dropbox\TCG PICTURES\GRADED PICTURES - 8-5\_processed")
IMG_DIR = ROOT / "assets" / "graded"
DATA = ROOT / "assets" / "graded-slabs.json"
OUT = ROOT / "graded.html"

IMG_W, IMG_H = 500, 1000  # slab photos are 1:2
JPEG_QUALITY = 82


def export_images(slabs):
    IMG_DIR.mkdir(exist_ok=True)
    for s in slabs:
        for side, suffix in (("F", ""), ("B", "b")):
            src = PROCESSED_DIR / f"{s['cert']}{side}.jpg"
            dst = IMG_DIR / f"{s['cert']}{suffix}.jpg"
            if dst.exists():
                continue
            im = Image.open(src)
            im = im.resize((IMG_W, IMG_H), Image.LANCZOS)
            im.save(dst, "JPEG", quality=JPEG_QUALITY, optimize=True)


def verify_url(s):
    if s["grader"] == "PSA":
        return f"https://www.psacard.com/cert/{s['cert']}"
    return f"https://www.cgccards.com/certlookup/{s['cert']}/"


# Prices pulled down 2026-08-10 (Nick: make-offer only). Price data stays in
# graded-slabs.json untouched — flip to False to show asks again.
MAKE_OFFER_ONLY = True


def fmt_price(s):
    if MAKE_OFFER_ONLY:
        return ""
    return f"${s['price']:,.0f}" if s.get("price") else ""


def offer_mailto(s):
    number = f" {s['number']}" if s["number"] else ""
    subject = f"Offer: {s['name']} {s['grade_label']} (Cert {s['cert']})"
    asking = f"Asking: {fmt_price(s)}\n" if fmt_price(s) else ""
    body = (
        "Hi Nick,\n\nI'd like to make an offer on this graded card:\n\n"
        f"Card: {s['name']}{number}\n"
        f"Set: {s['set']}\n"
        f"Grade: {s['grade_label']}\n"
        f"Cert #: {s['cert']}\n"
        f"{asking}\n"
        "My offer: $"
    )
    return ("mailto:nick@sakekittycards.com?subject="
            + urllib.parse.quote(subject) + "&body=" + urllib.parse.quote(body))


def grade_class(s):
    if s["grade"] == "10":
        return "grade-10"
    if s["grade"] == "9":
        return "grade-9"
    return "grade-8"


def card_html(s):
    e = html.escape
    mailto = e(offer_mailto(s), quote=True)
    price_line = (
        f'\n            <p class="slab-price">{fmt_price(s)}</p>' if fmt_price(s) else ""
    )
    number = f" · #{e(s['number'])}" if s["number"] else ""
    jp = '<span class="slab-lang">JP</span>' if s["lang"] == "JP" else ""
    alt = e(f"{s['name']} {s['grade_label']} — {s['set']}")
    return f"""        <article class="single-card" id="cert-{s['cert']}">
          <a class="single-imgwrap slab-imgwrap" href="{mailto}" aria-label="Make an offer on {e(s['name'])} {e(s['grade_label'])}">
            <img src="assets/graded/{s['cert']}.jpg" alt="{alt}" loading="lazy" decoding="async" width="{IMG_W}" height="{IMG_H}" />
          </a>{jp}
          <div class="single-meta">
            <h3 class="single-name">{e(s['name'])}</h3>
            <p class="single-sub">{e(s['set'])}{number}</p>
            <div class="single-tags">
              <span class="slab-grade {grade_class(s)}">{e(s['grade_label'])}</span>
            </div>{price_line}
            <p class="slab-cert">Cert #{s['cert']} · <a href="{verify_url(s)}" target="_blank" rel="noopener">Verify</a> · <a href="assets/graded/{s['cert']}b.jpg" target="_blank" rel="noopener">Back</a></p>
            <a class="btn make-offer" href="{mailto}">Make Offer</a>
          </div>
        </article>"""


SITE = "https://sakekittycards.com"


def slab_schema(slabs):
    """ItemList of Product nodes, one per slab, baked in at build time.

    Static on purpose: this page is already fully server-rendered, so there is
    no reason to inject schema with JS the way product.html has to.

    No `price` is emitted while MAKE_OFFER_ONLY is on. These genuinely have no
    fixed ask, and inventing one to satisfy Google's merchant-listing fields
    would be inaccurate structured data. Availability + seller + url are valid
    on their own; flip MAKE_OFFER_ONLY off and the offers pick up real prices.
    """
    items = []
    for i, s in enumerate(slabs, start=1):
        number = f" #{s['number']}" if s["number"] else ""
        lang = " (Japanese)" if s["lang"] == "JP" else ""
        url = f"{SITE}/graded.html#cert-{s['cert']}"
        offer = {
            "@type": "Offer",
            "url": url,
            "availability": "https://schema.org/InStock",
            "itemCondition": "https://schema.org/UsedCondition",
            "seller": {"@id": f"{SITE}/#organization"},
        }
        if not MAKE_OFFER_ONLY and s.get("price"):
            offer["price"] = f"{s['price']:.2f}"
            offer["priceCurrency"] = "USD"
        product = {
            "@type": "Product",
            "name": f"{s['name']}{number} — {s['grade_label']}",
            "description": (
                f"{s['name']}{number} from {s['set']}{lang}, graded "
                f"{s['grade_label']} by {s['grader']}. "
                f"Certificate #{s['cert']}, independently verifiable at "
                f"{verify_url(s)}."
            ),
            "image": f"{SITE}/assets/graded/{s['cert']}.jpg",
            "sku": s["cert"],
            "category": "Collectible Trading Cards",
            "brand": {"@type": "Brand", "name": "Pokémon"},
            "itemCondition": "https://schema.org/UsedCondition",
            "url": url,
            "offers": offer,
        }
        items.append({"@type": "ListItem", "position": i, "item": product})

    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": "Sake Kitty Cards — Graded Vault",
            "numberOfItems": len(items),
            "itemListElement": items,
        },
        # Compact: this block is machine-generated and machine-read, so
        # pretty-printing it just adds ~11KB of whitespace to a commerce page.
        separators=(",", ":"),
        ensure_ascii=False,
    )


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="icon" type="image/png" href="logo-icon.png" />
  <link rel="apple-touch-icon" href="logo-touch.png" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="theme-color" content="#06060a" />
  <meta name="color-scheme" content="dark" />
  <title>Graded Vault — Make an Offer | Sake Kitty Cards</title>
  <meta name="description" content="Our graded slab showcase — PSA and CGC certified Pokémon cards, vintage to modern chase. No fixed price: send your best offer and we'll reply." />

  <link rel="canonical" href="https://sakekittycards.com/graded.html" />
  <meta property="og:title" content="Graded Vault — Make an Offer | Sake Kitty Cards" />
  <meta property="og:description" content="PSA and CGC certified Pokémon slabs, vintage to modern chase. No fixed price — send your best offer and we'll reply." />
  <meta property="og:site_name" content="Sake Kitty Cards" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:image" content="https://sakekittycards.com/og-image.png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:url" content="https://sakekittycards.com/graded.html" />
  <meta property="og:type" content="website" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Graded Vault — Make an Offer | Sake Kitty Cards" />
  <meta name="twitter:description" content="PSA and CGC certified Pokémon slabs, vintage to modern chase. No fixed price — send your best offer and we'll reply." />
  <meta name="twitter:image" content="https://sakekittycards.com/og-image.png" />
  <!-- Breadcrumb structured data -->
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [
      { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://sakekittycards.com/" },
      { "@type": "ListItem", "position": 2, "name": "Graded Vault", "item": "https://sakekittycards.com/graded.html" }
    ]
  }
  </script>

  <!-- Product/ItemList structured data — generated by scripts/build_graded_page.py
       from assets/graded-slabs.json. Do NOT hand-edit: this file is fully
       regenerated on every build and edits here are silently discarded. -->
  <script type="application/ld+json">
__SLAB_SCHEMA__
  </script>

  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bangers&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="style.css?v=178" />
  <style>
    .page-singles .page-hero { padding-bottom: 18px; }
    .page-singles .page-hero h1 { font-size: clamp(38px, 7vw, 60px); }
    .singles-tagline {
      font-family: 'Inter', sans-serif; font-weight: 700;
      font-size: clamp(13px, 2.2vw, 16px); letter-spacing: 0.05em;
      text-transform: uppercase; margin-top: 12px;
    }
    .singles-tagline .ok { color: var(--cyan); }
    .singles-tagline .pop { color: var(--pink); }
    .singles-note {
      display: flex; gap: 10px; align-items: flex-start;
      max-width: 760px; margin: 16px auto 0;
      padding: 12px 16px; border-radius: 12px;
      background: rgba(0,212,255,0.08); border: 1px solid rgba(0,212,255,0.28);
      color: rgba(255,255,255,0.88); font-size: 14px; line-height: 1.55; text-align: left;
    }
    .singles-note strong { color: var(--cyan); }

    .singles-grid {
      display: grid; gap: 18px;
      grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    }
    .single-card {
      position: relative;
      display: flex; flex-direction: column;
      background: var(--panel, #12121c); border: 1px solid var(--border);
      border-radius: 14px; overflow: hidden;
      transition: transform .2s ease, border-color .2s, box-shadow .2s;
    }
    .single-card:hover {
      transform: translateY(-4px); border-color: rgba(255,106,0,0.55);
      box-shadow: 0 14px 34px rgba(255,106,0,0.18), 0 0 26px rgba(123,47,255,0.12);
    }
    .single-imgwrap {
      position: relative; display: block; padding: 14px 14px 6px;
      background: radial-gradient(circle at 50% 35%, rgba(123,47,255,0.14), transparent 70%);
    }
    .single-imgwrap img {
      display: block; width: 100%; height: auto; border-radius: 8px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.45);
    }
    .slab-lang {
      position: absolute; top: 20px; right: 20px;
      font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 6px;
      background: #4a2540; color: #ffb6e6;
    }
    .single-meta { padding: 4px 14px 14px; display: flex; flex-direction: column; gap: 7px; flex: 1; }
    .single-name { font-size: 16px; font-weight: 700; margin: 0; line-height: 1.2; }
    .single-sub { font-size: 12.5px; color: var(--dim); margin: 0; }
    .single-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 2px; }
    .slab-grade {
      font-size: 11px; font-weight: 800; padding: 3px 8px; border-radius: 6px;
      letter-spacing: .02em;
    }
    .slab-grade.grade-10 { background: rgba(255,210,122,0.18); color: #ffd27a; }
    .slab-grade.grade-9 { background: rgba(0,212,255,0.16); color: #67d8ff; }
    .slab-grade.grade-8 { background: rgba(255,184,77,0.16); color: #ffce85; }
    .slab-price {
      font-size: 21px; font-weight: 800; margin: 2px 0 0;
      color: var(--orange); letter-spacing: -0.2px;
      filter: drop-shadow(0 0 8px rgba(255,106,0,0.20));
    }
    .slab-cert { font-size: 11.5px; color: var(--dim); margin: 0; }
    .slab-cert a { color: var(--cyan); text-decoration: none; }
    .slab-cert a:hover { text-decoration: underline; }
    .make-offer { margin-top: auto; width: 100%; justify-content: center; }
    .singles-tcg {
      max-width: 720px; margin: 30px auto 0; padding: 22px 24px; border-radius: 16px;
      text-align: center;
      background: linear-gradient(135deg, rgba(255,106,0,0.12), rgba(123,47,255,0.12));
      border: 1px solid rgba(255,106,0,0.35);
    }
    .singles-tcg h2 { margin: 0 0 6px; font-size: clamp(20px,4vw,26px); }
    .singles-tcg p { margin: 0 0 14px; color: var(--muted); font-size: 14px; line-height: 1.5; }
    @media (max-width: 560px) {
      .singles-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
      .single-name { font-size: 15px; }
    }
  </style>
</head>
<body class="page-singles">
  <a class="skip-link" href="#main">Skip to main content</a>
  <div class="bg-blob bg-blob-1"></div>
  <div class="bg-blob bg-blob-2"></div>

  <nav class="site-nav" id="siteNav">
    <div class="nav-inner">
      <a href="index.html" class="nav-logo">
        <img width="32" height="32" src="logo-sm.webp" alt="Sake Kitty Cards" />
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
            <li><a href="graded.html">Graded Vault</a></li>
            <li><a href="shop.html?cat=merch">Apparel &amp; Merch</a></li>
          </ul>
        </li>
        <li><a href="trade-in.html">Sell / Trade</a></li>
        <li><a href="grading-prep.html">Grading Prep</a></li>
        <li><a href="events.html">Events</a></li>
        <li><a href="team.html">Our Team</a></li>
        <li><a href="about.html">About</a></li>
        <li><a href="reviews.html">Reviews</a></li>
        <li><a href="watch.html">Watch</a></li>
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
      <h1>Graded Vault</h1>
      <p>Our slab showcase — __COUNT__ PSA &amp; CGC certified cards, from Shadowless Base Set to the newest Special Illustration Rares. Every photo is the exact slab you'll receive. No fixed prices — send your best offer and we'll reply.</p>
      <p class="singles-tagline">Certified <span class="ok">Slabs</span> · Best <span class="pop">Offer</span></p>
      <div class="singles-note">
        <span aria-hidden="true">📍</span>
        <span>We're local vendors — these also sell in person and at shows, so availability can change. <strong>We'll confirm a slab is still here before anything's finalized.</strong> Tap any card to send an offer straight to Nick.</span>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="singles-grid">
__CARDS__
      </div>
      <div class="singles-tcg">
        <h2>Have slabs to sell?</h2>
        <p>We buy graded cards too — up to 90% cash or 100% trade credit. Look up your card and get an instant quote on our Sell / Trade page.</p>
        <a class="btn btn-lg" href="trade-in.html">Sell or trade your slabs →</a>
      </div>
    </div>
  </main>

  <footer class="site-footer">
    <div class="footer-inner">
      <div class="footer-brand">
        <img width="44" height="44" src="logo-sm.webp" alt="Sake Kitty Cards" class="footer-logo-img" />
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
        <a href="graded.html">Graded Vault</a>
        <a href="events.html">Events</a>
        <a href="team.html">Our Team</a>
        <a href="trade-in.html">Sell / Trade</a>
        <a href="grading-prep.html">Grading Prep</a>
        <a href="reviews.html">Reviews</a>
        <a href="watch.html">Watch</a>
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

  <script src="main.js?v=161" defer></script>
</body>
</html>
"""


def main():
    slabs = json.loads(DATA.read_text(encoding="utf-8"))
    # 2026-08-14: graded-slabs.json is now rebuilt from TCGenie acct-54 stock, which includes slabs newer than
    # the 8/5 shoot. A slab with no photo (neither exported to assets/graded nor available in PROCESSED_DIR)
    # must NOT render a broken card on the live page — hold it off until it's photographed (task #50).
    have, held = [], []
    for s in slabs:
        if (IMG_DIR / f"{s['cert']}.jpg").exists() or (PROCESSED_DIR / f"{s['cert']}F.jpg").exists():
            have.append(s)
        else:
            held.append(s)
    export_images(have)
    cards = "\n".join(card_html(s) for s in have)
    page = (PAGE.replace("__COUNT__", str(len(have)))
                .replace("__CARDS__", cards)
                .replace("__SLAB_SCHEMA__", slab_schema(have)))
    OUT.write_text(page, encoding="utf-8")
    print(f"graded.html written with {len(have)} slabs (+Product schema); images in {IMG_DIR}")
    if held:
        print(f"HELD OFF the page ({len(held)} — no photo yet):")
        for s in held:
            print(f"  ! {s['cert']}  {s.get('name','')}")


if __name__ == "__main__":
    main()
