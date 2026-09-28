// Run with:  node --test workers/square/test/
//
// The corpus test at the bottom is the important one: it runs the classifier
// over eight real first-touch enquiries pulled from the live mailbox. If a
// rule change starts auto-replying to one of those, this fails.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  classify,
  parseAddress,
  parseWeb3Form,
  extractFirstName,
  looksEnglish,
  renderReply,
  renderSubject,
  REASONS,
} from '../src/wholesale-autoreply.js';

const HERE = dirname(fileURLToPath(import.meta.url));

/** A message that should sail through every gate, for negative testing. */
function cleanMsg(overrides = {}) {
  return {
    from: 'Dana Whitfield <dana@whitfieldcards.example>',
    subject: 'Wholesale account',
    bodyText:
      'Hi there, I run a card shop and would like to open a wholesale account ' +
      'with you. Could you tell me how your terms work and what I would need ' +
      'to get set up as a reseller? Thanks, Dana',
    headers: {},
    hasAttachments: false,
    threadMessageCount: 1,
    labels: ['INBOX'],
    ...overrides,
  };
}

const CLEAN_CTX = {
  alreadyReplied: false,
  knownContact: false,
  killSwitch: false,
  sentLastHour: 0,
  sentLastDay: 0,
};

// ─── Baseline ──────────────────────────────────────────────────────────────

test('a clean generic terms enquiry is eligible for reply', () => {
  const r = classify(cleanMsg(), CLEAN_CTX);
  assert.equal(r.decision, 'reply');
  assert.equal(r.firstName, 'Dana');
});

// ─── Stage 0: drop ─────────────────────────────────────────────────────────

test('drops mail carrying Auto-Submitted', () => {
  const r = classify(cleanMsg({ headers: { 'Auto-Submitted': 'auto-replied' } }), CLEAN_CTX);
  assert.equal(r.decision, 'drop');
  assert.deepEqual(r.reasons, [REASONS.AUTO_SUBMITTED]);
});

test('Auto-Submitted: no is not a drop', () => {
  const r = classify(cleanMsg({ headers: { 'Auto-Submitted': 'no' } }), CLEAN_CTX);
  assert.equal(r.decision, 'reply');
});

test('drops mailing lists and bulk precedence', () => {
  assert.equal(classify(cleanMsg({ headers: { 'List-Id': '<x.example>' } }), CLEAN_CTX).decision, 'drop');
  assert.equal(classify(cleanMsg({ headers: { Precedence: 'bulk' } }), CLEAN_CTX).decision, 'drop');
});

test('drops no-reply style senders', () => {
  for (const from of ['no-reply@x.com', 'noreply@x.com', 'mailer-daemon@x.com', 'postmaster@x.com']) {
    assert.equal(classify(cleanMsg({ from }), CLEAN_CTX).decision, 'drop', from);
  }
});

test('never replies to ourselves', () => {
  for (const from of ['nick@sakekittycards.com', 'wholesale@sakekittycards.com', 'sakekittycards@gmail.com']) {
    const r = classify(cleanMsg({ from }), CLEAN_CTX);
    assert.equal(r.decision, 'drop', from);
    assert.deepEqual(r.reasons, [REASONS.OWN_ADDRESS]);
  }
});

test('drops spam-labelled mail', () => {
  assert.equal(classify(cleanMsg({ labels: ['SPAM'] }), CLEAN_CTX).decision, 'drop');
});

// ─── Stage 1: hard blocks ──────────────────────────────────────────────────

const blocks = [
  ['currency in body', { bodyText: 'Terms for a reseller account, budget is $4,000.' }, REASONS.CURRENCY],
  ['currency written out', { bodyText: 'Opening a reseller account, around 4000 USD to start.' }, REASONS.CURRENCY],
  ['quantity', { bodyText: 'Reseller account please, thinking 5 cases to start.' }, REASONS.QUANTITY],
  ['availability', { bodyText: 'Reseller account - what do you have in stock?' }, REASONS.AVAILABILITY],
  ['sourcing', { bodyText: 'Reseller account - can you get me sealed product?' }, REASONS.SOURCING],
  ['english', { bodyText: 'Reseller account, interested in English sealed.' }, REASONS.ENGLISH],
  ['price request', { bodyText: 'Reseller account - could you send a price list?' }, REASONS.PRICE_REQUEST],
  ['chaser', { bodyText: 'Reseller account. I already emailed about this.' }, REASONS.CHASER],
  ['partnership', { bodyText: 'Reseller account - I would like to discuss consignment.' }, REASONS.PARTNERSHIP],
  ['attachment', { hasAttachments: true }, REASONS.ATTACHMENT],
];

for (const [label, override, expectedReason] of blocks) {
  test(`routes on ${label}`, () => {
    const r = classify(cleanMsg(override), CLEAN_CTX);
    assert.equal(r.decision, 'route', `${label} should route`);
    assert.ok(
      r.reasons.some((x) => x.startsWith(expectedReason)),
      `${label}: expected ${expectedReason}, got ${r.reasons.join(', ')}`
    );
  });
}

