// Sake Kitty Square Worker
// Proxies calls to the Square API so the site never sees the access token.
// Also pulls per-variant mockup images from Printful and merges them into
// the /items response so the shop can swap photos on color/variant select.
// Additionally handles grading-prep submissions and tracker lookups backed
// by an Airtable "Submissions" table.
//
// Endpoints:
//   GET  /items            — list products from Square catalog (+ Printful mockups)
//   POST /checkout         — create a Square Payment Link from a cart
//   POST /grading/submit   — save a new grading-prep request to Airtable
//   GET  /grading/track    — fetch public status info for an order number
//   GET  /health           — liveness check
//
// Secrets: SQUARE_ACCESS_TOKEN, PRINTFUL_ACCESS_TOKEN, AIRTABLE_TOKEN
//          (set via `wrangler secret put <NAME>`)
// Vars:   SQUARE_ENV ("sandbox" | "production"), SQUARE_LOCATION_ID,
//         SQUARE_APPLICATION_ID, PRINTFUL_STORE_ID, AIRTABLE_BASE_ID,
//         AIRTABLE_TABLE_ID

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Max-Age': '86400',
};

const SQUARE_BASE = {
  sandbox:    'https://connect.squareupsandbox.com',
  production: 'https://connect.squareup.com',
};

// Square API version — pin to a known-good version so future Square updates
// don't silently break the worker. Bump intentionally when needed.
const SQUARE_API_VERSION = '2025-01-23';

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url  = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';
    const base = SQUARE_BASE[env.SQUARE_ENV] || SQUARE_BASE.sandbox;

    const squareHeaders = {
      'Square-Version': SQUARE_API_VERSION,
      'Authorization':  `Bearer ${env.SQUARE_ACCESS_TOKEN}`,
      'Content-Type':   'application/json',
    };

    try {
      if (path === '/health' && request.method === 'GET') {
        return json({ ok: true, env: env.SQUARE_ENV || 'sandbox' });
      }

      if (path === '/items' && request.method === 'GET') {
        return await listItems(base, squareHeaders, env.SQUARE_LOCATION_ID, env);
      }

      if (path === '/checkout' && request.method === 'POST') {
        const body = await request.json().catch(() => ({}));
        return await createCheckout(body, base, squareHeaders, env, url);
      }

      if (path === '/grading/submit' && request.method === 'POST') {
        const body = await request.json().catch(() => ({}));
        return await submitGradingRequest(body, env);
      }

      if (path === '/grading/track' && request.method === 'GET') {
        const order = (url.searchParams.get('order') || '').trim();
        return await trackGradingRequest(order, env);
      }

      // Dev-only: dump raw catalog for inspection.
      if (path === '/dev/raw' && request.method === 'GET') {
        if (env.SQUARE_ENV !== 'sandbox') return json({ error: 'disabled outside sandbox' }, 403);
        const r = await fetch(`${base}/v2/catalog/list?types=ITEM`, { headers: squareHeaders });
        return json(await r.json());
      }

      // Dev-only: delete every ITEM in the catalog. Sandbox only.
      if (path === '/dev/cleanup' && request.method === 'GET') {
        if (env.SQUARE_ENV !== 'sandbox') return json({ error: 'disabled outside sandbox' }, 403);
        return await cleanupAllItems(base, squareHeaders);
      }

      // Dev-only seeder: creates a test product. Disabled in production.
      if (path === '/dev/seed' && request.method === 'GET') {
        if (env.SQUARE_ENV !== 'sandbox') {
          return json({ error: 'seed endpoint disabled outside sandbox' }, 403);
        }
        return await seedTestItem(base, squareHeaders, env.SQUARE_LOCATION_ID);
      }

      return json({ error: 'not found', path }, 404);
    } catch (err) {
      return json({ error: err.message || String(err) }, 500);
    }
  },
};

// ─── Handlers ──────────────────────────────────────────────────────────────

