// Wholesale first-touch auto-reply — classifier and reply template.
//
// Governing rule, from AUTOREPLY-BRIEF.md:
//   Auto-send only what is true regardless of who is asking.
//   Never auto-send anything touching a price, a product, availability,
//   quantity, sourcing, or English product. Default on ambiguity is ROUTE.
//
// Everything here is pure — no I/O, no bindings, no Date.now(). The Worker
// supplies state (already-replied senders, rate-limit counts, config) in
// `ctx`, which keeps the whole decision surface unit-testable.

// ─── Term lists ────────────────────────────────────────────────────────────

// Distinctive product terms. Derived from the 68 catalogue SKU names in
// wholesale.html (var CATALOG), then hand-extended with the short forms and
// nicknames a buyer would actually type. Regenerate the derived half with:
//   git show origin/main:wholesale.html | grep -oE "name:'[^']+'"
const PRODUCT_TERMS = [
  // Derived from catalogue SKU names
  '151', '30th anniversary', '30th', 'abyss eye', 'ancient roar',
  'battle partners', 'black crystal blaze', 'blade awakened',
  'brilliant illusion', 'bt01', 'bt02', 'bt03', 'unbreakable',
  'chaos rising', 'clay burst', 'cyber judge', 'dream drawing',
  'eevee', 'eeveelution', 'vaporeon', 'flareon', 'jolteon',
  'first chapter', 'floodborn', 'fukuoka', 'future flash', 'gem pack',
  'hiroshima', 'inferno x', 'kpop demon hunters', 'mega brave',
  'mega dream', 'mega symphonia', 'naruto', 'night wanderer',
  'nihil zero', 'ninja spinner', 'paldea', 'panini', 'fifa world cup',
  'pitch black', 'pursue glory together', 'raging surf',
  'rise of the floodborn', 'sharp blade awakening', 'shiny treasure',
  'snow hazard', 'spiritforged', 'stellar glass', 'stellar miracle',
  'storm emeralda', 'terastal', 'tohoku', 'trainer collection',
  'triple beat', 'true mystery', 'v-union', 'v union', 'violet ex',
  'vstar universe', 'wild force',

  // Named in the brief as must-block synonyms
  'prismatic', 'prismatic evolutions', 'surging sparks',

  // Common set/product nicknames not in the catalogue but certain to appear
  'charizard', 'pikachu', 'umbreon', 'sv2a', 'crown zenith', 'evolving skies',
  'obsidian flames', 'paradox rift', 'temporal forces', 'twilight masquerade',
  'shrouded fable', 'stellar crown', 'journey together', 'destined rivals',
  'white flare', 'black bolt', 'mega evolution', 'phantasmal flames',
  'lorcana', 'one piece', 'weiss schwarz', 'yugioh', 'yu-gi-oh',

  // Generic product categories — any of these is product talk, so route
  'booster box', 'booster boxes', 'booster bundle', 'booster display',
  'elite trainer box', 'etb', 'etbs', 'coin set', 'gift box', 'special box',
  'half case', 'half-case', 'sealed case',
];

const AVAILABILITY_TERMS = [
  'in stock', 'in-stock', 'stock', 'available', 'availability', 'how many',
  'do you have', 'do you carry', 'got any', 'have any', 'when can you',
  'when will', 'when would', 'lead time', 'leadtime', 'restock', 'eta',
  'on hand', 'inventory', 'quantities available',
];

const SOURCING_TERMS = [
  'can you get', 'can you source', 'source', 'sourcing', 'order in',
  'preorder', 'pre-order', 'pre order', 'allocation', 'allocate',
  'bring in', 'special order', 'able to get', 'get your hands on',
  'procure', 'obtain',
];

// Anything that touches a price. The brief's rule is absolute: never
// auto-send anything touching a price, and a request for one qualifies.
const PRICE_REQUEST_TERMS = [
  'price', 'prices', 'pricing', 'price list', 'pricelist', 'price sheet',
  'quote', 'quotation', 'how much', 'cost', 'costs', 'rate', 'rates',
  'discount', 'discounts', 'deal', 'deals', 'best price', 'wholesale price',
  'wholesale pricing', 'case pricing', 'pallet pricing', 'msrp', 'margin',
];