test('routes on every catalogue product term', () => {
  const samples = ['storm emeralda', 'gem pack', 'black crystal blaze', 'shiny treasure',
                   'prismatic evolutions', 'surging sparks', '151', 'booster box', 'ETB'];
  for (const term of samples) {
    const r = classify(cleanMsg({ bodyText: `Reseller account enquiry about ${term} for my store.` }), CLEAN_CTX);
    assert.equal(r.decision, 'route', `"${term}" should route`);
    assert.ok(r.reasons.some((x) => x.startsWith(REASONS.PRODUCT_NAME)), `"${term}" reasons: ${r.reasons}`);
  }
});

test('routes anything that is not a first touch', () => {
  assert.ok(classify(cleanMsg({ subject: 'Re: Wholesale account' }), CLEAN_CTX)
    .reasons.includes(REASONS.NOT_FIRST_TOUCH));
  assert.ok(classify(cleanMsg({ threadMessageCount: 2 }), CLEAN_CTX)
    .reasons.includes(REASONS.NOT_FIRST_TOUCH));
  assert.ok(classify(cleanMsg({ headers: { 'In-Reply-To': '<a@b>' } }), CLEAN_CTX)
    .reasons.includes(REASONS.NOT_FIRST_TOUCH));
});

test('routes a sender we have already auto-replied to', () => {
  const r = classify(cleanMsg(), { ...CLEAN_CTX, alreadyReplied: true });
  assert.equal(r.decision, 'route');
  assert.ok(r.reasons.includes(REASONS.ALREADY_REPLIED));
});

test('routes a known contact', () => {
  const r = classify(cleanMsg(), { ...CLEAN_CTX, knownContact: true });
  assert.ok(r.reasons.includes(REASONS.KNOWN_CONTACT));
});

test('routes site-form offers', () => {
  const r = classify(cleanMsg({ subject: 'Offer: PSA 10 Charizard' }), CLEAN_CTX);
  assert.equal(r.decision, 'route');
  assert.ok(r.reasons.includes(REASONS.SITE_OFFER));
});

test('routes an overlong body', () => {
  const r = classify(cleanMsg({ bodyText: cleanMsg().bodyText + ' filler'.repeat(500) }), CLEAN_CTX);
  assert.ok(r.reasons.includes(REASONS.TOO_LONG));
});

test('routes when no first name can be extracted', () => {
  const r = classify(cleanMsg({
    from: 'info@somecardshop.example',
    bodyText: 'We would like to open a wholesale reseller account. Please advise on terms.',
  }), CLEAN_CTX);
  assert.equal(r.decision, 'route');
  assert.ok(r.reasons.includes(REASONS.NO_FIRST_NAME));
});

test('routes non-English bodies', () => {
  const r = classify(cleanMsg({ bodyText: 'こんにちは、卸売アカウントを開設したいのですが、条件を教えてください。' }), CLEAN_CTX);
  assert.ok(r.reasons.includes(REASONS.NOT_ENGLISH_LANG));
});

// ─── Stage 2 ───────────────────────────────────────────────────────────────

test('routes when there is no wholesale intent at all', () => {
  const r = classify(cleanMsg({
    subject: 'Question',
    bodyText: 'Hi, I am Dana. I was wondering if you are open on Sundays and where you are based. Thanks.',
  }), CLEAN_CTX);
  assert.equal(r.decision, 'route');
  assert.ok(r.reasons.includes(REASONS.NO_WHOLESALE_INTENT));
});

test('kill switch forces route', () => {
  const r = classify(cleanMsg(), { ...CLEAN_CTX, killSwitch: true });
  assert.equal(r.decision, 'route');
  assert.ok(r.reasons.includes(REASONS.KILL_SWITCH));
});

test('rate caps force route', () => {
  assert.ok(classify(cleanMsg(), { ...CLEAN_CTX, sentLastHour: 3 }).reasons.includes(REASONS.CAP_HOURLY));
  assert.ok(classify(cleanMsg(), { ...CLEAN_CTX, sentLastDay: 10 }).reasons.includes(REASONS.CAP_DAILY));
});

// ─── Parsing helpers ───────────────────────────────────────────────────────

test('parseAddress handles both forms', () => {
  assert.deepEqual(parseAddress('Dana W <dana@x.com>'), { name: 'Dana W', email: 'dana@x.com' });
  assert.deepEqual(parseAddress('dana@x.com'), { name: '', email: 'dana@x.com' });
});

test('extractFirstName prefers a personal display name', () => {
  assert.equal(extractFirstName('Marcus Trelane', ''), 'Marcus');
});

test('extractFirstName ignores corporate display names and falls back to the body', () => {
  assert.equal(extractFirstName('Curio Dept', 'Hi, my name is Declan and I run a shop.'), 'Declan');
  assert.equal(extractFirstName('The Last Word TCG', 'no introduction here'), null);
});