async function listItems(base, headers, locationId, env) {
  // Square catalog and Printful mockups fetched in parallel.
  const [squareRes, printfulMockups] = await Promise.all([
    fetch(`${base}/v2/catalog/list?types=ITEM,IMAGE`, { headers }).then(r => r.json().then(d => [r, d])),
    fetchPrintfulVariantImages(env).catch(() => ({})),  // fail open
  ]);
  const [res, data] = squareRes;
  if (!res.ok) return json({ error: 'square_api_error', detail: data }, res.status);

  const objects = data.objects || [];
  const images  = Object.fromEntries(
    objects.filter(o => o.type === 'IMAGE').map(o => [o.id, o.image_data?.url])
  );

  const catalogItems = objects.filter(o => o.type === 'ITEM');

  // Collect every variation ID across all items for one batch inventory call.
  const allVariationIds = catalogItems
    .flatMap(o => (o.item_data?.variations || []).map(v => v.id))
    .filter(Boolean);
  const stockCounts = await fetchStockCounts(base, headers, allVariationIds, locationId);

  const items = catalogItems
    .map(o => {
      const squareHero = images[o.item_data?.image_ids?.[0]] || null;

      const variations = (o.item_data?.variations || [])
        .map(v => {
          const vd    = v.item_variation_data;
          const cents = vd?.price_money?.amount;
          if (cents == null) return null;
          // Prefer Printful mockup (has the logo printed), fall back to per-variation
          // image in Square (rare), then to null.
          const printfulImg = printfulMockups[v.id] || null;
          const squareVarImg = vd?.image_ids?.[0] ? (images[vd.image_ids[0]] || null) : null;
          return {
            id:       v.id,
            name:     vd?.name || '',
            price:    cents / 100,
            inStock:  !(v.id in stockCounts) || stockCounts[v.id] > 0,
            imageUrl: printfulImg || squareVarImg || null,
          };
        })
        .filter(Boolean);

      if (!variations.length) return null;

      // Top-level fields point to the first in-stock variation for backward compat.
      const primary = variations.find(v => v.inStock) || variations[0];

      // Product gallery: dedupped Square item images + any variation (Printful) mockups.
      const seen = new Set();
      const imageUrls = [
        ...(o.item_data?.image_ids || []).map(id => images[id]).filter(Boolean),
        ...variations.map(v => v.imageUrl).filter(Boolean),
      ].filter(u => { if (!u || seen.has(u)) return false; seen.add(u); return true; });

      // Top-level imageUrl prefers the primary variation's Printful mockup when available,
      // so the grid shows the default color's printed shot.
      const imageUrl = primary.imageUrl || squareHero;

      return {
        id:          o.id,
        variationId: primary.id,
        name:        o.item_data?.name || '',
        description: o.item_data?.description || '',
        price:       primary.price,
        currency:    o.item_data?.variations?.[0]?.item_variation_data?.price_money?.currency || 'USD',
        imageUrl,
        imageUrls,
        categoryId:  o.item_data?.category_id || null,
        inStock:     variations.some(v => v.inStock),
        variations,
      };
    })
    .filter(Boolean);

  return json({ items });
}