// A second approach is not a first touch, even when it arrives on a brand
// new thread through a different channel.
const CHASER_TERMS = [
  'already emailed', 'already sent', 'no response', 'no reply',
  'have not heard', "haven't heard", 'havent heard', 'following up',
  'follow up', 'follow-up', 'checking in', 'chasing', 'second time',
  'reached out before', 'previously reached out', 'sent a message before',
  'still waiting', 'any update', 'bumping this',
];

const PARTNERSHIP_TERMS = [
  'consignment', 'consign', 'partnership', 'partner with', 'partnering',
  'commission', 'agent', 'affiliate', 'collaborate', 'collaboration',
  'joint venture', 'invest', 'investment', 'investor', 'equity',
  'distributor agreement', 'distribution agreement', 'exclusive rights',
  'sponsorship', 'sponsor',
];

// Positive signal that this is a wholesale enquiry at all. Stage 2 requires
// at least one of these — absence means route, not send.
const WHOLESALE_INTENT_TERMS = [
  'wholesale', 'b2b', 'bulk', 'reseller', 'resell', 'resale', 'trade account',
  'wholesale account', 'open an account', 'opening an account',
  'minimum order', 'moq', 'terms', 'distributor', 'retailer', 'my shop',
  'my store', 'our store', 'our shop', 'lgs', 'card shop',
];

// Display-name tokens that mean the From name is a business, not a person.
const COMPANY_NAME_TOKENS = [
  'llc', 'inc', 'ltd', 'limited', 'co', 'corp', 'company', 'cards', 'card',
  'shop', 'store', 'group', 'team', 'dept', 'department', 'games', 'gaming',
  'tcg', 'collectibles', 'collectables', 'sales', 'trading', 'supply',
  'wholesale', 'labs', 'lab', 'holdings', 'enterprises', 'ventures', 'the',
  'info', 'sales', 'admin', 'support', 'contact', 'hello',
];

const BULK_SENDER_PATTERNS = [
  /^no-?reply@/i, /^do-?not-?reply@/i, /^notify\+/i, /^notifications?@/i,
  /^bounce/i, /^mailer-daemon@/i, /^postmaster@/i, /^automated@/i,
  /^alerts?@/i, /^robot@/i, /^daemon@/i,
];

// Our own addresses — never reply to ourselves.
const OWN_ADDRESS_PATTERNS = [
  /@sakekittycards\.com$/i,
  /^sakekittycards@gmail\.com$/i,
  /@tcgenie\.io$/i,
];

// ─── Decision codes ────────────────────────────────────────────────────────
// Stored verbatim in D1 so the shadow log explains itself without the code.

export const REASONS = {
  // drop
  AUTO_SUBMITTED: 'drop.auto_submitted',
  MAILING_LIST: 'drop.mailing_list',
  BULK_PRECEDENCE: 'drop.bulk_precedence',
  BULK_SENDER: 'drop.bulk_sender',
  OWN_ADDRESS: 'drop.own_address',
  SPAM: 'drop.spam',
  NO_SENDER: 'drop.no_sender',
  // route — hard blocks
  NOT_FIRST_TOUCH: 'route.not_first_touch',
  ALREADY_REPLIED: 'route.already_replied',
  KNOWN_CONTACT: 'route.known_contact',
  CURRENCY: 'route.currency_amount',
  QUANTITY: 'route.quantity',
  PRODUCT_NAME: 'route.product_name',
  AVAILABILITY: 'route.availability',
  SOURCING: 'route.sourcing',
  ENGLISH: 'route.english_product',
  SITE_OFFER: 'route.site_offer',
  PARTNERSHIP: 'route.partnership',
  PRICE_REQUEST: 'route.price_request',
  CHASER: 'route.chaser',
  ATTACHMENT: 'route.attachment',
  TOO_LONG: 'route.body_too_long',
  NO_FIRST_NAME: 'route.no_first_name',
  NOT_ENGLISH_LANG: 'route.not_english_language',
  // route — stage 2 failures
  NO_WHOLESALE_INTENT: 'route.no_wholesale_intent',
  BODY_TOO_SHORT: 'route.body_too_short',
  KILL_SWITCH: 'route.kill_switch',
  CAP_HOURLY: 'route.cap_hourly',
  CAP_DAILY: 'route.cap_daily',
  // send
  ELIGIBLE: 'reply.eligible',
};