test('extractFirstName reads a sign-off', () => {
  assert.equal(extractFirstName('info@x.com', 'We want an account.\n\nThanks,\nMacen'), 'Macen');
});

test('looksEnglish rejects CJK and accepts ordinary English', () => {
  assert.equal(looksEnglish('こんにちは、卸売アカウントを開設したいのですが'), false);
  assert.equal(looksEnglish('We would like to open an account with you for our store.'), true);
});

test('parseWeb3Form unwraps a site form submission', () => {
  const parsed = parseWeb3Form({
    from: 'notify+abc123@web3forms.com',
    subject: 'Contact: Wholesale / B2B',
    bodyText: 'name : Dana Whitfield\nemail : dana@x.com\ntopic : Wholesale / B2B\nmessage : Hello, I want an account.\nSecond line.',
  });
  assert.equal(parsed.from, 'Dana Whitfield <dana@x.com>');
  assert.equal(parsed.bodyText, 'Hello, I want an account.\nSecond line.');
  assert.equal(parsed.viaWebForm, true);
});

test('parseWeb3Form returns null for ordinary mail', () => {
  assert.equal(parseWeb3Form({ from: 'dana@x.com', bodyText: 'hello' }), null);
});

test('a web3forms submission is NOT dropped as a bulk sender', () => {
  const r = classify({
    from: 'notify+abc123@web3forms.com',
    subject: 'Contact: Wholesale / B2B',
    bodyText: 'name : Dana Whitfield\nemail : dana@x.com\ntopic : Wholesale / B2B\nmessage : Hi, I run a card shop and want to open a wholesale reseller account. What are your terms to get set up?',
    headers: {},
    hasAttachments: false,
    threadMessageCount: 1,
    labels: ['INBOX'],
  }, CLEAN_CTX);
  assert.notEqual(r.decision, 'drop');
  assert.equal(r.decision, 'reply');
  assert.equal(r.firstName, 'Dana');
});

// ─── Template ──────────────────────────────────────────────────────────────

test('the reply template leaks no price, product or discount', () => {
  const body = renderReply({ firstName: 'Dana' });

  // The only currency figure permitted is the $1,500 minimum.
  const amounts = body.match(/\$[\d,]+/g) || [];
  assert.deepEqual(amounts, ['$1,500'], `unexpected amounts: ${amounts}`);

  // No catalogue product may appear.
  for (const term of ['storm emeralda', 'gem pack', 'prismatic', 'booster box', 'etb', '151']) {
    assert.ok(!body.toLowerCase().includes(term), `template mentions "${term}"`);
  }

  // Never volunteer English, never imply a discount.
  assert.ok(!/\benglish\b/i.test(body), 'template mentions English');
  assert.ok(/don't offer volume discounts/i.test(body), 'template must rule discounts out explicitly');

  // Nick's voice: no exclamation marks, no em-dashes.
  assert.ok(!body.includes('!'), 'template contains an exclamation mark');
  assert.ok(!/[—–]/.test(body), 'template contains an em- or en-dash');

  // The durable facts the brief requires.
  for (const fact of ['$1,500', 'Wire', 'Wise', 'Zelle', 'resale certificate', 'without markup']) {
    assert.ok(
      body.toLowerCase().includes(fact.toLowerCase()),
      `template is missing "${fact}"`
    );
  }

  // Links to the price-free lead page, never the pricing catalogue.
  assert.ok(body.includes('sakekittycards.com/wholesale-pokemon'), 'wrong catalogue link');
  assert.ok(!/sakekittycards\.com\/wholesale(?!-pokemon)/.test(body), 'links the pricing catalogue');
});

test('renderSubject prefixes Re: exactly once', () => {
  assert.equal(renderSubject('Wholesale account'), 'Re: Wholesale account');
  assert.equal(renderSubject('Re: Wholesale account'), 'Re: Wholesale account');
  assert.equal(renderSubject(''), 'Re: Wholesale enquiry');
});

// ─── The real corpus ───────────────────────────────────────────────────────

test('eight real first-touch enquiries are classified as the brief requires', () => {
  const { cases } = JSON.parse(
    readFileSync(join(HERE, 'fixtures', 'real-enquiries.json'), 'utf8')
  );

  const results = [];
  for (const c of cases) {
    const r = classify(c.msg, CLEAN_CTX);
    results.push({ id: c.id, expect: c.expect, got: r.decision, reasons: r.reasons });
    assert.equal(
      r.decision,
      c.expect,
      `${c.id}: expected ${c.expect}, got ${r.decision} (${r.reasons.join(', ')})`
    );
  }

  // Report the fire rate so a rule change that quietly opens the gates is
  // visible in the test output, not just in production.
  const replied = results.filter((r) => r.got === 'reply').length;
  console.log(`\n  corpus: ${replied}/${results.length} auto-reply, ${results.length - replied} routed`);
  for (const r of results) {
    console.log(`    ${r.got.padEnd(6)} ${r.id.padEnd(24)} ${r.reasons.slice(0, 3).join(', ')}`);
  }
});