// Fetch all Printful sync products for the store, then each product's variants,
// and build a map of { squareVariationId: printfulMockupUrl }.
// Returns {} on any failure so the /items endpoint still works without Printful.
//
// Cached in Cloudflare's edge cache for 5 minutes so shop page views don't
// trigger 7+ Printful API calls per request.
async function fetchPrintfulVariantImages(env) {
  const token   = env.PRINTFUL_ACCESS_TOKEN;
  const storeId = env.PRINTFUL_STORE_ID;
  if (!token || !storeId) return {};

  const cacheKey = new Request('https://internal.cache/printful-mockups/v1');
  const cached   = await caches.default.match(cacheKey);
  if (cached) {
    try { return await cached.json(); } catch {}
  }

  const pfHeaders = {
    'Authorization': `Bearer ${token}`,
    'X-PF-Store-Id': String(storeId),
  };

  // List sync products (enough to know their IDs; variants come from the per-product call).
  const listRes = await fetch('https://api.printful.com/sync/products?limit=100', { headers: pfHeaders });
  if (!listRes.ok) return {};
  const listData = await listRes.json();
  const products = Array.isArray(listData.result) ? listData.result : [];

  // Fetch per-product details in parallel (each returns sync_variants with external_id + files).
  const details = await Promise.all(products.map(async p => {
    try {
      const r = await fetch(`https://api.printful.com/sync/products/${p.id}`, { headers: pfHeaders });
      if (!r.ok) return null;
      const d = await r.json();
      return d.result;
    } catch { return null; }
  }));

  const map = {};
  for (const d of details) {
    const variants = d?.sync_variants || [];
    for (const v of variants) {
      // external_id is the Square variation ID.
      const squareVarId = v.external_id;
      if (!squareVarId) continue;

      // Prefer the "preview" file (branded mockup with the logo printed on the garment).
      // Fall back to product.image (plain Printful catalog shot of that color).
      const preview = (v.files || []).find(f => f.type === 'preview');
      const url = preview?.preview_url || v.product?.image || null;
      if (url) map[squareVarId] = url;
    }
  }

  // Cache at the edge for 5 min. Long enough to absorb traffic bursts,
  // short enough that Printful edits show up within minutes.
  const cacheResponse = new Response(JSON.stringify(map), {
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=300' },
  });
  await caches.default.put(cacheKey, cacheResponse);
  return map;
}

async function fetchStockCounts(base, headers, variationIds, locationId) {
  if (variationIds.length === 0) return {};
  const res = await fetch(`${base}/v2/inventory/counts/batch-retrieve`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      catalog_object_ids: variationIds,
      location_ids:       [locationId],
      states:             ['IN_STOCK'],
    }),
  });
  const data = await res.json();
  if (!res.ok) return {};  // fail open — treat all as in-stock if inventory API hiccups
  const out = {};
  for (const count of data.counts || []) {
    if (count.state === 'IN_STOCK' && count.location_id === locationId) {
      out[count.catalog_object_id] = Number(count.quantity) || 0;
    }
  }
  return out;
}