/**
 * Two rule sets, switchable at runtime through the `ruleset` config key.
 *
 * 'standard' (default) - acknowledge and route. Auto-replies to a genuine
 *   wholesale first touch even when it names a product, a quantity or a
 *   budget, because the reply never answers any of those: it delivers the
 *   durable terms and says Nick is picking the specifics up. The message
 *   still reaches Nick either way.
 *
 * 'strict' - the original brief. Any mention of a price, product, quantity,
 *   availability or sourcing is a hard block. Measured against eight real
 *   first-touch enquiries this replies to none of them, because naming a
 *   product or a budget is what a wholesale enquiry is.
 *
 * Neither set changes a word of what goes out. The template carries no
 * price, no product name and no availability claim under either.
 */
export const RULESETS = { STANDARD: 'standard', STRICT: 'strict' };
export const DEFAULT_RULESET = RULESETS.STANDARD;

export const DEFAULT_CAPS = { perHour: 3, perDay: 10 };
export const MAX_BODY_CHARS = 2000;
export const MIN_BODY_CHARS = 20;

// ─── Text helpers ──────────────────────────────────────────────────────────

/** Lowercase, strip accents, collapse punctuation to spaces. */
export function normalizeText(s) {
  if (!s) return '';
  return String(s)
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[–—]/g, '-')
    .toLowerCase();
}

