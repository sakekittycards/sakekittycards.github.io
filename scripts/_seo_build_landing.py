# -*- coding: utf-8 -*-
"""Emit the five commercial landing pages (2026-09-01 SEO overhaul).

Each page owns ONE distinct search intent that no existing URL served:
  sell-pokemon-collection    whole-collection / estate / inherited lots
  pokemon-card-appraisal     "what are my cards worth" valuation intent
  sell-graded-pokemon-cards  PSA / CGC / BGS slab selling
  pokemon-card-buyer-florida local geo intent (ONE honest page, not city doorways)
  wholesale-pokemon          B2B lead gen (no prices — wholesale.html stays hidden)

Every number on these pages is copied from live code, not remembered:
  rate ladder  -> trade-in.html  const RATES
  condition    -> trade-in.html  const COND_MULT
  service fees -> grading-prep.html service cards
  shipping     -> main.js SK_SHIP_FLAT_FEE / SK_FREE_SHIP_THRESHOLD
  show venues  -> assets/events-data.js
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _seo_page_kit import emit, breadcrumbs, faq_schema, faq_html, SITE

FORCE = '--force' in sys.argv

# ── shared fragments ──────────────────────────────────────────────────────────

RATE_TABLE = '''      <div class="card" style="overflow-x:auto;border-radius:var(--r)">
        <table class="buylist-table">
          <caption class="visually-hidden">Sake Kitty Cards buy rates by item value, as a percentage of current market value</caption>
          <thead>
            <tr><th scope="col">Market value of the item</th><th scope="col">Cash</th><th scope="col">Store credit</th></tr>
          </thead>
          <tbody>
            <tr><td>Singles under $100</td><td class="buy-price">70%</td><td class="credit-price">80%</td></tr>
            <tr><td>Singles $100 &ndash; $499</td><td class="buy-price">80%</td><td class="credit-price">90%</td></tr>
            <tr><td>Singles $500 &ndash; $999</td><td class="buy-price">85%</td><td class="credit-price">95%</td></tr>
            <tr><td>Anything $1,000 and up</td><td class="buy-price">90%</td><td class="credit-price">100%</td></tr>
            <tr><td>Sealed under $100</td><td class="buy-price">80%</td><td class="credit-price">90%</td></tr>
            <tr><td>Sealed $100 &ndash; $499</td><td class="buy-price">83%</td><td class="credit-price">93%</td></tr>
            <tr><td>Sealed $500 &ndash; $999</td><td class="buy-price">86%</td><td class="credit-price">96%</td></tr>
            <tr><td>Unsorted bulk, by weight</td><td class="buy-price">$1.50 / lb</td><td class="credit-price">$2.50 / lb</td></tr>
          </tbody>
        </table>
      </div>
      <p style="font-size:13.5px;color:var(--dim);margin-top:14px;max-width:740px">
        Rates are a percentage of the card&rsquo;s current market value, then adjusted for condition
        (Near Mint 100% &middot; Lightly Played 85% &middot; Moderately Played 70% &middot; Heavily Played 50% &middot; Damaged 30%).
        Graded slabs use the singles ladder from $100 up; we don&rsquo;t buy graded cards worth under $100,
        because the grading fee already inside the slab costs more than the card.
        Bulk by weight is English Pok&eacute;mon only &mdash; no basic energy, no jumbo or oversized cards.
        The full 13-category bulk table lives on the
        <a href="trade-in.html">Sell / Trade page</a>.
      </p>'''

PAY_BLOCK = '''        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">How you get paid</h3>
          <p>Cash offers go out by <strong>Venmo, PayPal, or Cash App</strong> &mdash; your pick &mdash; the same day we
          finish going through the lot. We don&rsquo;t use Zelle. If you take store credit instead, it&rsquo;s issued as a
          Square gift card with a unique code you can spend at our booth or online, and credit always pays more
          than cash on the same cards.</p>
        </div>'''

MAILIN_BLOCK = '''        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">Mail in from anywhere</h3>
          <p>You do not have to be in Florida. Most of what we buy arrives by mail from all over the country.
          We review every submission and confirm the offer <em>before</em> you ship anything, so nothing leaves
          your hands on a guess. Our <a href="shipping.html">packing and shipping guide</a> walks through exactly
          how to pack cards so they arrive in the condition they left in &mdash; that guide is the difference between
          a Near Mint quote and a Lightly Played one.</p>
        </div>'''


def cta(primary_text, primary_href, secondary_text, secondary_href, heading, sub):
    return '''    <div class="section" style="padding-top:0">
      <div class="card" style="padding:40px 36px;text-align:center;background:linear-gradient(135deg,rgba(255,106,0,.07),rgba(123,47,255,.07));border-color:rgba(255,106,0,.18)">
        <h2 style="font-family:'Bangers',cursive;font-size:clamp(24px,4vw,34px);letter-spacing:.04em;padding-bottom:8px">%s</h2>
        <p style="max-width:560px;margin:0 auto 24px;color:var(--muted)">%s</p>
        <div style="display:flex;gap:14px;flex-wrap:wrap;justify-content:center">
          <a href="%s" class="btn btn-primary btn-lg">%s</a>
          <a href="%s" class="btn btn-outline btn-lg">%s</a>
        </div>
      </div>
    </div>''' % (heading, sub, primary_href, primary_text, secondary_href, secondary_text)


def service_schema(name, desc, sid, url, extra=''):
    return '''  {
    "@context": "https://schema.org",
    "@type": "Service",
    "@id": "%s#service",
    "name": "%s",
    "serviceType": "%s",
    "description": "%s",
    "url": "%s",
    "provider": { "@type": "Organization", "@id": "https://sakekittycards.com/#organization", "name": "Sake Kitty Cards", "url": "https://sakekittycards.com/" },
    "areaServed": [
      { "@type": "Country", "name": "United States" },
      { "@type": "State", "name": "Florida" }
    ],
    "availableChannel": [
      { "@type": "ServiceChannel", "serviceUrl": "%s", "name": "Online submission" },
      { "@type": "ServiceChannel", "serviceUrl": "https://sakekittycards.com/events.html", "name": "In person at Florida card shows" }
    ]%s
  }''' % (url, name, sid, desc, url, url, extra)


# ── 1. SELL A COLLECTION ──────────────────────────────────────────────────────

C_FAQ = [
    ("Do I have to list every card to get an offer on a collection?",
     "No. That is the whole reason this page exists. For a shoebox, a longbox, a binder run, or an "
     "inherited collection, send photos and a rough description and we will work from that. The "
     "card-by-card lookup tool on the Sell / Trade page is there for people who want to itemize a "
     "short list of specific cards &mdash; it is not the right tool for 4,000 commons."),
    ("How big does a collection have to be?",
     "There is no minimum. We buy single binders and we buy garage-full estate collections. What "
     "changes with size is the process: small lots we can quote from photos, large lots usually get "
     "sorted in person or after they arrive."),
    ("What if the collection has non-Pok&eacute;mon cards mixed in?",
     "Tell us what is in there. Pok&eacute;mon is what we specialize in and what we pay the most for. "
     "We will be straight with you about anything outside that rather than quietly valuing it at zero."),
    ("Do you buy collections you have to travel for?",
     "For large Florida collections, yes &mdash; we already drive the state every month for shows, so "
     "we can often work a pickup into a route we are already running. Ask."),
    ("What happens if I do not like the offer?",
     "Nothing. The offer is free and there is no obligation. If you mailed cards in and you turn the "
     "offer down, we ship them back to you &mdash; we are not going to hold your collection hostage over "
     "a number you did not agree to."),
    ("How do you decide what a collection is worth?",
     "Every card with real value is priced off recent sold data for that exact card, set, number and "
     "printing &mdash; not off the highest asking price someone has posted. Then the published rate ladder "
     "applies. Bulk is priced by category or by weight. We show our work if you ask."),
]

emit('sell-pokemon-collection.html', force=FORCE,
     title='Sell Your Pok&eacute;mon Card Collection &mdash; Cash Offers, Any Size | Sake Kitty Cards'.replace('&eacute;', 'é').replace('&mdash;', '—'),
     desc='Selling a whole Pokemon collection? We buy binders, shoeboxes, estates and bulk — mail-in from anywhere or in person in Florida. Free offer, no obligation, published buy rates.',
     ogtype='website',
     schema=[
         breadcrumbs([('Home', ''), ('Sell / Trade', 'trade-in.html'), ('Sell a Collection', 'sell-pokemon-collection.html')]),
         service_schema(
             'Pokemon collection buying',
             'Sake Kitty Cards buys complete Pokemon card collections of any size — binders, boxes, bulk, sealed and graded — by mail from anywhere in the US or in person at Florida card shows. Free written offer with no obligation.',
             'Collectibles buying service',
             SITE + 'sell-pokemon-collection.html'),
         faq_schema(C_FAQ),
     ],
     body='''    <div class="page-hero">
      <h1>Sell Your Pok&eacute;mon Card Collection</h1>
      <p>Binders, shoeboxes, closet finds, estates and everything in between. Mail it in from anywhere in
      the country or hand it over at one of our Florida booths. You get a free, itemized offer with no
      obligation &mdash; and if you say no, you get your cards back.</p>
      <div style="display:flex;gap:14px;flex-wrap:wrap;justify-content:center;margin-top:28px">
        <a href="contact.html" class="btn btn-primary btn-lg">Get an offer on your collection</a>
        <a href="trade-in.html" class="btn btn-outline btn-lg">I have a short list of specific cards</a>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">Who this is for</h2>
        <p class="section-sub">If you are looking at a pile of cards and thinking &ldquo;I am not typing all of these
        into a form,&rdquo; you are in the right place.</p>
      </div>
      <div class="values-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px">
        <div class="card" style="padding:24px 26px">
          <h3 style="font-family:'Bangers',cursive;font-size:21px;letter-spacing:.04em;padding-bottom:6px">You are getting out of the hobby</h3>
          <p>Years of binders, a few slabs, some sealed you never opened. One offer, one payment, done.</p>
        </div>
        <div class="card" style="padding:24px 26px">
          <h3 style="font-family:'Bangers',cursive;font-size:21px;letter-spacing:.04em;padding-bottom:6px">You inherited a collection</h3>
          <p>You did not build it and you do not know what is in it. We will tell you what is actually
          valuable before we tell you what we will pay.</p>
        </div>
        <div class="card" style="padding:24px 26px">
          <h3 style="font-family:'Bangers',cursive;font-size:21px;letter-spacing:.04em;padding-bottom:6px">You are thinning out</h3>
          <p>Keep the cards you love, sell the rest. Take store credit and it cycles straight back into
          something you actually want.</p>
        </div>
        <div class="card" style="padding:24px 26px">
          <h3 style="font-family:'Bangers',cursive;font-size:21px;letter-spacing:.04em;padding-bottom:6px">You have bulk, not chase cards</h3>
          <p>Thousands of commons and uncommons still have a number. We buy unsorted English Pok&eacute;mon bulk
          by the pound so you are not sorting it yourself.</p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">How a collection offer works</h2>
        <p class="section-sub">Five steps, and you can stop at any of them.</p>
      </div>
      <div class="prep-steps">
        <div class="prep-step">
          <div class="prep-step-num">1</div>
          <h3>Tell us what you have</h3>
          <p>Photos of the binder pages, the box, the slabs, the sealed. Rough counts are fine. The more we
          can see, the tighter the first number is.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">2</div>
          <h3>We give you a range</h3>
          <p>Before anything ships, you get an honest range and an explanation of what is driving it. If the
          range does not interest you, the conversation ends there and it cost you nothing.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">3</div>
          <h3>Ship it or hand it over</h3>
          <p>Mail it in following the <a href="shipping.html">packing guide</a>, or bring it to a booth. Florida
          collections large enough to justify it can sometimes be picked up.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">4</div>
          <h3>We go through it card by card</h3>
          <p>Everything with real value gets looked up against recent sold data for that exact printing and
          condition. Bulk gets weighed or counted by category.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">5</div>
          <h3>Firm offer, then payment</h3>
          <p>You get the itemized breakdown and the final number. Accept and you are paid the same day.
          Decline and the collection ships back to you.</p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">What we pay</h2>
        <p class="section-sub">Published, not negotiated behind a curtain. These are the same rates the
        card-by-card quote tool uses.</p>
      </div>
''' + RATE_TABLE + '''
    </div>

    <div class="section" style="padding-top:0">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px">
''' + PAY_BLOCK + '''
''' + MAILIN_BLOCK + '''
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header" style="text-align:center">
        <h2 class="section-title" style="display:inline-block">Collection selling questions</h2>
        <div class="divider" style="margin:10px auto 0"></div>
      </div>
''' + faq_html(C_FAQ) + '''
    </div>

    <div class="section" style="padding-top:0">
      <div class="card" style="padding:30px 32px">
        <h2 style="font-family:'Bangers',cursive;font-size:26px;letter-spacing:.04em;padding-bottom:8px">Before you sell, read these</h2>
        <p style="margin-bottom:16px">Two guides worth ten minutes if this is your first time selling a collection:</p>
        <ul style="line-height:2;padding-left:20px;color:var(--muted)">
          <li><a href="guide-sell-pokemon-collection.html">How to sell a Pok&eacute;mon collection without getting lowballed</a> &mdash; the four mistakes that cost sellers the most money.</li>
          <li><a href="guide-what-dealers-pay.html">What percentage of market value do Pok&eacute;mon dealers pay?</a> &mdash; why nobody pays 100%, and what a fair number actually looks like.</li>
          <li><a href="pokemon-card-appraisal.html">What are my Pok&eacute;mon cards worth?</a> &mdash; how to value a collection yourself before you talk to anyone.</li>
        </ul>
      </div>
    </div>

''' + cta('Start a collection offer', 'contact.html', 'See the full rate matrix', 'trade-in.html',
          'Ready when you are', 'Send photos and a rough description. We reply within 24 hours, and the offer is free either way.'))


# ── 2. APPRAISAL ──────────────────────────────────────────────────────────────

A_FAQ = [
    ("Do you charge for an appraisal?",
     "No. Quotes and valuations are free and carry no obligation to sell. We would rather you know what "
     "you have and decide for yourself than guess."),
    ("What is the difference between what a card is listed for and what it is worth?",
     "Anyone can list a card for any price. A listing is an asking price with no buyer attached. What "
     "the card is worth is what comparable copies actually sold for recently, in the same condition and "
     "the same printing. Those two numbers can be off by multiples on thin-volume cards. We price off "
     "sold data, and so should you."),
    ("Does condition really change the value that much?",
     "Yes. On the same card, our condition multipliers run Near Mint 100%, Lightly Played 85%, "
     "Moderately Played 70%, Heavily Played 50% and Damaged 30%. On a $400 card that spread is $280."),
    ("Can you tell me what a card is worth if I get it graded?",
     "That is a different question, and it is the one the grading-prep screening answers. A PSA 10 and a "
     "PSA 9 of the same modern card typically differ by around 3x; on vintage the gap is wider. But you "
     "do not get to pick the grade &mdash; that is why screening the card first matters."),
    ("Is a formal written appraisal for insurance or probate something you do?",
     "We give detailed, itemized valuations, and people have used them for estate and insurance purposes. "
     "We are card dealers, not a certified appraisal firm, so if you need a document that satisfies a "
     "specific legal or insurance requirement, check what that body will accept first."),
    ("What information should I send?",
     "Clear, straight-on photos with the card fully in frame, the set symbol and the card number legible, "
     "and a shot of the back and the corners for anything valuable. For a whole collection, photos of "
     "binder pages and rough counts are enough to start."),
]

emit('pokemon-card-appraisal.html', force=FORCE,
     title='What Are My Pokémon Cards Worth? Free Appraisal | Sake Kitty Cards',
     desc='Find out what your Pokemon cards are actually worth. Free valuation from a working card dealer — sold-comp pricing, condition explained, and a live lookup tool you can use yourself.',
     schema=[
         breadcrumbs([('Home', ''), ('Sell / Trade', 'trade-in.html'), ('Card Appraisal', 'pokemon-card-appraisal.html')]),
         service_schema(
             'Pokemon card and collection appraisal',
             'Free valuation of Pokemon cards, graded slabs, sealed product and whole collections, priced against recent sold comparables rather than asking prices.',
             'Collectibles appraisal',
             SITE + 'pokemon-card-appraisal.html'),
         faq_schema(A_FAQ),
     ],
     body='''    <div class="page-hero">
      <h1>What Are Your Pok&eacute;mon Cards Worth?</h1>
      <p>The honest answer is: what someone recently paid for the same card, in the same condition, in the
      same printing. Not what it is listed for. Here is how to find that number &mdash; with a free tool you can
      use right now, and a human who will check your work.</p>
      <div style="display:flex;gap:14px;flex-wrap:wrap;justify-content:center;margin-top:28px">
        <a href="trade-in.html" class="btn btn-primary btn-lg">Look up your cards free</a>
        <a href="contact.html" class="btn btn-outline btn-lg">Have us value a collection</a>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">Listed price is not value</h2>
        <p class="section-sub">This is the single biggest thing people get wrong, and it is the reason
        collections get mis-valued in both directions.</p>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px">
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">The asking-price trap</h3>
          <p>Search a card and you will see listings ranging from reasonable to absurd. A listing is one
          person&rsquo;s hope. On a card that only sells a few times a month, one optimistic listing can sit at
          the top of the results for a year and convince everyone the card is worth triple what it is.</p>
        </div>
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">What we actually use</h3>
          <p>Recent completed sales for the exact card &mdash; right set, right card number, right printing,
          right condition. When a card is thin on volume we widen the window rather than lean on a single
          outlier sale. Graded slabs are priced against sold comps for that specific grade.</p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">The four things that move the number</h2>
      </div>
      <div class="prep-steps">
        <div class="prep-step">
          <div class="prep-step-num">1</div>
          <h3>The exact printing</h3>
          <p>First Edition, Shadowless, Unlimited, reverse holo, promo stamp, a different set with the same
          art &mdash; these are different cards with different values, even though they look almost identical.
          Getting the printing wrong is the most common valuation error we see.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">2</div>
          <h3>Condition</h3>
          <p>Near Mint 100% &middot; Lightly Played 85% &middot; Moderately Played 70% &middot; Heavily Played 50% &middot; Damaged 30%.
          Whitening on the back edges and soft corners are what usually drop a card a tier.
          Our <a href="guide-grade-your-own-cards.html">self-grading guide</a> walks through how to read your own cards.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">3</div>
          <h3>Graded vs raw</h3>
          <p>A slab prices off its grade, not off the raw card. A PSA 10 of a modern card typically trades
          around 3&times; its PSA 9; on vintage the multiple is wider still. A raw card is worth the raw price
          until somebody has actually graded it.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">4</div>
          <h3>Language and region</h3>
          <p>Japanese, Chinese and English versions of the same Pok&eacute;mon are separate markets with separate
          prices. Japanese print quality means Japanese cards often grade higher, which changes the math on
          whether to submit them.</p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="card" style="padding:36px 34px">
        <h2 style="font-family:'Bangers',cursive;font-size:clamp(24px,4vw,32px);letter-spacing:.04em;padding-bottom:8px">Appraise them yourself, free</h2>
        <p style="max-width:720px;margin-bottom:18px">Our Sell / Trade lookup is a working valuation tool, not
        a lead form. Search a card by name, set or number &mdash; English, Japanese, sealed or graded &mdash; pick the
        condition, and it shows you the current market value it found before it shows you our offer. Use it
        purely to price your collection and never contact us; that is a completely legitimate use of it.</p>
        <div style="display:flex;gap:14px;flex-wrap:wrap">
          <a href="trade-in.html" class="btn btn-primary">Open the lookup tool</a>
          <a href="grading-prep.html" class="btn btn-outline">Value it as a graded card</a>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">When you want a human to look</h2>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px">
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">Send it to us</h3>
          <p>Photos and a rough description are enough to start. We reply within 24 hours with what we see,
          what it is worth, and what we would pay &mdash; three separate numbers, deliberately. There is no fee
          and no obligation.</p>
          <p style="margin-top:14px"><a href="contact.html" class="btn btn-primary btn-sm">Send photos for a valuation</a></p>
        </div>
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">Worth a second opinion</h3>
          <p>Vintage WOTC-era cards, anything you suspect is First Edition or Shadowless, error and
          miscut cards, sealed product where the seal condition matters, and anything you are not certain
          is genuine. Those are the cases where a photo to a dealer saves real money.</p>
          <p style="margin-top:14px"><a href="guide-spot-fake-pokemon-cards.html" class="btn btn-outline btn-sm">How to spot a fake</a></p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header" style="text-align:center">
        <h2 class="section-title" style="display:inline-block">Appraisal questions</h2>
        <div class="divider" style="margin:10px auto 0"></div>
      </div>
''' + faq_html(A_FAQ) + '''
    </div>

''' + cta('Get a free valuation', 'contact.html', 'Sell a whole collection', 'sell-pokemon-collection.html',
          'Know before you sell', 'Free, no obligation, and we will tell you if you should keep it instead.'))


# ── 3. SELL GRADED ────────────────────────────────────────────────────────────

G_FAQ = [
    ("Which grading companies do you buy?",
     "PSA, CGC, BGS and SGC. PSA and CGC slabs are the most liquid and generally get the strongest "
     "offers, simply because they have the deepest sold-comp history to price against."),
    ("Why won't you buy graded cards under $100?",
     "Because the slab already has $25 to $30 of grading fees baked into it that we cannot recover. On a "
     "card worth $60, the economics do not work for either of us. Under $100 you will do better selling "
     "the slab directly, or trading it in as part of a larger lot."),
    ("What do you pay for slabs?",
     "The same ladder as singles from $100 up: 80% cash or 90% credit from $100 to $499, 85% or 95% from "
     "$500 to $999, and 90% cash or 100% credit at $1,000 and above."),
    ("Do you need the cert number?",
     "Yes, and it is genuinely useful to you. The cert number tells us the exact card, set, printing and "
     "grade with zero ambiguity, so the quote comes back faster and does not move when the slab arrives."),
    ("Do you buy cards graded by companies other than the big four?",
     "Usually not at slab prices. Off-brand slabs tend to trade at or near raw value, so it is normally "
     "better to quote the card as a raw single. Ask and we will tell you honestly which way it goes."),
    ("How should I ship slabs?",
     "Slab in a sleeve or bubble wrap, taped so it cannot slide, in a rigid box &mdash; never a bubble mailer "
     "on its own. Cracked cases are the most common shipping damage we see. The packing guide has the full "
     "method, and we cover insurance guidance there too."),
]

emit('sell-graded-pokemon-cards.html', force=FORCE,
     title='Sell Graded Pokémon Cards — PSA, CGC & BGS Slabs | Sake Kitty Cards',
     desc='We buy graded Pokemon slabs — PSA, CGC, BGS and SGC — from $100 up, at 80–90% cash or up to 100% in trade credit. Cert-number quotes, mail-in nationwide.',
     schema=[
         breadcrumbs([('Home', ''), ('Sell / Trade', 'trade-in.html'), ('Sell Graded Slabs', 'sell-graded-pokemon-cards.html')]),
         service_schema(
             'Graded Pokemon slab buying',
             'Sake Kitty Cards buys graded Pokemon cards certified by PSA, CGC, BGS and SGC, valued at $100 and above, priced against recent sold comparables for that exact grade.',
             'Collectibles buying service',
             SITE + 'sell-graded-pokemon-cards.html'),
         faq_schema(G_FAQ),
     ],
     body='''    <div class="page-hero">
      <h1>Sell Your Graded Pok&eacute;mon Cards</h1>
      <p>PSA, CGC, BGS and SGC slabs from $100 up. Quote from the cert number in minutes, priced against
      recent sold comps for that exact grade &mdash; up to 90% cash or 100% in trade credit.</p>
      <div style="display:flex;gap:14px;flex-wrap:wrap;justify-content:center;margin-top:28px">
        <a href="trade-in.html" class="btn btn-primary btn-lg">Quote your slabs</a>
        <a href="graded.html" class="btn btn-outline btn-lg">See what we&rsquo;re holding</a>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">What we pay for slabs</h2>
        <p class="section-sub">Graded cards use the singles ladder from $100 up. No haggling, no
        &ldquo;let me talk to my partner&rdquo; theater.</p>
      </div>
      <div class="card" style="overflow-x:auto;border-radius:var(--r)">
        <table class="buylist-table">
          <caption class="visually-hidden">Buy rates for graded Pokemon slabs by slab value</caption>
          <thead>
            <tr><th scope="col">Slab value</th><th scope="col">Cash</th><th scope="col">Store credit</th></tr>
          </thead>
          <tbody>
            <tr><td>Under $100</td><td class="buy-price">Not accepted</td><td class="credit-price">Not accepted</td></tr>
            <tr><td>$100 &ndash; $499</td><td class="buy-price">80%</td><td class="credit-price">90%</td></tr>
            <tr><td>$500 &ndash; $999</td><td class="buy-price">85%</td><td class="credit-price">95%</td></tr>
            <tr><td>$1,000 and up</td><td class="buy-price">90%</td><td class="credit-price">100%</td></tr>
          </tbody>
        </table>
      </div>
      <p style="font-size:13.5px;color:var(--dim);margin-top:14px;max-width:740px">
        Under $100 is a deliberate policy, not a lowball. A slab carries $25&ndash;$30 of grading fees we
        cannot recover, so on a cheap slab there is no version of the deal that is good for you.
        Bring low-value slabs to a booth as part of a larger lot instead, or sell them direct.</p>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">How slab pricing actually works</h2>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px">
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">The grade is the product</h3>
          <p>A PSA 10 and a PSA 9 of the same card are two different assets. On modern cards the 10 usually
          trades around 3&times; the 9; on vintage the multiple is bigger again. We price the grade you have,
          not the grade the card looks like it deserves.</p>
        </div>
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">Sold comps, newest first</h3>
          <p>We work from the most recent completed sales of that card in that grade and let old sales fall
          out of the window. A slab that sold for $900 eighteen months ago tells you almost nothing about
          today.</p>
        </div>
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">Cert number, no ambiguity</h3>
          <p>Give us the cert and there is nothing left to argue about &mdash; card, set, printing, grade, all
          confirmed. That is why cert-quoted slabs get a firm number rather than a range, and why the number
          does not move when the slab lands.</p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">Getting slabs to us safely</h2>
        <p class="section-sub">Cracked cases are the single most common shipping damage we see, and a cracked
        case can cost you the grade.</p>
      </div>
      <div class="card" style="padding:30px 32px">
        <ul style="line-height:2.05;padding-left:20px;color:var(--muted)">
          <li>Sleeve or bubble-wrap each slab individually so cases cannot rub against each other.</li>
          <li>Tape the wrapped slab so it cannot slide inside the box &mdash; movement is what breaks cases.</li>
          <li>Use a <strong>rigid box</strong>, not a bubble mailer, for anything graded.</li>
          <li>Insure it. Our full method, including the packing tiers by order size, is in the
              <a href="shipping.html">packing and shipping guide</a>.</li>
          <li>Wait for us to confirm the offer before you ship. We review every submission first.</li>
        </ul>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px">
''' + PAY_BLOCK + '''
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">Raw cards you were going to grade</h3>
          <p>If you have not submitted yet, run the numbers first. Grading costs roughly $30 a card all-in
          before you know the grade, and a card that comes back a 9 instead of a 10 can be worth less than
          the raw card plus the fee. Our <a href="grading-prep.html">grading prep screening</a> tells you which
          cards are worth submitting, and the <a href="guide-should-you-grade.html">break-even guide</a> shows the
          math.</p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header" style="text-align:center">
        <h2 class="section-title" style="display:inline-block">Graded selling questions</h2>
        <div class="divider" style="margin:10px auto 0"></div>
      </div>
''' + faq_html(G_FAQ) + '''
    </div>

''' + cta('Quote your slabs now', 'trade-in.html', 'Sell the whole collection instead', 'sell-pokemon-collection.html',
          'Have the cert numbers handy?', 'Drop them into the graded form and you will have a firm number back fast.'))


# ── 4. FLORIDA ────────────────────────────────────────────────────────────────

F_FAQ = [
    ("Do you have a storefront I can walk into?",
     "No, and we would rather say that plainly than imply otherwise. Sake Kitty Cards is a booth-and-mail "
     "operation: we vend card shows across Florida most weekends, we ship nationwide, and we run online. "
     "The events page lists exactly where we will be and when."),
    ("Can I sell cards to you at a show?",
     "Yes, that is most of what we do at a booth. Bring the cards, we look through them there, and you "
     "walk away paid the same day. For large collections it helps to message ahead so we bring enough "
     "cash and set aside the time."),
    ("Which part of Florida are you actually in?",
     "Both coasts, genuinely. Gulf side we are regularly in Fort Myers, North Fort Myers and Naples. "
     "Treasure Coast we are at the Stuart show most months. Atlantic side we are at Delray Beach, Palm "
     "Beach Gardens, Pompano Beach and Fort Lauderdale. We also do larger national conventions."),
    ("I am in Florida but nowhere near a show. What then?",
     "Mail it in, exactly like an out-of-state seller would. Same rates, same process, same-day payment. "
     "Being local is convenient, not required."),
    ("Do you buy at shows you are not vending?",
     "Sometimes. If you are bringing something significant to a Florida show we are attending, message "
     "ahead and we will find you."),
    ("What should I bring to a booth to sell?",
     "The cards, sleeved or in a binder so we can go through them without damaging anything, and an idea "
     "of what you want for them. Cert numbers for slabs speed things up. If it is a big lot, message "
     "first so we are ready for it."),
]

emit('pokemon-card-buyer-florida.html', force=FORCE,
     title='Pokémon Card Buyer in Florida — Sell at Our Booth or by Mail | Sake Kitty Cards',
     desc='Selling Pokemon cards in Florida? We vend shows on both coasts — Fort Myers, Naples, Stuart, Delray Beach, Palm Beach Gardens, Pompano Beach and Fort Lauderdale — and buy by mail nationwide.',
     schema=[
         breadcrumbs([('Home', ''), ('Sell / Trade', 'trade-in.html'), ('Selling in Florida', 'pokemon-card-buyer-florida.html')]),
         service_schema(
             'Pokemon card buying in Florida',
             'Sake Kitty Cards buys Pokemon cards, sealed product and graded slabs in person at card shows across Florida on both the Gulf and Atlantic coasts, and by mail from anywhere in the United States.',
             'Collectibles buying service',
             SITE + 'pokemon-card-buyer-florida.html',
             extra=''',
    "areaServed": [
      { "@type": "State", "name": "Florida" },
      { "@type": "City", "name": "Fort Myers", "containedInPlace": { "@type": "State", "name": "Florida" } },
      { "@type": "City", "name": "North Fort Myers", "containedInPlace": { "@type": "State", "name": "Florida" } },
      { "@type": "City", "name": "Naples", "containedInPlace": { "@type": "State", "name": "Florida" } },
      { "@type": "City", "name": "Stuart", "containedInPlace": { "@type": "State", "name": "Florida" } },
      { "@type": "City", "name": "Delray Beach", "containedInPlace": { "@type": "State", "name": "Florida" } },
      { "@type": "City", "name": "Palm Beach Gardens", "containedInPlace": { "@type": "State", "name": "Florida" } },
      { "@type": "City", "name": "Pompano Beach", "containedInPlace": { "@type": "State", "name": "Florida" } },
      { "@type": "City", "name": "Fort Lauderdale", "containedInPlace": { "@type": "State", "name": "Florida" } },
      { "@type": "Country", "name": "United States" }
    ]'''),
         faq_schema(F_FAQ),
     ],
     body='''    <div class="page-hero">
      <h1>Selling Pok&eacute;mon Cards in Florida</h1>
      <p>We are a traveling card-show vendor, not a strip-mall shop &mdash; which means we are probably closer
      to you than a store is. Gulf coast and Atlantic coast, most weekends, cash at the table. And if you are
      nowhere near a show, mail it in on exactly the same terms.</p>
      <div style="display:flex;gap:14px;flex-wrap:wrap;justify-content:center;margin-top:28px">
        <a href="events.html" class="btn btn-primary btn-lg">See where we&rsquo;ll be next</a>
        <a href="trade-in.html" class="btn btn-outline btn-lg">Get a quote before you come</a>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">Where we actually set up</h2>
        <p class="section-sub">These are real, recurring booths &mdash; not a list of cities we picked off a map.
        Dates rotate; the <a href="events.html">events calendar</a> is always current.</p>
      </div>
      <div class="card" style="overflow-x:auto;border-radius:var(--r)">
        <table class="buylist-table">
          <caption class="visually-hidden">Florida card shows Sake Kitty Cards regularly vends</caption>
          <thead>
            <tr><th scope="col">Area</th><th scope="col">Show</th><th scope="col">Venue</th></tr>
          </thead>
          <tbody>
            <tr><td>Southwest Florida</td><td>Florida Regional Card Expo</td><td>Caloosa Sound Convention Center, Fort Myers</td></tr>
            <tr><td>Southwest Florida</td><td>SWFL Super Card Show</td><td>Lee Civic Center, North Fort Myers</td></tr>
            <tr><td>Southwest Florida</td><td>Pokekon</td><td>DoubleTree at Bell Tower Shops, Fort Myers</td></tr>
            <tr><td>Southwest Florida</td><td>Naples Card Show</td><td>The White Rose, Naples</td></tr>
            <tr><td>Treasure Coast</td><td>Stuart Card Show</td><td>The Flagler, Stuart</td></tr>
            <tr><td>Palm Beach County</td><td>PGA Card Show</td><td>Palm Beach Gardens</td></tr>
            <tr><td>Palm Beach County</td><td>Delray Card Show</td><td>Delray Beach</td></tr>
            <tr><td>Broward County</td><td>Cardichu</td><td>D1, Pompano Beach</td></tr>
            <tr><td>Broward County</td><td>Card Party &amp; The Hobby Card Show</td><td>Broward County Convention Center, Fort Lauderdale</td></tr>
          </tbody>
        </table>
      </div>
      <p style="font-size:13.5px;color:var(--dim);margin-top:14px;max-width:740px">
        We also vend larger multi-state conventions &mdash; Collect-A-Con, Tampa, Orlando and Lakeland shows among
        them. If you are traveling to a big Florida show, check the calendar before you assume we are not there.</p>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">Selling at a booth vs. mailing it in</h2>
        <p class="section-sub">Both get you the same published rates. They suit different situations.</p>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px">
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">At the booth</h3>
          <p>Fastest route: you hand the cards over, we go through them in front of you, you get paid before
          you leave. Best for anything where you want to see the process, and for lots big enough that you
          would rather not put them in the post at all. Message ahead for large collections so we bring
          enough cash and clear the time.</p>
        </div>
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">By mail</h3>
          <p>Best when there is no show near you, or the timing does not work. Quote first, ship second &mdash;
          we confirm the offer before anything leaves your house. Follow the
          <a href="shipping.html">packing guide</a> and payment goes out the day we finish the lot.
          We buy from all fifty states, not just Florida.</p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">Why sell to a local vendor at all?</h2>
      </div>
      <div class="card" style="padding:30px 32px">
        <p style="margin-bottom:14px">Selling card by card on a marketplace will, on paper, beat a dealer offer.
        It should &mdash; you are doing the work. What that route actually costs you is roughly 13% in
        marketplace fees, the postage and packing on every single sale, the time to list and photograph
        everything, and the risk on every claim and return. On a 900-card collection that is weeks of
        evenings.</p>
        <p style="margin-bottom:14px">A dealer offer is one transaction, one payment, zero fees, zero
        shipping on your side, and no returns. Our rate ladder is published so you can do that comparison
        honestly rather than guessing at it. If the answer for your particular collection is &ldquo;sell it
        yourself,&rdquo; we will tell you that too.</p>
        <p>The specific advantage of a local vendor over a mail-in national buyer is simple: you can put the
        cards on the table, watch them being valued, ask why, and take cash the same day. Nobody is holding
        your collection three states away while you wait for a revised offer.</p>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header" style="text-align:center">
        <h2 class="section-title" style="display:inline-block">Local selling questions</h2>
        <div class="divider" style="margin:10px auto 0"></div>
      </div>
''' + faq_html(F_FAQ) + '''
    </div>

''' + cta('Check the show calendar', 'events.html', 'Quote it before you drive', 'trade-in.html',
          'Find us in person', 'Booths on both coasts, most weekends. Bring the cards, leave with cash.'))


# ── 5. WHOLESALE ──────────────────────────────────────────────────────────────

W_FAQ = [
    ("What is the minimum order?",
     "$1,500 before shipping. That is a real floor, not a starting point for negotiation &mdash; below it the "
     "case-break and handling economics do not work."),
    ("Who is this for?",
     "Card shops, show vendors, breakers, online sellers and anyone buying sealed to resell rather than to "
     "open. It is a business-to-business price list, not a retail one."),
    ("Do you publish wholesale prices on the site?",
     "No. The current list goes out by email on request so it can stay accurate to the day &mdash; sealed cost "
     "moves constantly and a page of stale numbers helps nobody. Ask and you will get the live list."),
    ("What do you carry?",
     "English, Japanese and Chinese sealed Pokemon. Japanese is priced by the box; Chinese is priced by the "
     "case. Availability changes with each allocation, so the list you receive is what is genuinely in hand "
     "or confirmed inbound."),
    ("Can I mix regions in one order to hit the minimum?",
     "Yes. The $1,500 minimum is on the total order, not per line or per region."),
    ("How do payment and shipping work on wholesale?",
     "Both are agreed per order &mdash; freight on cases is very different from a few boxes, and we would rather "
     "quote it properly than bake a guess into the price. Tell us where it is going and we will price it."),
]

emit('wholesale-pokemon.html', force=FORCE,
     title='Pokémon Wholesale for Shops & Vendors — Sealed by the Case | Sake Kitty Cards',
     desc='Wholesale sealed Pokemon for card shops, breakers and show vendors. English, Japanese by the box and Chinese by the case. $1,500 minimum — request the current price list.',
     schema=[
         breadcrumbs([('Home', ''), ('Shop', 'shop.html'), ('Wholesale', 'wholesale-pokemon.html')]),
         service_schema(
             'Pokemon sealed wholesale distribution',
             'Business-to-business wholesale supply of sealed Pokemon trading card product — English, Japanese by the box and Chinese by the case — to card shops, breakers and show vendors, with a $1,500 order minimum.',
             'Wholesale distribution',
             SITE + 'wholesale-pokemon.html'),
         faq_schema(W_FAQ),
     ],
     body='''    <div class="page-hero">
      <h1>Pok&eacute;mon Wholesale for Shops, Vendors &amp; Breakers</h1>
      <p>Sealed English, Japanese and Chinese Pok&eacute;mon at trade pricing &mdash; Japanese by the box, Chinese by
      the case. $1,500 minimum. The current list goes out by email so the numbers are accurate the day you
      get them.</p>
      <div style="display:flex;gap:14px;flex-wrap:wrap;justify-content:center;margin-top:28px">
        <a href="mailto:nick@sakekittycards.com?subject=Wholesale%20price%20list%20request" class="btn btn-primary btn-lg">Request the current price list</a>
        <a href="contact.html" class="btn btn-outline btn-lg">Talk to us first</a>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">What we supply</h2>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px">
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">Japanese sealed</h3>
          <p>Priced by the box. Japanese product is the backbone of most breaker and singles operations right
          now &mdash; higher pull consistency, better print quality, and the grading upside that comes with it.</p>
        </div>
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">Chinese sealed</h3>
          <p>Priced by the case. A market most US shops still have no supply line into, which is exactly why
          it is worth carrying. Case quantities, direct allocation.</p>
        </div>
        <div class="card" style="padding:26px 28px">
          <h3 style="font-family:'Bangers',cursive;font-size:22px;letter-spacing:.04em;padding-bottom:6px">English sealed</h3>
          <p>Boxes, ETBs, special collections and Pok&eacute;mon Center exclusives as allocation allows. Availability
          moves fast; the live list tells you what is actually in hand.</p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header">
        <h2 class="section-title">How it works</h2>
      </div>
      <div class="prep-steps">
        <div class="prep-step">
          <div class="prep-step-num">1</div>
          <h3>Ask for the list</h3>
          <p>Email us with your shop or business name and roughly what you are looking to move. We send the
          current list with live pricing and real availability.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">2</div>
          <h3>Build the order</h3>
          <p>Mix regions and SKUs however you like &mdash; the $1,500 minimum applies to the order total, not to
          each line.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">3</div>
          <h3>We quote freight</h3>
          <p>Shipping is quoted per order against the actual weight and destination. Cases and boxes are
          wildly different to ship and we would rather price it than average it.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">4</div>
          <h3>Confirm and go</h3>
          <p>You approve the final total, we invoice, it ships. Repeat allocations get first refusal on the
          next drop.</p>
        </div>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="card" style="padding:32px 34px">
        <h2 style="font-family:'Bangers',cursive;font-size:clamp(24px,4vw,32px);letter-spacing:.04em;padding-bottom:8px">Why buy from us</h2>
        <p style="margin-bottom:14px">We are a vending operation first. We buy sealed to sell at our own
        booths across Florida every month, which means we are on the same allocations as our customers and we
        know what actually moves at a table versus what sits.</p>
        <p style="margin-bottom:14px">It also means we do not have to inflate a wholesale list to survive.
        Our sealed pricing runs at a thin, deliberate margin over cost, and anything where that margin would
        push the price close to what a shop could just buy it for at retail gets dropped from the list
        entirely rather than padded out to look like a bigger catalog.</p>
        <p>If you want to see the retail side of the same operation first, the
        <a href="shop.html">shop</a> and the <a href="events.html">show calendar</a> are both public.</p>
      </div>
    </div>

    <div class="section" style="padding-top:0">
      <div class="section-header" style="text-align:center">
        <h2 class="section-title" style="display:inline-block">Wholesale questions</h2>
        <div class="divider" style="margin:10px auto 0"></div>
      </div>
''' + faq_html(W_FAQ) + '''
    </div>

''' + cta('Email for the price list', 'mailto:nick@sakekittycards.com?subject=Wholesale%20price%20list%20request',
          'General contact form', 'contact.html',
          'Get the current list', 'Tell us your shop name and what you move. We reply within 24 hours.'))

print('done.')