async function createCheckout(body, base, headers, env, reqUrl) {
  const items        = Array.isArray(body.items) ? body.items : [];
  const shippingCost = Number(body.shippingCost) || 0;
  const buyerNote    = typeof body.note === 'string' ? body.note.slice(0, 500) : '';
  const returnUrl    = typeof body.returnUrl === 'string' && body.returnUrl.startsWith('http')
    ? body.returnUrl
    : 'https://sakekittycards.com/order-confirmation.html';

  if (items.length === 0) return json({ error: 'items array is required' }, 400);

  const lineItems = items.map((item) => {
    const quantity = String(Math.max(1, parseInt(item.quantity, 10) || 1));
    if (item.variationId) {
      // Reference the Square catalog variation — Square pulls name + price from catalog.
      // This is what Printful's order sync watches for to trigger fulfillment.
      return { catalog_object_id: String(item.variationId), quantity };
    }
    // Fallback for any ad-hoc item without a catalog ID.
    const name  = String(item.name || 'Item').slice(0, 500);
    const cents = Math.round(Number(item.price) * 100);
    if (!Number.isFinite(cents) || cents <= 0) throw new Error(`invalid price for ${name}`);
    return { name, quantity, base_price_money: { amount: cents, currency: 'USD' } };
  });

  if (shippingCost > 0) {
    lineItems.push({
      name: 'Shipping',
      quantity: '1',
      base_price_money: { amount: Math.round(shippingCost * 100), currency: 'USD' },
    });
  }

  const payload = {
    idempotency_key: crypto.randomUUID(),
    order: {
      location_id: env.SQUARE_LOCATION_ID,
      line_items:  lineItems,
    },
    checkout_options: {
      allow_tipping:           false,
      ask_for_shipping_address: true,
      redirect_url:             returnUrl,
    },
  };
  if (buyerNote) payload.pre_populated_data = { buyer_note: buyerNote };

  const res  = await fetch(`${base}/v2/online-checkout/payment-links`, {
    method: 'POST',
    headers,
    body:   JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) return json({ error: 'square_api_error', detail: data }, res.status);

  return json({
    url:       data.payment_link?.url,
    id:        data.payment_link?.id,
    orderId:   data.payment_link?.order_id,
    createdAt: data.payment_link?.created_at,
  });
}

async function seedTestItem(base, headers, locationId) {
  // Step 1 — create the item + variation.
  const createPayload = {
    idempotency_key: crypto.randomUUID(),
    object: {
      type: 'ITEM',
      id: '#pikachu_plush',
      item_data: {
        name: 'Pikachu Plush',
        description: 'Test plush for cart development — remove before production.',
        variations: [{
          type: 'ITEM_VARIATION',
          id: '#pikachu_plush_regular',
          item_variation_data: {
            item_id: '#pikachu_plush',
            name: 'Regular',
            pricing_type: 'FIXED_PRICING',
            price_money: { amount: 2500, currency: 'USD' },
          },
        }],
      },
    },
  };
  const createRes = await fetch(`${base}/v2/catalog/object`, {
    method: 'POST', headers, body: JSON.stringify(createPayload),
  });
  const createData = await createRes.json();
  if (!createRes.ok) return json({ error: 'square_api_error', detail: createData }, createRes.status);

  const item      = createData.catalog_object;
  const variation = item?.item_data?.variations?.[0];
  if (!variation) return json({ error: 'no variation returned by create', detail: createData }, 500);

  // Step 2 — set inventory count to 0 at the location. This is Square's
  // real "sold out" signal; location_overrides.sold_out is silently dropped.
  const invRes = await fetch(`${base}/v2/inventory/changes/batch-create`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      idempotency_key: crypto.randomUUID(),
      changes: [{
        type: 'PHYSICAL_COUNT',
        physical_count: {
          catalog_object_id: variation.id,
          state:       'IN_STOCK',
          location_id: locationId,
          quantity:    '0',
          occurred_at: new Date().toISOString(),
        },
      }],
    }),
  });
  const invData = await invRes.json();
  if (!invRes.ok) return json({ error: 'inventory_api_error', detail: invData }, invRes.status);

  return json({
    ok:       true,
    itemId:   item.id,
    itemName: item.item_data?.name,
    soldOut:  true,
    message:  'test product created with 0 inventory — hit /items to verify inStock:false',
  });
}

async function cleanupAllItems(base, headers) {
  const listRes = await fetch(`${base}/v2/catalog/list?types=ITEM`, { headers });
  const listData = await listRes.json();
  if (!listRes.ok) return json({ error: 'square_api_error', detail: listData }, listRes.status);

  const ids = (listData.objects || []).map(o => o.id);
  if (ids.length === 0) return json({ ok: true, deleted: 0, message: 'catalog already empty' });

  const delRes = await fetch(`${base}/v2/catalog/batch-delete`, {
    method: 'POST', headers, body: JSON.stringify({ object_ids: ids }),
  });
  const delData = await delRes.json();
  if (!delRes.ok) return json({ error: 'square_api_error', detail: delData }, delRes.status);

  return json({ ok: true, deleted: ids.length, ids });
}

// ─── Grading-prep: Airtable-backed submissions + tracker ───────────────────

// Generate a human-friendly order number. Format: SK-<YYYY>-<6 random chars>
// Char set excludes 0/O/1/I to prevent confusion over the phone / email.
const ORDER_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
function generateOrderNumber() {
  const year = new Date().getUTCFullYear();
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  let suffix = '';
  for (const b of bytes) suffix += ORDER_CHARS[b % ORDER_CHARS.length];
  return `SK-${year}-${suffix}`;
}