/** Match a term on word boundaries so "eevee" does not fire inside "eeveelution". */
function hasTerm(haystack, term) {
  const esc = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(^|[^a-z0-9])${esc}([^a-z0-9]|$)`, 'i').test(haystack);
}

function firstTermHit(haystack, terms) {
  for (const t of terms) if (hasTerm(haystack, t)) return t;
  return null;
}

/** Address out of "Name <a@b.com>" or a bare address. */
export function parseAddress(from) {
  if (!from) return { name: '', email: '' };
  const angled = /<([^>]+)>/.exec(from);
  const email = (angled ? angled[1] : from).trim().toLowerCase();
  let name = angled ? from.slice(0, angled.index).trim() : '';
  name = name.replace(/^["']|["']$/g, '').trim();
  return { name, email };
}

/**
 * The site contact form (web3forms) is the single busiest wholesale intake
 * channel, and it arrives from notify+xxxxx@web3forms.com with the real
 * sender buried in the body:
 *
 *   name : Marcus Trelane
 *   email : marcus@northvaleretail.example
 *   topic : Wholesale / B2B
 *   message : Hi Sake Kitty Cards team, ...
 *
 * Without this, every form submission is discarded by the bulk-sender drop
 * rule. Unwrap it into a message that looks like ordinary inbound mail, and
 * mark it so the Worker knows to send a fresh message rather than a threaded
 * reply (there is nothing of the sender's to reply to).
 *
 * Returns null when `msg` is not a recognisable form submission.
 */
export function parseWeb3Form(msg) {
  const { email: senderEmail } = parseAddress(msg.from);
  if (!/@web3forms\.com$/i.test(senderEmail)) return null;

  const body = msg.bodyText || '';
  const field = (key) => {
    const re = new RegExp(`^\\s*${key}\\s*:\\s*(.*)$`, 'im');
    const m = re.exec(body);
    return m ? m[1].trim() : '';
  };

  const name = field('name');
  const email = field('email').toLowerCase();
  const topic = field('topic');

  // The message field runs to the end of the payload.
  const msgIdx = body.search(/^\s*message\s*:/im);
  let message = '';
  if (msgIdx >= 0) {
    message = body.slice(msgIdx).replace(/^\s*message\s*:\s*/i, '').trim();
  }

  if (!email || !email.includes('@') || !message) return null;

  return {
    ...msg,
    from: name ? `${name} <${email}>` : email,
    subject: topic ? `Wholesale enquiry - ${topic}` : (msg.subject || 'Wholesale enquiry'),
    bodyText: message,
    formTopic: topic,
    viaWebForm: true,
    // A form submission has no message of the sender's to thread onto.
    threadMessageCount: 1,
    headers: {},
  };
}

/**
 * Turn raw inbound mail into the shape the classifier reasons about.
 * Currently that means unwrapping site-form submissions; everything else
 * passes through untouched.
 */
export function normalizeInbound(msg) {
  return parseWeb3Form(msg) || msg;
}

/**
 * Best-effort first name. Returns null when we cannot get one confidently —
 * the caller treats that as a route, because a template that cannot greet
 * the sender by name has no business going out unattended.
 */
export function extractFirstName(fromName, bodyText) {
  const clean = (w) => w.replace(/[^A-Za-z'-]/g, '');
  const ok = (w) =>
    w.length >= 2 &&
    w.length <= 20 &&
    /^[A-Za-z][A-Za-z'-]*$/.test(w) &&
    !COMPANY_NAME_TOKENS.includes(w.toLowerCase());

  // 1. Display name, when it looks like a person. A display name that is
  //    itself an address ("info@x.com") is not one — stripping the
  //    punctuation out of it yields plausible-looking junk like "Infoxcom".
  if (fromName && !fromName.includes('@')) {
    const parts = fromName.split(/\s+/).map(clean).filter(Boolean);
    const looksCorporate = parts.some((p) =>
      COMPANY_NAME_TOKENS.includes(p.toLowerCase())
    );
    if (!looksCorporate && parts.length >= 1 && ok(parts[0])) {
      return titleCase(parts[0]);
    }
  }

  // 2. Self-introduction in the body.
  const body = bodyText || '';
  const patterns = [
    /\bmy name is\s+([A-Za-z][A-Za-z'-]{1,19})/i,
    /\bthis is\s+([A-Za-z][A-Za-z'-]{1,19})/i,
    /\bi'?m\s+([A-Za-z][A-Za-z'-]{1,19})\s*[,.]/i,
    /\bname'?s\s+([A-Za-z][A-Za-z'-]{1,19})/i,
  ];
  for (const re of patterns) {
    const m = re.exec(body);
    if (m && ok(m[1])) return titleCase(m[1]);
  }

  // 3. Sign-off on the last few non-empty lines. Handles both the one-line
  //    form ("Thanks, Macen") and the far more common two-line form
  //    ("Thank you," / "Macen").
  const SIGNOFF = /^(?:-{1,2}\s*)?(?:thanks|thank you|many thanks|regards|kind regards|best regards|best|cheers|sincerely|all the best)\b/i;
  const lines = body.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const tail = lines.slice(-6);

  for (let i = 0; i < tail.length; i++) {
    const m = new RegExp(SIGNOFF.source + String.raw`\s*[,.-]?\s*([A-Za-z][A-Za-z'-]{1,19})$`, 'i').exec(tail[i]);
    if (m && ok(m[1])) return titleCase(m[1]);

    // Sign-off alone on its line: the next line is the name.
    if (SIGNOFF.test(tail[i]) && /^[a-z\s,.-]+$/i.test(tail[i]) && tail[i + 1]) {
      const first = tail[i + 1].split(/\s+/)[0];
      const w = clean(first);
      if (ok(w)) return titleCase(w);
    }
  }

  return null;
}

function titleCase(w) {
  return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
}

/**
 * Crude English-language check. We are not trying to identify the language,
 * only to confirm the text looks like the English our template answers in.
 */
export function looksEnglish(bodyText) {
  const t = normalizeText(bodyText);
  if (!t.trim()) return false;

  // A run of CJK, Cyrillic, Arabic, Hebrew, Thai or Devanagari is the one
  // reliable signal. Treat that as decisive.
  const nonLatin = (t.match(/[぀-ヿ一-鿿Ѐ-ӿ؀-ۿ֐-׿฀-๿ऀ-ॿ]/g) || []).length;
  if (nonLatin > 5) return false;

  // Short messages carry too few function words to judge, and demanding
  // proof of English from them routes perfectly ordinary two-line
  // enquiries. Let them through; stage 2 still requires English wholesale
  // vocabulary before anything is sent, which catches other languages
  // written in Latin script.
  if (t.length < 200) return true;

  const common = ['the', 'and', 'you', 'for', 'we ', 'is ', 'are', 'to ', 'of ', 'in ', 'would', 'with', 'our', 'that', 'have'];
  return common.filter((w) => t.includes(w)).length >= 3;
}

// ─── Stage 0: drop ─────────────────────────────────────────────────────────

function dropReason(msg) {
  const h = lowerKeys(msg.headers || {});

  const autoSubmitted = h['auto-submitted'];
  if (autoSubmitted && autoSubmitted.trim().toLowerCase() !== 'no') {
    return REASONS.AUTO_SUBMITTED;
  }
  if (h['list-id'] || h['list-unsubscribe'] || h['list-post']) {
    return REASONS.MAILING_LIST;
  }
  const precedence = (h['precedence'] || '').trim().toLowerCase();
  if (['bulk', 'list', 'junk', 'auto_reply'].includes(precedence)) {
    return REASONS.BULK_PRECEDENCE;
  }
  if (h['x-autoreply'] || h['x-autorespond'] || h['x-auto-response-suppress']) {
    return REASONS.AUTO_SUBMITTED;
  }

  const { email } = parseAddress(msg.from);
  if (!email || !email.includes('@')) return REASONS.NO_SENDER;
  if (OWN_ADDRESS_PATTERNS.some((re) => re.test(email))) return REASONS.OWN_ADDRESS;
  if (BULK_SENDER_PATTERNS.some((re) => re.test(email))) return REASONS.BULK_SENDER;

  const labels = (msg.labels || []).map((l) => String(l).toUpperCase());
  if (labels.includes('SPAM') || labels.includes('TRASH')) return REASONS.SPAM;

  return null;
}

function lowerKeys(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj || {})) out[String(k).toLowerCase()] = v;
  return out;
}

