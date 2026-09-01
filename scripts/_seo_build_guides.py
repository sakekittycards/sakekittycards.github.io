# -*- coding: utf-8 -*-
"""Emit the six evergreen guides (2026-09-01 SEO overhaul).

resources.html used to cram five topics into ~1,000 words on one URL, so it
ranked for none of them. Each topic now gets a page deep enough to actually
answer the question, and resources.html becomes the hub that links to them.

Chosen because Sake Kitty has genuine first-party evidence on each, not because
the keyword had volume. The PSA 10:9 multiple table in guide-should-you-grade
is our own measurement across 58,152 graded price pairs — nobody else publishes
it, which is the whole point.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _seo_page_kit import emit, breadcrumbs, faq_schema, faq_html, SITE

FORCE = '--force' in sys.argv
PUB = '2026-09-01'


def article(headline, desc, slug, section):
    return '''  {
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": "%s",
    "description": "%s",
    "articleSection": "%s",
    "inLanguage": "en-US",
    "datePublished": "%s",
    "dateModified": "%s",
    "mainEntityOfPage": { "@type": "WebPage", "@id": "%s%s" },
    "image": "https://sakekittycards.com/og-image.png",
    "author": { "@type": "Organization", "@id": "https://sakekittycards.com/#organization", "name": "Sake Kitty Cards", "url": "https://sakekittycards.com/" },
    "publisher": { "@type": "Organization", "@id": "https://sakekittycards.com/#organization", "name": "Sake Kitty Cards", "logo": { "@type": "ImageObject", "url": "https://sakekittycards.com/logo-touch.png" } }
  }''' % (headline, desc, section, PUB, PUB, SITE, slug)


def crumbs(name, slug):
    return breadcrumbs([('Home', ''), ('Guides', 'resources.html'), (name, slug)])


def prose(*paras):
    return '\n'.join('      <p>%s</p>' % p for p in paras)


def sec(title, inner, sub=None):
    head = '        <h2 class="section-title">%s</h2>' % title
    if sub:
        head += '\n        <p class="section-sub">%s</p>' % sub
    return ('    <div class="section" style="padding-top:0">\n'
            '      <div class="section-header">\n%s\n      </div>\n%s\n    </div>' % (head, inner))


def nextsteps(items, heading='Where to go from here'):
    lis = '\n'.join('          <li>%s</li>' % i for i in items)
    return '''    <div class="section" style="padding-top:0">
      <div class="card" style="padding:30px 32px;background:linear-gradient(135deg,rgba(255,106,0,.07),rgba(123,47,255,.07));border-color:rgba(255,106,0,.18)">
        <h2 style="font-family:'Bangers',cursive;font-size:26px;letter-spacing:.04em;padding-bottom:8px">%s</h2>
        <ul style="line-height:2.05;padding-left:20px;color:var(--muted)">
%s
        </ul>
      </div>
    </div>''' % (heading, lis)


def hero(h1, lede):
    return '''    <div class="page-hero">
      <h1>%s</h1>
      <p>%s</p>
    </div>''' % (h1, lede)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Selling a collection without getting lowballed
# ══════════════════════════════════════════════════════════════════════════════
Q1 = [
    ("Should I sort my collection before selling it?",
     "Pull out anything obviously valuable &mdash; holos, full arts, vintage, anything already in a slab &mdash; so "
     "those get priced individually instead of disappearing into a bulk count. Beyond that, do not spend a "
     "weekend sorting commons by set. It will not change the bulk rate."),
    ("Is it worth selling the good cards separately and bulking the rest?",
     "Almost always, yes, and any honest buyer will tell you the same thing. The valuable cards should be "
     "priced card by card; the rest is a bulk transaction. A buyer who wants to price the whole thing as one "
     "undifferentiated lot is usually hoping you have not noticed what is in it."),
    ("How many offers should I get?",
     "At least two, and tell each buyer you are getting others. That is not rude, it is normal. What you are "
     "checking is not just the top number but whether the buyer will show you how they got there."),
    ("Does it matter whether I take cash or store credit?",
     "It does if you are staying in the hobby. Credit pays roughly ten percentage points more than cash on "
     "the same cards, which is real money if you were going to spend it on cards anyway. If you are leaving "
     "the hobby, take the cash."),
]

emit('guide-sell-pokemon-collection.html', force=FORCE,
     title='How to Sell a Pokémon Card Collection Without Getting Lowballed',
     desc='A working card dealer explains how collection offers are built, the four mistakes that cost sellers the most money, and how to tell a fair offer from a bad one.',
     ogtype='article',
     schema=[crumbs('Selling a Collection', 'guide-sell-pokemon-collection.html'),
             article('How to Sell a Pokemon Card Collection Without Getting Lowballed',
                     'How Pokemon collection offers are actually built, and the four mistakes that cost sellers the most money.',
                     'guide-sell-pokemon-collection.html', 'Selling guides'),
             faq_schema(Q1)],
     body=hero('How to Sell a Pok&eacute;mon Collection Without Getting Lowballed',
               'We buy collections for a living, so treat this as a dealer explaining exactly what happens on '
               'our side of the table &mdash; including the parts that are not in your favor.') + '\n\n' +
     sec('First: nobody is going to pay you market value',
         prose(
             'Every offer you get will be below what the cards would sell for individually online. That is not '
             'a trick, it is the entire business model. A buyer is paying you today, in one payment, with no '
             'fees, no listing work, no packing, no shipping and no returns &mdash; and then carrying the risk and '
             'the time of selling those cards one at a time over the following months.',
             'So the question is never &ldquo;is this offer below market?&rdquo; It always is. The question is '
             '<strong>how far below, and can the buyer show you the math?</strong> That is the only thing worth '
             'evaluating. We publish our rate ladder in full on the '
             '<a href="trade-in.html">Sell / Trade page</a> for exactly that reason, and '
             '<a href="guide-what-dealers-pay.html">this guide breaks down what those percentages mean</a> '
             'against the alternative of selling it yourself.')) + '\n\n' +
     sec('The four mistakes that cost the most money',
         '''      <div class="prep-steps">
        <div class="prep-step">
          <div class="prep-step-num">1</div>
          <h3>Letting the good cards get bulked</h3>
          <p>The single most expensive mistake. If a $180 alt art goes into a 3,000-card bulk count, you were
          paid about four cents for it. Pull every holo, full art, alt art, vintage card and slab out before
          anyone quotes you, even if you are not sure it is worth anything. Being wrong about a card costs you
          nothing; missing one costs you the card.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">2</div>
          <h3>Pricing off listings instead of sales</h3>
          <p>Searching a card and seeing a $600 listing does not mean the card is worth $600. It means one
          person is asking $600 and nobody has paid it. On low-volume cards, a single fantasy listing can sit
          at the top of the results for a year. Filter to completed sales. Every serious buyer prices off sold
          data, so if you price off listings you will think every offer is an insult.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">3</div>
          <h3>Ignoring condition</h3>
          <p>Sellers habitually grade their own cards a full tier too generously. A card with edge whitening on
          the back and slightly soft corners is not Near Mint. On our ladder that difference is 15% of the
          card&rsquo;s value at Lightly Played and 30% at Moderately Played. Read your cards honestly before you set
          expectations &mdash; <a href="guide-grade-your-own-cards.html">here is how</a>.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">4</div>
          <h3>Shipping badly</h3>
          <p>Cards that arrive dinged get quoted as dinged cards. A loose stack in a bubble mailer will move
          in transit and the corners will take it. This is entirely avoidable and it is pure lost money.
          The <a href="shipping.html">packing guide</a> covers the method by lot size.</p>
        </div>
      </div>''') + '\n\n' +
     sec('What a real offer looks like',
         prose(
             'A legitimate collection offer should be <strong>itemized</strong>. You should be able to see which '
             'cards were valued individually, what each was valued at, what condition was assigned, what the '
             'bulk counts were and what rate was applied to each. If a buyer hands you one number for 2,000 '
             'cards and will not break it down, that is the warning sign &mdash; not the number itself.',
             'You should also be told, unprompted, if something in the collection is worth more than the buyer '
             'wants to pay for it. We would rather tell someone &ldquo;this one card is worth more than our '
             'offer on the whole box, sell it yourself&rdquo; than buy it quietly and have them find out later. '
             'That is not generosity, it is that we work the same Florida shows every month and word travels.',
             'And the offer should be <strong>free and reversible</strong>. Nothing should ship before you have '
             'agreed a number, and if you turn down a final offer on cards you already mailed, they should come '
             'back to you. Ask about that specifically before you send anything to anyone.')) + '\n\n' +
     sec('Cash or store credit',
         prose(
             'Most buyers, us included, pay more in credit than in cash &mdash; on our ladder the spread is about '
             'ten percentage points, and at the top tier credit reaches 100% of market value against 90% cash. '
             'The reason is simple: credit stays in the business.',
             'The decision is therefore not really about the percentage. It is about whether you were going to '
             'spend that money on cards anyway. If you are consolidating a collection and plan to buy chase '
             'cards with the proceeds, credit is straightforwardly the better deal. If you are done with the '
             'hobby, take the cash and do not let a bigger number talk you into a currency you cannot spend.')) + '\n\n' +
     sec('Collection selling questions', faq_html(Q1)) + '\n\n' +
     nextsteps([
         '<a href="sell-pokemon-collection.html">Get an offer on your collection</a> &mdash; free, itemized, no obligation.',
         '<a href="guide-what-dealers-pay.html">What percentage of market do dealers actually pay?</a> &mdash; the numbers behind the ladder.',
         '<a href="pokemon-card-appraisal.html">Value your collection yourself first</a> &mdash; free lookup tool, no contact required.',
         '<a href="shipping.html">How to pack cards so they arrive Near Mint</a> &mdash; the difference between two condition tiers.',
     ]))


# ══════════════════════════════════════════════════════════════════════════════
# 2. Should you grade — the break-even math (carries the proprietary dataset)
# ══════════════════════════════════════════════════════════════════════════════
Q2 = [
    ("What does it cost to grade a Pokemon card?",
     "At PSA's entry-level tier the fee has recently sat around $25 per card, before shipping in both "
     "directions and before insurance. Budget roughly $30 per card all-in as a working floor, and check "
     "PSA's current published pricing before you submit, because grading fees change."),
    ("What raw value makes grading worth it?",
     "As a rough gate: modern cards need to be worth enough that a 10 covers the fee and beats the raw card, "
     "which in practice means a raw value in the low hundreds unless you are very confident of the grade. "
     "Vintage justifies grading at lower raw values because the PSA 10 multiple is larger."),
    ("How much more is a PSA 10 worth than a PSA 9?",
     "Across 58,152 Pokemon cards where both a Grade 9 and a PSA 10 price exist, the median ratio is 3.0x. "
     "Modern cards from 2020 onward cluster very tightly around 2.97x. Pre-2004 vintage runs a median 4.26x "
     "and a volume-weighted 5.37x, because the vintage distribution has a much fatter tail."),
    ("Is it worth grading a card I am not confident is a 10?",
     "Usually not, and this is where most money is lost. You are not buying a PSA 10, you are buying a "
     "lottery ticket on one. If the card comes back a 9 you have spent about $30 to end up with an asset "
     "worth roughly a third of what you were hoping for. Screening the card first is how you avoid paying "
     "that tuition repeatedly."),
    ("Does it matter which grading company I use?",
     "It matters to resale liquidity more than to accuracy. PSA slabs have the deepest sold-comp history for "
     "Pokemon, which makes them the easiest to price and sell. See our PSA vs CGC vs BGS comparison."),
]

emit('guide-should-you-grade.html', force=FORCE,
     title='Should You Grade Your Pokémon Card? The Break-Even Math',
     desc='The real numbers behind grading: what it costs, what a PSA 10 is actually worth versus a 9 (measured across 58,152 cards), and when submitting loses you money.',
     ogtype='article',
     schema=[crumbs('Should You Grade?', 'guide-should-you-grade.html'),
             article('Should You Grade Your Pokemon Card? The Break-Even Math',
                     'What grading costs, what a PSA 10 is worth versus a PSA 9 measured across 58,152 cards, and when submitting loses money.',
                     'guide-should-you-grade.html', 'Grading guides'),
             faq_schema(Q2)],
     body=hero('Should You Grade Your Pok&eacute;mon Card?',
               'Grading is an investment with a fee, a wait, and an uncertain outcome. Here is the arithmetic, '
               'including a number almost nobody publishes: what a PSA 10 is actually worth relative to a 9.') + '\n\n' +
     sec('The three numbers that decide it',
         prose(
             'Grading is worth it when the graded card is worth more than the raw card plus the fee, adjusted '
             'for the odds of getting the grade you are hoping for. That is the whole model. It needs three '
             'inputs: <strong>what the card is worth raw</strong>, <strong>what it is worth at each grade</strong>, '
             'and <strong>what it costs to find out</strong>.',
             'The cost is the easy one. PSA&rsquo;s entry tier has recently sat around $25 per card, and you are '
             'shipping in both directions with insurance. Call it about <strong>$30 per card all-in</strong> as a '
             'working floor. Grading fees change, so check PSA&rsquo;s current published pricing before you commit '
             'to a submission.',
             'The raw value you can look up in about twenty seconds with the '
             '<a href="trade-in.html">card lookup tool</a>. The hard input is the third one, and it is where '
             'most people guess.')) + '\n\n' +
     sec('What a PSA 10 is actually worth versus a PSA 9',
         '''      <p style="max-width:780px;margin-bottom:20px">You will see a lot of confident claims about this
      ratio online, most of them repeating a single unsourced figure. So we measured it. Taking every Pok&eacute;mon
      card where both a Grade 9 price and a PSA 10 price exist &mdash; <strong>58,152 matched pairs</strong> &mdash;
      here is the actual distribution of the PSA 10 to Grade 9 ratio.</p>
      <div class="card" style="overflow-x:auto;border-radius:var(--r)">
        <table class="buylist-table">
          <caption class="visually-hidden">Measured PSA 10 to Grade 9 price ratio for Pokemon cards, by segment</caption>
          <thead>
            <tr><th scope="col">Segment</th><th scope="col">Cards measured</th><th scope="col">Median ratio</th><th scope="col">Weighted by sales volume</th></tr>
          </thead>
          <tbody>
            <tr><td>All Pok&eacute;mon cards</td><td>58,152</td><td class="buy-price">3.00&times;</td><td class="credit-price">3.28&times;</td></tr>
            <tr><td>Modern (2020 onward)</td><td>20,126</td><td class="buy-price">2.97&times;</td><td class="credit-price">3.01&times;</td></tr>
            <tr><td>Vintage (pre-2004)</td><td>8,595</td><td class="buy-price">4.26&times;</td><td class="credit-price">5.37&times;</td></tr>
            <tr><td>Grade 9 worth $10 &ndash; $25</td><td>30,290</td><td class="buy-price">2.94&times;</td><td class="credit-price">3.01&times;</td></tr>
            <tr><td>Grade 9 worth $50 &ndash; $100</td><td>5,961</td><td class="buy-price">3.56&times;</td><td class="credit-price">3.97&times;</td></tr>
            <tr><td>Grade 9 worth $250+</td><td>3,660</td><td class="buy-price">3.86&times;</td><td class="credit-price">4.69&times;</td></tr>
          </tbody>
        </table>
      </div>
      <p style="font-size:13.5px;color:var(--dim);margin-top:14px;max-width:780px">
        Our own analysis, run August 2026 against per-grade Pok&eacute;mon pricing data licensed from PriceCharting.
        Every row is the median of the per-card ratio, not a ratio of medians. The volume-weighted column
        reweights by how often each card actually sells, which is closer to what you will personally encounter.
        Re-measured periodically; the market moves.</p>
      <p style="max-width:780px;margin-top:22px">Three things fall out of this that change how you should
      think about submitting:</p>
      <ul style="line-height:2.05;padding-left:20px;color:var(--muted);max-width:780px">
        <li><strong>Modern is remarkably predictable.</strong> The middle half of modern cards sits between
        2.6&times; and 3.1&times;. If you are grading a 2020-or-later card, 3&times; is a safe planning number.</li>
        <li><strong>Vintage is a different asset class.</strong> A median 4.26&times; and a volume-weighted
        5.37&times; means a vintage card justifies grading at a materially lower raw value than a modern one.</li>
        <li><strong>The commonly repeated 6.8&times; figure is a tail value, not an average.</strong> It exists,
        but it lives out at the extreme of the distribution. Planning a submission around it is how people end
        up disappointed.</li>
      </ul>''',
         sub='This is our own measurement, not a repeated internet figure. Here is the method and the data.') + '\n\n' +
     sec('Running the numbers on your card',
         '''      <div class="card" style="padding:32px 34px;max-width:840px">
        <p style="margin-bottom:16px">Take a modern card worth <strong>$120 raw</strong> in Near Mint. Assume the
        PSA 9 sells for $150 and, at the measured modern 3&times;, the PSA 10 sells for around $450.</p>
        <ul style="line-height:2.05;padding-left:20px;color:var(--muted);margin-bottom:16px">
          <li><strong>It comes back a 10:</strong> $450 minus $30 in fees = $420 against $120 raw. Excellent.</li>
          <li><strong>It comes back a 9:</strong> $150 minus $30 = $120 against $120 raw. You broke even and
          waited two months.</li>
          <li><strong>It comes back an 8:</strong> you are now underwater against simply selling it raw.</li>
        </ul>
        <p style="margin-bottom:16px">So the entire decision on that card rests on one question: <em>how likely
        is the 10?</em> Not &ldquo;is it a nice card&rdquo; &mdash; how likely is the 10. And the honest answer for
        most people, on most cards, is that they do not know, because the things that cost a 10 are centering
        measured to the millimeter, print lines, edge whitening only visible at an angle, and surface
        imperfections you cannot see without a light and a loupe.</p>
        <p>That is the entire reason pre-grading screening exists. Roughly $3 to $5 per card to find out which
        cards are worth a $30 gamble is a much better bet than $30 per card to find out the hard way.</p>
      </div>''') + '\n\n' +
     sec('When not to grade',
         '''      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px">
        <div class="card" style="padding:24px 26px">
          <h3 style="font-family:'Bangers',cursive;font-size:21px;letter-spacing:.04em;padding-bottom:6px">The card is cheap</h3>
          <p>A $30 fee on a $15 card cannot be rescued by any grade. Bulk-grading low-value cards is the most
          common way people lose money in this hobby.</p>
        </div>
        <div class="card" style="padding:24px 26px">
          <h3 style="font-family:'Bangers',cursive;font-size:21px;letter-spacing:.04em;padding-bottom:6px">You already know it has a flaw</h3>
          <p>A visible ding, a soft corner, obvious off-centering. You are paying $30 to have someone confirm
          what you can already see.</p>
        </div>
        <div class="card" style="padding:24px 26px">
          <h3 style="font-family:'Bangers',cursive;font-size:21px;letter-spacing:.04em;padding-bottom:6px">You need the money now</h3>
          <p>Grading turnaround is measured in weeks to months. If you are selling because you need the cash,
          the raw sale today beats a better price later.</p>
        </div>
        <div class="card" style="padding:24px 26px">
          <h3 style="font-family:'Bangers',cursive;font-size:21px;letter-spacing:.04em;padding-bottom:6px">It is sentimental</h3>
          <p>Grade it anyway if you want it protected and displayed. Just do not pretend that is an investment
          decision &mdash; it is a nice reason and it does not need a spreadsheet.</p>
        </div>
      </div>''') + '\n\n' +
     sec('Grading questions', faq_html(Q2)) + '\n\n' +
     nextsteps([
         '<a href="grading-prep.html">Have us screen your cards first</a> &mdash; $3 or $5 a card to find out which ones are worth submitting. Screening does not guarantee a specific grade. Final grades are determined by PSA, CGC, or Beckett.',
         '<a href="guide-psa-vs-cgc.html">PSA vs CGC vs BGS</a> &mdash; which grader to send it to, and why it matters to resale.',
         '<a href="guide-grade-your-own-cards.html">Read your own cards first</a> &mdash; the flaws that cost a 10.',
         '<a href="sell-graded-pokemon-cards.html">Already have slabs?</a> We buy PSA, CGC, BGS and SGC from $100 up.',
     ]))


# ══════════════════════════════════════════════════════════════════════════════
# 3. What dealers pay
# ══════════════════════════════════════════════════════════════════════════════
Q3 = [
    ("Why don't dealers pay full market value?",
     "Because a dealer is buying an asset they then have to sell, over months, at their own cost and risk. "
     "The gap between what they pay and what the card sells for covers marketplace fees, shipping, labor, "
     "the cards that turn out to be in worse condition than they looked, and the ones that never sell."),
    ("What is a fair percentage?",
     "It scales with the value of the card. On cheap singles, 60-70% of market is normal because the handling "
     "cost per card is nearly the same whether the card is worth $3 or $300. On four-figure cards the "
     "percentage should be much higher — we pay 90% cash and 100% in credit at $1,000 and up."),
    ("Would I make more selling the cards myself?",
     "On paper, yes, and honestly for some collections that is the right answer. What it costs you is roughly "
     "13% in marketplace fees, packing and postage on every sale, the hours to photograph and list, and the "
     "risk on returns and claims. On a handful of high-value cards that work pays. On 900 cards it usually "
     "does not."),
    ("Why is store credit worth more than cash?",
     "Because credit stays in the business. It costs us less to give you $100 of credit than $100 of cash, so "
     "we can afford to give you more of it. On our ladder credit runs about ten points above cash."),
    ("Do dealers pay more at a show than online?",
     "Not on our ladder — the rates are the same in person and by mail. What changes at a show is speed: you "
     "get looked at and paid the same day."),
]

emit('guide-what-dealers-pay.html', force=FORCE,
     title='What Percentage of Market Value Do Pokémon Dealers Pay?',
     desc='Why no dealer pays 100%, what a fair offer looks like at each value tier, and an honest comparison against selling the cards yourself — fees, time and risk included.',
     ogtype='article',
     schema=[crumbs('What Dealers Pay', 'guide-what-dealers-pay.html'),
             article('What Percentage of Market Value Do Pokemon Dealers Pay?',
                     'Why dealers pay below market, what a fair percentage looks like at each tier, and an honest comparison against selling yourself.',
                     'guide-what-dealers-pay.html', 'Selling guides'),
             faq_schema(Q3)],
     body=hero('What Percentage of Market Value Do Dealers Pay?',
               'Nobody pays 100%, and any buyer who says they do is quietly moving the number somewhere else. '
               'Here is what the percentages actually are, why they scale, and how to check whether an offer '
               'is fair.') + '\n\n' +
     sec('Why the number is never 100%',
         prose(
             'When a dealer buys your card they are not acquiring cash, they are acquiring inventory. That card '
             'now has to be graded for condition, priced, photographed, listed, stored, insured, packed and '
             'shipped &mdash; and it has to actually sell, which some cards do not, for months or ever.',
             'Against the eventual sale price there is roughly 13% in marketplace fees, the postage, the '
             'packing materials, the labor, and the losses on cards that turn out worse than they looked or '
             'that come back as a claim. The buy percentage has to absorb all of that before anything is left.',
             'What you are actually buying with that gap is <strong>certainty and time</strong>: one payment, '
             'today, with no fees on your side, no listings to write, no packages to mail, and no returns to '
             'handle. Whether that trade is worth it depends entirely on how much you value your own evenings.')) + '\n\n' +
     sec('Why the percentage scales with value',
         prose(
             'The handling cost of a card barely changes with its price. Grading the condition, photographing '
             'it, listing it, packing it and shipping it costs about the same whether the card is worth $4 or '
             '$400. On a $4 card that fixed cost is most of the margin; on a $400 card it is a rounding error.',
             'That is why any buy ladder that is honestly constructed has to rise steeply with value, and why '
             'a flat percentage across a whole collection is a warning sign. Here is ours, published in full:') +
         '''
      <div class="card" style="overflow-x:auto;border-radius:var(--r);margin-top:22px">
        <table class="buylist-table">
          <caption class="visually-hidden">Sake Kitty Cards buy rates as a percentage of market value</caption>
          <thead>
            <tr><th scope="col">Item value</th><th scope="col">Cash</th><th scope="col">Store credit</th></tr>
          </thead>
          <tbody>
            <tr><td>Singles under $100</td><td class="buy-price">70%</td><td class="credit-price">80%</td></tr>
            <tr><td>Singles $100 &ndash; $499</td><td class="buy-price">80%</td><td class="credit-price">90%</td></tr>
            <tr><td>Singles $500 &ndash; $999</td><td class="buy-price">85%</td><td class="credit-price">95%</td></tr>
            <tr><td>Anything $1,000 and up</td><td class="buy-price">90%</td><td class="credit-price">100%</td></tr>
            <tr><td>Sealed under $100</td><td class="buy-price">80%</td><td class="credit-price">90%</td></tr>
            <tr><td>Sealed $100 &ndash; $499</td><td class="buy-price">83%</td><td class="credit-price">93%</td></tr>
            <tr><td>Sealed $500 &ndash; $999</td><td class="buy-price">86%</td><td class="credit-price">96%</td></tr>
            <tr><td>Unsorted English bulk, by weight</td><td class="buy-price">$1.50 / lb</td><td class="credit-price">$2.50 / lb</td></tr>
          </tbody>
        </table>
      </div>
      <p style="font-size:13.5px;color:var(--dim);margin-top:14px;max-width:780px">
        Graded slabs follow the singles ladder from $100 up and are not accepted below $100. Sealed sits above
        singles at every tier because it moves faster and carries no condition risk. All rates are then adjusted
        for condition. The full 13-category bulk table is on the <a href="trade-in.html">Sell / Trade page</a>.</p>''',
         sub='The percentage should go up as the card gets more valuable. If it does not, ask why.') + '\n\n' +
     sec('Selling it yourself: the honest comparison',
         '''      <div class="card" style="padding:32px 34px;max-width:840px">
        <p style="margin-bottom:16px">Say you have a card with a $200 market value. Here is the same card, both ways.</p>
        <ul style="line-height:2.05;padding-left:20px;color:var(--muted);margin-bottom:16px">
          <li><strong>Sell it yourself:</strong> $200 sale, minus roughly 13% marketplace fees ($26), minus
          shipping and packing (call it $5), minus the time to photograph, list, answer questions, pack and
          post it. You net about <strong>$169</strong>, in whatever number of weeks it takes to sell, and you
          carry the return risk.</li>
          <li><strong>Sell it to us:</strong> $160 cash today at the $100&ndash;$499 tier, or <strong>$180 in
          credit</strong>. No fees, no shipping on your side, no listing, no returns.</li>
        </ul>
        <p style="margin-bottom:16px">On one $200 card the self-sale wins by about $9 and costs you an hour.
        Reasonable people go either way on that. Now multiply it: on 40 cards the self-sale wins by $360 and
        costs you forty listings, forty packages and several weeks of evenings. On 900 cards, most of them
        worth under $10 each, the fixed cost per sale swamps the difference entirely and selling them
        individually is simply not rational.</p>
        <p>That is the actual decision. It is not &ldquo;dealer versus market&rdquo; &mdash; it is <strong>how many
        cards, how valuable, and how much is your time worth</strong>. For a handful of expensive cards, sell
        them yourself; we will tell you so. For a collection, take the offer.</p>
      </div>''') + '\n\n' +
     sec('How to check an offer is fair',
         '''      <div class="card" style="padding:30px 32px;max-width:840px">
        <ul style="line-height:2.05;padding-left:20px;color:var(--muted)">
          <li><strong>Ask for the itemization.</strong> Which cards were priced individually, at what values,
          at what condition, at what rate. A buyer who will not show this is hiding something.</li>
          <li><strong>Check the values against sold data, not listings.</strong> Completed sales only. If the
          buyer&rsquo;s values match recent sold comps, the values are not the problem.</li>
          <li><strong>Check the percentage scales.</strong> One flat rate applied to a $5 card and a $900 card
          is either generous on one end or robbery on the other.</li>
          <li><strong>Check the condition calls.</strong> This is where offers get quietly reduced. If several
          cards you believe are Near Mint came back as Moderately Played, ask which flaw drove that.</li>
          <li><strong>Get a second offer.</strong> Always. And tell both buyers you are doing it.</li>
        </ul>
      </div>''') + '\n\n' +
     sec('Common questions', faq_html(Q3)) + '\n\n' +
     nextsteps([
         '<a href="trade-in.html">Price your cards against our published ladder</a> &mdash; free tool, shows the market value before it shows the offer.',
         '<a href="sell-pokemon-collection.html">Get an itemized offer on a whole collection</a>.',
         '<a href="guide-sell-pokemon-collection.html">How to sell a collection without getting lowballed</a>.',
         '<a href="pokemon-card-buyer-florida.html">Prefer to do it in person?</a> We vend shows on both Florida coasts.',
     ]))


# ══════════════════════════════════════════════════════════════════════════════
# 4. PSA vs CGC vs BGS
# ══════════════════════════════════════════════════════════════════════════════
Q4 = [
    ("Which grading company is best for Pokemon cards?",
     "For resale liquidity, PSA. It has the deepest sold-comp history for Pokemon, which means a PSA slab is "
     "the easiest to price and the easiest to sell. CGC is a strong second and is often better value on "
     "modern bulk submissions. BGS is worth it mainly for the subgrades and for a Black Label chase."),
    ("Does a CGC 10 sell for as much as a PSA 10?",
     "Generally no, on the same card. The gap varies by era and by card, but PSA slabs command a premium that "
     "reflects market familiarity more than grading accuracy. Factor that into the decision before you submit, "
     "not after."),
    ("What is the difference between a BGS 9.5 and a BGS 10?",
     "BGS grades four subgrades — centering, corners, edges and surface — and the overall grade is derived "
     "from them. A BGS 10 Pristine requires near-perfection across all four; the Black Label 10 requires a "
     "perfect 10 in every subgrade and is genuinely rare, which is why it carries such a premium."),
    ("Do the graders use the same scale?",
     "All three use a 1-to-10 scale, but they are not interchangeable. Historically CGC has been considered "
     "stricter on centering and surface for modern cards. Do not assume a card that would be a PSA 10 is "
     "automatically a CGC 10 or vice versa."),
    ("Can you submit cards on my behalf?",
     "Yes. Our grading prep service will prep and submit through PSA, CGC or Beckett for you, or prep the "
     "cards and return them so you can submit them yourself. Error cards can go to either PSA or CGC — your "
     "choice."),
]

emit('guide-psa-vs-cgc.html', force=FORCE,
     title='PSA vs CGC vs BGS for Pokémon Cards — Which Should You Use?',
     desc='An honest comparison of PSA, CGC and BGS for Pokemon: resale liquidity, cost, subgrades, turnaround, and which one actually makes sense for your card.',
     ogtype='article',
     schema=[crumbs('PSA vs CGC vs BGS', 'guide-psa-vs-cgc.html'),
             article('PSA vs CGC vs BGS for Pokemon Cards',
                     'Comparing PSA, CGC and BGS for Pokemon cards on resale liquidity, cost, subgrades and turnaround.',
                     'guide-psa-vs-cgc.html', 'Grading guides'),
             faq_schema(Q4)],
     body=hero('PSA vs CGC vs BGS for Pok&eacute;mon Cards',
               'They all put your card in a plastic case with a number on it. What differs is how easily you '
               'can sell that case afterwards &mdash; and for Pok&eacute;mon specifically, that difference is not '
               'small.') + '\n\n' +
     sec('The short version',
         '''      <div class="card" style="overflow-x:auto;border-radius:var(--r)">
        <table class="buylist-table">
          <caption class="visually-hidden">Comparison of PSA, CGC and BGS for Pokemon card grading</caption>
          <thead>
            <tr><th scope="col"></th><th scope="col">PSA</th><th scope="col">CGC</th><th scope="col">BGS</th></tr>
          </thead>
          <tbody>
            <tr><td><strong>Resale liquidity</strong></td><td>Deepest for Pok&eacute;mon</td><td>Strong and growing</td><td>Thinner on modern Pok&eacute;mon</td></tr>
            <tr><td><strong>Subgrades</strong></td><td>No</td><td>On request</td><td>Yes, always &mdash; the main draw</td></tr>
            <tr><td><strong>Top grade</strong></td><td>PSA 10 Gem Mint</td><td>CGC 10 Pristine / Perfect 10</td><td>BGS 10 Pristine, Black Label 10</td></tr>
            <tr><td><strong>Best for</strong></td><td>Anything you intend to sell</td><td>Modern bulk, value submissions</td><td>Cards you believe are flawless</td></tr>
            <tr><td><strong>Watch out for</strong></td><td>Cost and wait at busy times</td><td>Slab sells below the PSA equivalent</td><td>A 9.5 is common; the premium is in the 10</td></tr>
          </tbody>
        </table>
      </div>
      <p style="font-size:13.5px;color:var(--dim);margin-top:14px;max-width:780px">
        Fees and turnaround times change frequently at all three companies. Check their current published
        pricing before you build a submission around any of this.</p>''') + '\n\n' +
     sec('PSA',
         prose(
             'PSA is the default for Pok&eacute;mon and the reason is market history, not grading philosophy. More '
             'Pok&eacute;mon cards have been graded by PSA than by anyone else, which means when you go to sell a '
             'PSA slab there is a long record of comparable sales at that exact grade. Pricing it is easy, and '
             'so is selling it.',
             'That liquidity is a real, measurable premium. On the same card at the same nominal grade, a PSA '
             'slab typically clears higher than the alternatives. If your intention is to sell the card, that '
             'premium is usually worth more than any fee difference elsewhere.',
             'The trade-off is that PSA has no subgrades &mdash; you get one number and no explanation. A card '
             'that just missed a 10 and a card that comfortably made a 9 look identical in the slab.')) + '\n\n' +
     sec('CGC',
         prose(
             'CGC came to Pok&eacute;mon from comics and built a serious reputation quickly. The slab is excellent, '
             'the presentation is clean, and on modern submissions it is frequently better value per card, '
             'which matters a lot when you are submitting a stack rather than a single chase card.',
             'CGC also offers subgrades on request, so you can get the diagnostic detail without going all the '
             'way to BGS. Historically CGC has been regarded as tougher on centering and surface for modern '
             'cards, which is a point in favor of the grade meaning something &mdash; but do not assume a card '
             'that would be a PSA 10 walks into a CGC 10.',
             'The honest caveat is resale. On the same card, a CGC 10 generally does not clear what a PSA 10 '
             'does. That gap is closing, but it is real today, and it should be part of the math before you '
             'submit rather than a surprise afterwards.')) + '\n\n' +
     sec('BGS',
         prose(
             'BGS is the subgrade company. Every slab carries separate marks for centering, corners, edges and '
             'surface, and the overall grade derives from those four. For anyone who actually wants to '
             'understand their card &mdash; or to prove its quality to a buyer &mdash; that transparency is genuinely '
             'valuable.',
             'The famous prize is the Black Label 10: a perfect 10 in all four subgrades. It is rare enough '
             'that it commands an enormous premium over an ordinary BGS 10, which is exactly why people chase '
             'it. The corollary is that a BGS 9.5 is comparatively common, and the price gap between a 9.5 and '
             'a 10 is where all the money lives.',
             'For modern Pok&eacute;mon specifically, BGS resale is thinner than PSA. It is the right choice when '
             'you genuinely believe the card is flawless and you want the subgrades to prove it. It is the '
             'wrong choice as a default.')) + '\n\n' +
     sec('So which one?',
         '''      <div class="card" style="padding:32px 34px;max-width:840px">
        <ul style="line-height:2.05;padding-left:20px;color:var(--muted)">
          <li><strong>You intend to sell it:</strong> PSA. The liquidity premium is real and it usually
          outweighs everything else.</li>
          <li><strong>You are submitting a stack of modern cards:</strong> CGC is often the better economics,
          especially on cards where the difference between a 9 and a 10 is not life-changing.</li>
          <li><strong>You are convinced the card is perfect:</strong> BGS, and chase the Black Label. Just be
          honest with yourself about &ldquo;convinced.&rdquo;</li>
          <li><strong>You are keeping it forever:</strong> whichever slab you like looking at. This is a
          legitimate answer and nobody should talk you out of it.</li>
          <li><strong>You have no idea if the card will grade well:</strong> do not submit it yet. Screen it
          first &mdash; that is a $3 to $5 question, not a $30 one.</li>
        </ul>
      </div>''') + '\n\n' +
     sec('Grading company questions', faq_html(Q4)) + '\n\n' +
     nextsteps([
         '<a href="grading-prep.html">Grading prep and pre-screening</a> &mdash; we screen against PSA, CGC and Beckett standards, prep the cards, and submit on your behalf or hand them back. Screening does not guarantee a specific grade. Final grades are determined by PSA, CGC, or Beckett.',
         '<a href="guide-should-you-grade.html">Should you grade it at all?</a> &mdash; the break-even math, with our measured PSA 10 to 9 multiples.',
         '<a href="grading-terms.html">Grading prep terms</a> &mdash; fees, custody, and what happens at each stage.',
         '<a href="sell-graded-pokemon-cards.html">Selling slabs you already own</a> &mdash; PSA, CGC, BGS and SGC from $100 up.',
     ]))


# ══════════════════════════════════════════════════════════════════════════════
# 5. Grade your own cards
# ══════════════════════════════════════════════════════════════════════════════
Q5 = [
    ("What does Near Mint actually mean?",
     "A card that looks unplayed. Sharp corners, clean edges with no whitening visible when you tilt it, a "
     "clean surface with no scratches or print lines that catch the light, and centering that is not "
     "obviously off. Small factory imperfections are still Near Mint; handling wear is not."),
    ("How much does condition change what I get paid?",
     "A lot. Our multipliers are Near Mint 100%, Lightly Played 85%, Moderately Played 70%, Heavily Played "
     "50% and Damaged 30%. On a $400 card the spread between Near Mint and Heavily Played is $200."),
    ("Is a card with edge whitening still Near Mint?",
     "Usually not. Edge whitening on the back is the single most common reason a card people believe is Near "
     "Mint gets called Lightly Played. Tilt the card under a light and look along each edge — it shows up "
     "immediately at an angle when it is invisible flat on."),
    ("Does off-centering matter for raw sales?",
     "Much less than it does for grading. For a raw sale, centering only really matters when it is severe. "
     "For grading it is often the single thing standing between a 9 and a 10."),
    ("Should I clean a card before selling or grading it?",
     "No. Do not wipe, buff, polish or apply anything to a card. Cleaning attempts show up under a grader's "
     "light and get cards rejected as altered. A light dust-off with a clean microfiber is the absolute limit, "
     "and that is what our Card Prep service does."),
]

emit('guide-grade-your-own-cards.html', force=FORCE,
     title='How to Grade Your Own Pokémon Cards Before You Sell or Submit',
     desc='Read your own cards honestly: what Near Mint, Lightly Played and Moderately Played actually mean, the flaws people miss, and how condition changes what you get paid.',
     ogtype='article',
     schema=[crumbs('Grade Your Own Cards', 'guide-grade-your-own-cards.html'),
             article('How to Grade Your Own Pokemon Cards Before You Sell or Submit',
                     'What each condition tier actually means, the flaws sellers habitually miss, and how condition changes the money.',
                     'guide-grade-your-own-cards.html', 'Condition guides'),
             faq_schema(Q5)],
     body=hero('How to Read Your Own Cards',
               'Sellers grade their own cards about one tier too generously, almost universally. It is not '
               'dishonesty &mdash; it is that the flaws that matter are invisible until you know how to look for '
               'them. Here is how we look.') + '\n\n' +
     sec('Set yourself up first',
         prose(
             'You need one bright light source and a hard surface. Not overhead room lighting &mdash; a single '
             'directional light you can tilt the card against. Almost every flaw that costs you money is '
             'invisible flat-on under diffuse light and obvious the moment you angle the card.',
             'Take the card out of the sleeve. Handle it by the edges. Look at the back first, because the back '
             'is where wear shows earliest and where most people never think to look.')) + '\n\n' +
     sec('The four things to check, in order',
         '''      <div class="prep-steps">
        <div class="prep-step">
          <div class="prep-step-num">1</div>
          <h3>Edges &mdash; especially the back</h3>
          <p>Tilt the card and sight along each edge. You are looking for whitening: tiny flecks of white core
          showing through the black or colored border. This is the number one reason a card someone believes
          is Near Mint gets called Lightly Played, and it is essentially invisible unless you angle it.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">2</div>
          <h3>Corners</h3>
          <p>All eight of them, front and back. A sharp corner comes to a clean point. A soft corner looks
          slightly rounded or fuzzy; a dinged corner has a visible bend or white spot. One soft corner is
          Lightly Played territory. Several is Moderately Played.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">3</div>
          <h3>Surface</h3>
          <p>Angle the card so the light rakes across it. Now you will see scratches, print lines, scuffs on
          the holo, indentations and any cloudiness. Holo cards show surface wear far more readily than
          non-holo &mdash; a holo that looks perfect flat-on can be covered in fine scratches at 30 degrees.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">4</div>
          <h3>Centering</h3>
          <p>Compare the border width on opposite sides, front and back. For a raw sale this only matters when
          it is severe. For grading it matters enormously &mdash; centering is frequently the only thing standing
          between a 9 and a 10, and it is a factory flaw you cannot do anything about.</p>
        </div>
      </div>''') + '\n\n' +
     sec('What each tier actually means',
         '''      <div class="card" style="overflow-x:auto;border-radius:var(--r)">
        <table class="buylist-table">
          <caption class="visually-hidden">Card condition tiers, what they mean, and the value multiplier applied</caption>
          <thead>
            <tr><th scope="col">Tier</th><th scope="col">What it looks like</th><th scope="col">You get</th></tr>
          </thead>
          <tbody>
            <tr><td><strong>Near Mint</strong></td><td>Looks unplayed. Sharp corners, no edge whitening when tilted, clean surface. Minor factory imperfections are fine.</td><td class="buy-price">100%</td></tr>
            <tr><td><strong>Lightly Played</strong></td><td>Minor wear on close inspection. Slight edge whitening, one softening corner, or a light surface scratch.</td><td class="buy-price">85%</td></tr>
            <tr><td><strong>Moderately Played</strong></td><td>Wear obvious at a glance. Noticeable whitening, several soft corners, visible scratching or a light crease.</td><td class="buy-price">70%</td></tr>
            <tr><td><strong>Heavily Played</strong></td><td>Significant wear. Heavy whitening, creasing, major surface damage &mdash; but intact and clearly identifiable.</td><td class="buy-price">50%</td></tr>
            <tr><td><strong>Damaged</strong></td><td>Water damage, tears, heavy creasing, writing, or anything structural.</td><td class="buy-price">30%</td></tr>
          </tbody>
        </table>
      </div>
      <p style="font-size:13.5px;color:var(--dim);margin-top:14px;max-width:780px">
        These are the exact multipliers our quote tool applies. On a $400 card, the difference between calling
        it Near Mint and calling it Heavily Played is $200 &mdash; which is why we would rather you assess it
        accurately than optimistically.</p>''',
         sub='The multipliers here are the live ones our quote tool uses, not a general industry approximation.') + '\n\n' +
     sec('The rule that saves the most money',
         prose(
             '<strong>When you are torn between two tiers, pick the lower one.</strong> That is genuinely our '
             'own internal rule &mdash; we describe down, never up.',
             'The practical reason is that an over-optimistic self-assessment does not get you more money. It '
             'gets you a quote that then gets revised downward when the cards arrive, which is a worse '
             'experience for everyone and wastes a week. Quoting your cards honestly means the number you are '
             'told is the number you get paid.',
             'And one hard rule: <strong>do not clean, buff, polish or treat a card</strong>. Attempts to '
             'improve a card&rsquo;s appearance are visible to a grader under raking light and will get the card '
             'flagged as altered, which is worse than any condition problem you were trying to fix. A gentle '
             'dust-off with a clean microfiber is the entire acceptable range.')) + '\n\n' +
     sec('Condition questions', faq_html(Q5)) + '\n\n' +
     nextsteps([
         '<a href="trade-in.html">Quote your cards with the right condition selected</a> &mdash; the tool shows market value and offer separately.',
         '<a href="shipping.html">Pack them so the condition survives the trip</a> &mdash; badly packed Near Mint arrives Lightly Played.',
         '<a href="guide-should-you-grade.html">Thinking about grading instead?</a> The break-even math first.',
         '<a href="guide-spot-fake-pokemon-cards.html">Not sure a card is genuine?</a> The physical tests that settle it.',
     ]))


# ══════════════════════════════════════════════════════════════════════════════
# 6. Spotting fakes
# ══════════════════════════════════════════════════════════════════════════════
Q6 = [
    ("What is the fastest way to tell if a Pokemon card is fake?",
     "The light test. Hold the card up to a bright light. A genuine card has a thin black layer sandwiched "
     "between the front and back, so very little light passes through. Most counterfeits use single-layer "
     "stock and glow noticeably. Compare against a card you know is real from the same era."),
    ("Should I do the rip test?",
     "Only on a card you are prepared to destroy. Tearing a genuine card reveals a black core layer between "
     "two white layers. It is definitive and it is also permanent, so it is a last resort — never do it to a "
     "card that might be valuable."),
    ("Are fake cards always obvious?",
     "No, and they have improved a lot. Modern counterfeits can get the colors and the gloss close. What they "
     "consistently struggle with is the texture on textured cards, the fine detail in the holofoil pattern, "
     "the exact font weight and letter spacing, and the card stock itself."),
    ("What about proxies and custom cards?",
     "A card sold clearly labeled as a proxy, a custom or a fan art piece is not a counterfeit — it is just "
     "not a real card and has no collectible value. The problem is only when something is sold as genuine."),
    ("What should I do if I think I bought a fake?",
     "Stop, photograph it thoroughly front and back including the edges under angled light, and raise it with "
     "the platform you bought it on straight away — most have a specific process for counterfeit claims and "
     "they are usually time-limited. If you want a second pair of eyes first, send us the photos."),
]

emit('guide-spot-fake-pokemon-cards.html', force=FORCE,
     title='How to Spot Fake Pokémon Cards — The Tests That Actually Work',
     desc='The physical checks that reliably identify counterfeit Pokemon cards: the light test, card stock, texture, holofoil pattern, fonts and the back-print blue core.',
     ogtype='article',
     schema=[crumbs('Spotting Fakes', 'guide-spot-fake-pokemon-cards.html'),
             article('How to Spot Fake Pokemon Cards',
                     'The physical tests that reliably identify counterfeit Pokemon cards, from the light test to holofoil pattern and card stock.',
                     'guide-spot-fake-pokemon-cards.html', 'Authenticity guides'),
             faq_schema(Q6)],
     body=hero('How to Spot Fake Pok&eacute;mon Cards',
               'Counterfeits have got considerably better at color and gloss. What they still cannot '
               'consistently fake is the physical construction of the card. These are the tests that hold up.') + '\n\n' +
     sec('Start with a known-real card',
         prose(
             'Every test below is a comparison test. Put the suspect card next to a card you are certain is '
             'genuine, from the same era and ideally the same set, and check them side by side. Almost nobody '
             'can identify a fake in isolation; almost anybody can spot one next to a real card.',
             'Era matters because Pok&eacute;mon card stock, gloss and print technique have all changed over '
             'thirty years. Comparing a 1999 Base Set card to a modern one will produce differences that mean '
             'nothing.')) + '\n\n' +
     sec('The tests, most to least useful',
         '''      <div class="prep-steps">
        <div class="prep-step">
          <div class="prep-step-num">1</div>
          <h3>The light test</h3>
          <p>Hold the card up against a bright light. Genuine cards are built as a sandwich with an opaque
          black layer in the middle, so almost no light gets through. Most counterfeits use cheaper
          single-layer stock and glow visibly. Do this one first &mdash; it is non-destructive and it catches
          the majority of fakes on its own.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">2</div>
          <h3>Texture and gloss</h3>
          <p>Run a fingertip across the art. Modern full arts, illustration rares and textured cards have a
          distinct physical texture you can feel, and it follows the artwork precisely. Counterfeits are
          usually flat, or textured in a generic pattern that does not track the art. Gloss level should also
          match a real card from the same set.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">3</div>
          <h3>The holofoil pattern</h3>
          <p>Tilt the card and watch how the foil moves. Genuine holo patterns are fine, even and consistent
          with others from that set. Fakes tend toward a coarser, glittery, rainbow-ish sheen that shifts
          differently, and the foil often bleeds slightly outside where it should stop.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">4</div>
          <h3>Text, fonts and spacing</h3>
          <p>This is where counterfeiters are laziest. Compare font weight, letter spacing and the exact
          placement of the HP value, the set symbol, the card number, the energy symbols and the copyright
          line. Look for slightly-too-bold text, cramped or stretched spacing, and blurry or pixelated small
          type. The copyright line and the illustrator credit are worth reading character by character.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">5</div>
          <h3>The back print</h3>
          <p>Side by side, look at the blue of the card back. Genuine backs have a specific blue and a
          consistent swirl pattern; fakes commonly run too dark, too purple, or too washed out. Check the
          centering of the back too &mdash; counterfeits are frequently far more off-center than the real
          printing tolerance allows.</p>
        </div>
        <div class="prep-step">
          <div class="prep-step-num">6</div>
          <h3>Cut, size and thickness</h3>
          <p>Stack the card with a known-real one. They should be the same dimensions and the same thickness.
          Fakes are often marginally thinner or thicker, cut slightly out of square, or have edges that feel
          rough rather than cleanly finished.</p>
        </div>
      </div>''') + '\n\n' +
     sec('The rip test, and when to use it',
         prose(
             'Tearing a genuine card in half reveals the construction directly: a black core layer sandwiched '
             'between two white layers. A counterfeit typically shows solid white all the way through. It is '
             'the most definitive test there is.',
             'It is also irreversible, which makes it useless for exactly the cards you most want to '
             'authenticate. Use it only on a card you have already written off &mdash; a suspected fake from a '
             'lot of many identical ones, for instance. Never on anything you would be upset to lose.')) + '\n\n' +
     sec('Where fakes turn up',
         '''      <div class="card" style="padding:30px 32px;max-width:840px">
        <ul style="line-height:2.05;padding-left:20px;color:var(--muted)">
          <li><strong>Bulk lots and &ldquo;collection&rdquo; listings.</strong> A few fakes salted into a thousand
          real cards is the most common pattern we see, and it is usually the seller who did not know either.</li>
          <li><strong>Vintage chase cards at a suspiciously good price.</strong> Base Set Charizard is the
          single most counterfeited card in the hobby. If the price is well under the market, that is the
          reason.</li>
          <li><strong>Sealed product that has been resealed.</strong> Check the wrap seams and the crimp. A
          resealed box is a different problem from a fake card and an expensive one.</li>
          <li><strong>Off-brand slabs.</strong> A card in a case is not authenticated unless the company that
          cased it is one you recognize.</li>
        </ul>
      </div>''') + '\n\n' +
     sec('Authenticity questions', faq_html(Q6)) + '\n\n' +
     nextsteps([
         '<a href="contact.html">Send us photos if you are not sure</a> &mdash; front, back, and an angled shot under a light. We will tell you what we see, and we do not charge for it.',
         '<a href="pokemon-card-appraisal.html">Get a collection valued</a> &mdash; we flag anything that looks wrong as we go through it.',
         '<a href="guide-grade-your-own-cards.html">Reading condition on genuine cards</a>.',
         '<a href="pokemon-card-buyer-florida.html">Bring it to a booth</a> &mdash; in person is always the fastest way to settle it.',
     ]))

print('done.')