async function submitGradingRequest(body, env) {
  if (!env.AIRTABLE_TOKEN || !env.AIRTABLE_BASE_ID || !env.AIRTABLE_TABLE_ID) {
    return json({ error: 'grading_store_not_configured' }, 500);
  }

  const name  = String(body.name  || '').trim();
  const email = String(body.email || '').trim();
  if (!name || !email) return json({ error: 'name_and_email_required' }, 400);

  const phone = String(body.phone || '').trim();
  const notes = String(body.notes || '').trim();
  const tier  = String(body.tier  || '').trim();
  const cards = Array.isArray(body.cards) ? body.cards : [];
  if (cards.length === 0) return json({ error: 'no_cards' }, 400);

  const cardCount = cards.length;
  const totalCost = Number(body.totalCost) || 0;

  const orderNumber = generateOrderNumber();
  // Store the full card list as a JSON blob so the tracker can render the
  // exact cards submitted. Each card: { name, set, num, svc, prep, img }.
  const cardsJson = JSON.stringify(cards);

  const payload = {
    fields: {
      'Order Number':      orderNumber,
      'Customer Name':     name,
      'Customer Email':    email,
      'Customer Phone':    phone,
      'Notes':             notes,
      'Tier':              tier || undefined,  // don't send empty, Airtable rejects unknown select
      'Cards':             cardsJson,
      'Card Count':        cardCount,
      'Total Cost':        totalCost,
      'Status':            'Received by Sake Kitty',
    },
  };

  const res = await fetch(
    `https://api.airtable.com/v0/${env.AIRTABLE_BASE_ID}/${env.AIRTABLE_TABLE_ID}`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${env.AIRTABLE_TOKEN}`,
        'Content-Type':  'application/json',
      },
      body: JSON.stringify(payload),
    }
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return json({ error: 'airtable_error', detail: data }, res.status);
  }

  return json({
    ok:          true,
    orderNumber,
    status:      'Received by Sake Kitty',
  });
}

async function trackGradingRequest(order, env) {
  if (!env.AIRTABLE_TOKEN || !env.AIRTABLE_BASE_ID || !env.AIRTABLE_TABLE_ID) {
    return json({ error: 'grading_store_not_configured' }, 500);
  }
  if (!/^SK-\d{4}-[A-Z0-9]{4,10}$/.test(order)) {
    return json({ error: 'invalid_order_number' }, 400);
  }

  // Airtable filter — escape quotes by doubling, per their formula syntax.
  const safe = order.replace(/"/g, '""');
  const filter = encodeURIComponent(`{Order Number} = "${safe}"`);
  const url = `https://api.airtable.com/v0/${env.AIRTABLE_BASE_ID}/${env.AIRTABLE_TABLE_ID}?filterByFormula=${filter}&maxRecords=1`;

  const res = await fetch(url, {
    headers: { 'Authorization': `Bearer ${env.AIRTABLE_TOKEN}` },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return json({ error: 'airtable_error', detail: data }, res.status);
  }

  const record = (data.records || [])[0];
  if (!record) return json({ error: 'not_found' }, 404);

  const f = record.fields || {};
  // Mask the customer name to first-name-only for privacy, in case someone
  // tries order numbers by guessing.
  const firstName = String(f['Customer Name'] || '').split(/\s+/)[0] || '';
  let cards = [];
  try { cards = JSON.parse(f['Cards'] || '[]'); } catch {}
  let certs = [];
  try { certs = JSON.parse(f['PSA Cert Numbers'] || '[]'); } catch {}

  return json({
    orderNumber:  f['Order Number'] || order,
    customerName: firstName,
    tier:         f['Tier']   || null,
    status:       f['Status'] || 'Received by Sake Kitty',
    cardCount:    f['Card Count'] || cards.length,
    cards,
    psaSubmission: f['PSA Submission #'] || null,
    psaCerts:     certs,
    createdTime:  record.createdTime,
  });
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  });
}