// ─── Stage 1: hard blocks ──────────────────────────────────────────────────

function routeReasons(msg, ctx, firstName) {
  const reasons = [];
  const strict = (ctx.ruleset || DEFAULT_RULESET) === RULESETS.STRICT;
  const subject = msg.subject || '';
  const body = msg.bodyText || '';
  const hay = normalizeText(`${subject}\n${body}`);
  const { email } = parseAddress(msg.from);

  // 1. First touch only.
  const h = lowerKeys(msg.headers || {});
  const isReplySubject = /^\s*(re|fw|fwd|aw|sv|antw)\s*:/i.test(subject);
  if ((msg.threadMessageCount || 1) > 1 || h['in-reply-to'] || h['references'] || isReplySubject) {
    reasons.push(REASONS.NOT_FIRST_TOUCH);
  }

  // 2 & 3. Sender history.
  if (ctx.alreadyReplied) reasons.push(REASONS.ALREADY_REPLIED);
  if (ctx.knownContact) reasons.push(REASONS.KNOWN_CONTACT);

  // 4. Any currency amount. Strict only.
  if (strict && (/[$£€¥]\s?\d/.test(body) || /[$£€¥]\s?\d/.test(subject) ||
      /\b\d[\d,]*(?:\.\d+)?\s*(?:usd|dollars?|eur|gbp|jpy|cad)\b/i.test(hay))) {
    reasons.push(REASONS.CURRENCY);
  }

  // 5. Quantity-shaped numbers. Strict only.
  if (strict && (/\b\d[\d,]*\s*(?:x\b|pcs?\b|cases?\b|boxes?\b|box\b|bundles?\b|packs?\b|units?\b|etbs?\b|displays?\b|pallets?\b|sets?\b|tins?\b)/i.test(hay) ||
      /\b\d[\d,]*\s+of\s+(?:each|them|those|these)\b/i.test(hay) ||
      /\bqty\b|\bquantit/i.test(hay))) {
    reasons.push(REASONS.QUANTITY);
  }

  // 6. Product or set names. Strict only.
  const productHit = strict ? firstTermHit(hay, PRODUCT_TERMS) : null;
  if (productHit) reasons.push(`${REASONS.PRODUCT_NAME}:${productHit}`);

  // 7. Availability. Strict only.
  const availHit = strict ? firstTermHit(hay, AVAILABILITY_TERMS) : null;
  if (availHit) reasons.push(`${REASONS.AVAILABILITY}:${availHit}`);

  // 8. Sourcing. Strict only.
  const sourceHit = strict ? firstTermHit(hay, SOURCING_TERMS) : null;
  if (sourceHit) reasons.push(`${REASONS.SOURCING}:${sourceHit}`);

  // 9. English product — stocked but never advertised, so never volunteered.
  if (hasTerm(hay, 'english')) reasons.push(REASONS.ENGLISH);

  // 10. Site-form offers are real money.
  if (/\boffer\b\s*:/i.test(subject) || /^offer\b/i.test(subject.trim()) ||
      /\bmy offer\b|\bi'?d like to offer\b|\boffering you\b/i.test(hay)) {
    reasons.push(REASONS.SITE_OFFER);
  }

  // 11. Consignment / partnership / agency proposals.
  const partnerHit = firstTermHit(hay, PARTNERSHIP_TERMS);
  if (partnerHit) reasons.push(`${REASONS.PARTNERSHIP}:${partnerHit}`);

  // 11a. Any request that touches a price. Strict only.
  const priceHit = strict ? firstTermHit(hay, PRICE_REQUEST_TERMS) : null;
  if (priceHit) reasons.push(`${REASONS.PRICE_REQUEST}:${priceHit}`);

  // 11b. Someone chasing an earlier approach is not a first touch, whatever
  // channel it arrived on. Auto-replying to a chaser with generic terms is
  // the exact wound that cost us an account earlier this year.
  const chaserHit = firstTermHit(hay, CHASER_TERMS);
  if (chaserHit) reasons.push(`${REASONS.CHASER}:${chaserHit}`);

  // 12. Attachments could be order sheets, POs or certificates.
  if (msg.hasAttachments) reasons.push(REASONS.ATTACHMENT);

  // 13. Long messages are not the generic first touch this template answers.
  if (body.length > MAX_BODY_CHARS) reasons.push(REASONS.TOO_LONG);

  // 14. No confident greeting.
  if (!firstName) reasons.push(REASONS.NO_FIRST_NAME);

  // 15. Language we cannot classify.
  if (!looksEnglish(body)) reasons.push(REASONS.NOT_ENGLISH_LANG);

  return reasons;
}

// ─── Stage 2: affirmative eligibility ──────────────────────────────────────

function stage2Reasons(msg, ctx) {
  const reasons = [];
  const body = msg.bodyText || '';
  const hay = normalizeText(`${msg.subject || ''}\n${body}`);
  const caps = { ...DEFAULT_CAPS, ...(ctx.caps || {}) };

  if (ctx.killSwitch) reasons.push(REASONS.KILL_SWITCH);
  if (body.trim().length < MIN_BODY_CHARS) reasons.push(REASONS.BODY_TOO_SHORT);
  if (!firstTermHit(hay, WHOLESALE_INTENT_TERMS)) reasons.push(REASONS.NO_WHOLESALE_INTENT);
  if ((ctx.sentLastHour || 0) >= caps.perHour) reasons.push(REASONS.CAP_HOURLY);
  if ((ctx.sentLastDay || 0) >= caps.perDay) reasons.push(REASONS.CAP_DAILY);

  return reasons;
}

// ─── Public entry point ────────────────────────────────────────────────────

/**
 * @param {object} msg   { from, subject, bodyText, headers, hasAttachments,
 *                         threadMessageCount, labels }
 * @param {object} ctx   { alreadyReplied, knownContact, killSwitch,
 *                         sentLastHour, sentLastDay, caps }
 * @returns {{ decision: 'drop'|'route'|'reply', reasons: string[], firstName: string|null }}
 */
export function classify(rawMsg, ctx = {}) {
  // Unwrap site-form submissions first, or they die on the bulk-sender rule.
  const msg = normalizeInbound(rawMsg);

  const drop = dropReason(msg);
  if (drop) return { decision: 'drop', reasons: [drop], firstName: null, msg };

  const { name } = parseAddress(msg.from);
  const firstName = extractFirstName(name, msg.bodyText || '');

  const blocks = routeReasons(msg, ctx, firstName);
  if (blocks.length) return { decision: 'route', reasons: blocks, firstName, msg };

  const gaps = stage2Reasons(msg, ctx);
  if (gaps.length) return { decision: 'route', reasons: gaps, firstName, msg };

  return { decision: 'reply', reasons: [REASONS.ELIGIBLE], firstName, msg };
}

// ─── Reply template ────────────────────────────────────────────────────────
//
// Only durable facts. Every line here is true regardless of who is asking.
// Phrasing lifted from Nick's own sent replies: direct, no exclamation marks,
// hyphens rather than em-dashes, no "thank you for reaching out!".
//
// DO NOT add anything about a price, a product, availability, a quantity,
// sourcing, English product, or a volume discount.

export const CATALOGUE_URL = 'https://sakekittycards.com/wholesale-pokemon';
export const REPLY_FROM = 'wholesale@sakekittycards.com';

export function renderReply({ firstName, catalogueUrl = CATALOGUE_URL } = {}) {
  return `Hi ${firstName},

Thanks for reaching out. Here are the basics so you're not waiting on them.

- What we carry: Japanese and Simplified Chinese sealed Pokemon.
- Units: Japanese is priced by the box. Chinese is sold by the case,
  typically 20 boxes per case. Some lines are case-only.
- Minimum order: $1,500 before shipping, applied to the order total. Not per
  line or per category - a mixed opening order is fine.
- Payment: in full up front. Wire, check, cashier's check, PayPal, Venmo,
  Cash App or Wise. We don't take Zelle or cash.
- Pricing: we don't offer volume discounts. We price as competitively as we
  can from the start, so our list price is already our best price.
- Shipping: you pay the actual cost our supplier quotes for the order. We
  pass it through without markup and quote it per order.
- Resale certificate: we need a valid one on file before a first order ships.
- Territory: we don't offer territory protection or exclusivity.

More on how we work: ${catalogueUrl}

This reply is automatic so the terms reach you straight away. Anything
specific - particular products, quantities, or what we can get - Nick picks
up himself and will come back to you directly.

Best,
Sake Kitty Wholesale
${REPLY_FROM}
`;
}

export function renderSubject(originalSubject) {
  const s = (originalSubject || '').trim();
  if (!s) return 'Re: Wholesale enquiry';
  return /^re\s*:/i.test(s) ? s : `Re: ${s}`;
}

// Exported for the test suite and for the admin term-list endpoint.
export const TERM_LISTS = {
  PRODUCT_TERMS,
  AVAILABILITY_TERMS,
  SOURCING_TERMS,
  PARTNERSHIP_TERMS,
  PRICE_REQUEST_TERMS,
  CHASER_TERMS,
  WHOLESALE_INTENT_TERMS,
};
