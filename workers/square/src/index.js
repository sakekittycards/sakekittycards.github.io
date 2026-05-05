// Sake Kitty Square Worker
// Proxies calls to the Square API so the site never sees the access token.
// Also pulls per-variant mockup images from Printful and merges them into
// the /items response so the shop can swap photos on color/variant select.
// Additionally handles grading-prep submissions and tracker lookups backed
// by an Airtable "Submissions" table.
// Finally, accepts webhooks from Square when an order is paid, and
// submits the order directly to Printful via API (bypassing Printful's
// Square integration, which only syncs Square Online orders — not
// Payment Link API orders).
//
// Endpoints:
//   GET  /items              — list products from Square catalog (+ Printful mockups)
//   POST /checkout           — create a Square Payment Link from a cart
//   POST /grading/submit     — save a new grading-prep request to Airtable
//   GET  /grading/track      — fetch public status info for an order number
//   POST /webhooks/square    — handle Square order.updated / payment.updated events
//   POST /admin/upload-graded — bulk-create graded-card listings (admin only)
//   GET  /health             — liveness check
//
// Secrets: SQUARE_ACCESS_TOKEN, PRINTFUL_ACCESS_TOKEN, AIRTABLE_TOKEN,
//          SQUARE_WEBHOOK_SIGNATURE_KEY, ADMIN_TOKEN
//          (all set via `wrangler secret put <NAME>`)
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

      if (path === '/webhooks/square' && request.method === 'POST') {
        return await handleSquareWebhook(request, base, squareHeaders, env);
      }

      if (path === '/admin/upload-graded' && request.method === 'POST') {
        return await uploadGradedItem(request, base, squareHeaders, env);
      }

      if (path === '/admin/update-graded' && request.method === 'POST') {
        return await updateGradedItem(request, base, squareHeaders, env);
      }

      if (path === '/admin/update-graded-price' && request.method === 'POST') {
        return await updateGradedPrice(request, base, squareHeaders, env);
      }

      if (path === '/admin/replace-graded-images' && request.method === 'POST') {
        return await replaceGradedImages(request, base, squareHeaders, env);
      }

      if (path === '/admin/delete-item' && request.method === 'POST') {
        return await adminDeleteItem(request, base, squareHeaders, env);
      }

      // Public endpoint — let the gift-cards page check a balance from
      // a customer-typed code without redirecting to Square.
      if (path === '/gift-card/balance' && request.method === 'POST') {
        return await checkGiftCardBalance(request, base, squareHeaders, env);
      }

      // Diagnostic: fetch a single Square catalog item by id, OR list all
      // objects of a given type (?types=TAX). Admin-token gated.
      if (path === '/admin/inspect' && request.method === 'GET') {
        const token = request.headers.get('X-Sake-Admin-Token') || '';
        if (!env.ADMIN_TOKEN || !timingSafeEqual(token, env.ADMIN_TOKEN)) {
          return json({ error: 'unauthorized' }, 401);
        }
        const id = url.searchParams.get('id');
        const types = url.searchParams.get('types');
        if (id) {
          const r = await fetch(
            `${base}/v2/catalog/object/${encodeURIComponent(id)}?include_related_objects=true`,
            { headers: squareHeaders },
          );
          return json(await r.json(), r.status);
        }
        if (types) {
          // Pass through Square's pagination cursor so callers can walk
          // catalogs larger than one page (Square default = 100 / page).
          const cursor = url.searchParams.get('cursor') || '';
          const upstream = `${base}/v2/catalog/list?types=${encodeURIComponent(types)}`
            + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : '');
          const r = await fetch(upstream, { headers: squareHeaders });
          return json(await r.json(), r.status);
        }
        return json({ error: 'missing id or types' }, 400);
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

  // Square's catalog/list does NOT include images that were uploaded
  // attached to a specific item (object_id set). Those only come back
  // via batch-retrieve-objects. Collect every referenced image_id, drop
  // the ones we already have, then batch-fetch the rest.
  const referencedImageIds = new Set();
  for (const o of catalogItems) {
    for (const id of o.item_data?.image_ids || []) referencedImageIds.add(id);
    for (const v of o.item_data?.variations || []) {
      for (const id of v.item_variation_data?.image_ids || []) referencedImageIds.add(id);
    }
  }
  const missingImageIds = [...referencedImageIds].filter(id => !(id in images));
  if (missingImageIds.length > 0) {
    try {
      const r = await fetch(`${base}/v2/catalog/batch-retrieve`, {
        method: 'POST', headers,
        body: JSON.stringify({ object_ids: missingImageIds }),
      });
      const j = await r.json();
      for (const o of (j.objects || [])) {
        if (o.type === 'IMAGE') images[o.id] = o.image_data?.url;
      }
    } catch (_e) {
      // fail-open: items without images still render via emoji fallback on the shop
    }
  }

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

// Sale-tax nexus map. Add states + rates here as nexus expands.
// Florida uses the state base only (6%); county discretionary surtax
// varies destination-by-destination and we eat that small delta rather
// than risk over-charging buyers. Migrate to Square's auto-tax or a
// per-county lookup when volume justifies it.
const SALES_TAX_BY_STATE = {
  FL: { name: 'Florida Sales Tax', percentage: '6.0' },
};

async function createCheckout(body, base, headers, env, reqUrl) {
  const items         = Array.isArray(body.items) ? body.items : [];
  const shippingCost  = Number(body.shippingCost) || 0;
  // Mandatory shipping insurance, computed on the client side per the
  // graded/raw/sealed-only rules in main.js. Falls back to 0 for any
  // older client that doesn't send it.
  const insuranceCost = Number(body.insuranceCost) || 0;
  const buyerNote     = typeof body.note === 'string' ? body.note.slice(0, 500) : '';
  const returnUrl    = typeof body.returnUrl === 'string' && body.returnUrl.startsWith('http')
    ? body.returnUrl
    : 'https://sakekittycards.com/order-confirmation.html';

  // Buyer selects their shipping state in the cart drawer before checkout.
  // Square Payment Links don't auto-apply catalog taxes (that's a Square
  // Online feature), so we inject the tax server-side based on the state.
  const shippingState = typeof body.shippingState === 'string'
    ? body.shippingState.trim().toUpperCase()
    : '';
  const taxRule = SALES_TAX_BY_STATE[shippingState] || null;

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

  if (insuranceCost > 0) {
    lineItems.push({
      name: 'Shipping insurance',
      quantity: '1',
      base_price_money: { amount: Math.round(insuranceCost * 100), currency: 'USD' },
    });
  }

  const order = {
    location_id: env.SQUARE_LOCATION_ID,
    line_items:  lineItems,
    // Pre-declare a SHIPMENT fulfillment so Square attaches the
    // shipping address collected at checkout to the order as a proper
    // fulfillment. Printful's Square integration only syncs orders
    // that have a SHIPMENT fulfillment — without this placeholder,
    // the address ends up on the Customer record but not on the order,
    // and Printful silently ignores the order.
    fulfillments: [{
      type: 'SHIPMENT',
      state: 'PROPOSED',
    }],
  };

  if (taxRule) {
    // ORDER-scoped ADDITIVE tax: Square applies it to every line item
    // including shipping, then shows it as a separate "Florida Sales Tax"
    // line on the hosted checkout page.
    order.taxes = [{
      uid:        'sk-state-tax',
      name:       taxRule.name,
      type:       'ADDITIVE',
      percentage: taxRule.percentage,
      scope:      'ORDER',
    }];
  }

  const payload = {
    idempotency_key: crypto.randomUUID(),
    order,
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

  // Status is left empty on create; the tracker interprets empty/null as
  // "Request Submitted" (step 1 — form submitted but cards not yet in hand).
  // Nick sets Status to "Received by Sake Kitty Cards" manually once the
  // cards physically arrive, which moves the tracker to step 2.
  const payload = {
    fields: {
      'Order Number':      orderNumber,
      'Customer Name':     name,
      'Customer Email':    email,
      'Customer Phone':    phone,
      'Notes':             notes,
      'Tier':              tier || undefined,
      'Cards':             cardsJson,
      'Card Count':        cardCount,
      'Total Cost':        totalCost,
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
    status:      'Request Submitted',
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
    status:       f['Status'] || 'Request Submitted',
    cardCount:    f['Card Count'] || cards.length,
    cards,
    psaSubmission: f['PSA Submission #'] || null,
    psaCerts:     certs,
    createdTime:  record.createdTime,
  });
}

// ─── Square → Printful order relay (via webhook) ──────────────────────────

// Square fires webhooks when orders and payments change state. When an
// order reaches a fully-paid state and has a SHIPMENT fulfillment with a
// recipient address, we submit it to Printful via their /orders API. This
// bypasses Printful's built-in Square integration, which only syncs orders
// created through Square Online (not Payment Link API orders).
async function handleSquareWebhook(request, base, headers, env) {
  const rawBody = await request.text();
  const sig = request.headers.get('x-square-hmacsha256-signature') || '';

  // Square signs: HMAC-SHA256(signatureKey, notificationUrl + rawBody), base64.
  const notificationUrl = 'https://sakekitty-square.nwilliams23999.workers.dev/webhooks/square';
  const expected = await computeHmacSha256Base64(env.SQUARE_WEBHOOK_SIGNATURE_KEY, notificationUrl + rawBody);
  if (!timingSafeEqual(sig, expected)) {
    return new Response('invalid signature', { status: 401 });
  }

  let event;
  try { event = JSON.parse(rawBody); } catch { return new Response('bad json', { status: 400 }); }

  const type = event?.type;
  const squareOrderId =
    event?.data?.object?.order?.id ||
    event?.data?.object?.payment?.order_id ||
    null;
  if (!squareOrderId) return new Response('no order id', { status: 200 });

  // We only care about events that mean "this order is now paid / worth
  // relaying." order.updated fires for many state changes; we re-check the
  // order state after fetching. payment.updated is the stronger signal.
  if (type !== 'order.updated' && type !== 'payment.updated') {
    return new Response('ignored', { status: 200 });
  }

  // Fetch full order.
  const orderRes = await fetch(`${base}/v2/orders/${squareOrderId}`, { headers });
  const orderJson = await orderRes.json().catch(() => ({}));
  if (!orderRes.ok || !orderJson.order) return new Response('order fetch failed', { status: 200 });
  const order = orderJson.order;

  // Guard: don't relay if not paid, no shipment, or missing address.
  const paid = (order.total_money?.amount || 0) > 0 &&
               ((order.tenders || []).length > 0 ||
                order.state === 'COMPLETED' ||
                (order.net_amount_due_money?.amount ?? 1) === 0);
  if (!paid) return new Response('not paid yet', { status: 200 });

  const shipment = (order.fulfillments || []).find(f => f.type === 'SHIPMENT');
  const recipient = shipment?.shipment_details?.recipient;
  if (!recipient?.address) return new Response('no shipping address', { status: 200 });

  // Idempotency: if we've already submitted this Square order to Printful,
  // skip. Printful's /orders supports search by external_id.
  const existing = await printfulFindOrderByExternalId(squareOrderId, env);
  if (existing) return new Response('already relayed', { status: 200 });

  // Map Square catalog_object_id → Printful sync_variant_id.
  const variantMap = await fetchPrintfulSyncVariantIdMap(env);

  const pfItems = (order.line_items || [])
    .map(li => {
      const syncVariantId = variantMap[li.catalog_object_id];
      if (!syncVariantId) return null;  // e.g., the "Shipping" line has no catalog id
      return {
        sync_variant_id: syncVariantId,
        quantity: parseInt(li.quantity, 10) || 1,
      };
    })
    .filter(Boolean);

  if (pfItems.length === 0) return new Response('no printable items', { status: 200 });

  const pfBody = {
    external_id: squareOrderId,
    shipping: 'STANDARD',
    recipient: {
      name:         recipient.display_name || [recipient.address.first_name, recipient.address.last_name].filter(Boolean).join(' '),
      email:        recipient.email_address || '',
      phone:        recipient.phone_number || '',
      address1:     recipient.address.address_line_1 || '',
      address2:     recipient.address.address_line_2 || '',
      city:         recipient.address.locality || '',
      state_code:   recipient.address.administrative_district_level_1 || '',
      country_code: recipient.address.country || 'US',
      zip:          recipient.address.postal_code || '',
    },
    items: pfItems,
  };

  // Create & confirm in one call. `confirm=true` skips the draft step and
  // sends the order straight to fulfillment.
  const pfRes = await fetch('https://api.printful.com/orders?confirm=true', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.PRINTFUL_ACCESS_TOKEN}`,
      'X-PF-Store-Id': String(env.PRINTFUL_STORE_ID),
      'Content-Type':  'application/json',
    },
    body: JSON.stringify(pfBody),
  });
  const pfData = await pfRes.json().catch(() => ({}));
  if (!pfRes.ok) {
    // Log and still 200 so Square doesn't retry forever. We can investigate
    // via worker logs.
    console.log('PRINTFUL_ORDER_FAIL', squareOrderId, pfRes.status, JSON.stringify(pfData));
    return new Response('printful error (logged)', { status: 200 });
  }

  console.log('PRINTFUL_ORDER_OK', squareOrderId, '→ printful#' + (pfData.result?.id || '?'));
  return new Response('ok', { status: 200 });
}

// Look up a map of {squareVariationId: printfulSyncVariantId} across all
// sync products. Uses the edge cache for 10 min.
// Admin: bulk-create a graded-card listing in Square.
// Auth: X-Sake-Admin-Token header must match env.ADMIN_TOKEN secret.
// Body: {
//   card: { cert_number, card_number, name, set_name, year, grade,
//           pokemontcg_set_id, offer_min },
//   price_cents: integer,
//   image_base64: string (raw base64, no data: prefix),
//   image_filename: string (e.g. "pikachu-cert152270300-front.jpg")
// }
// Response: { ok, item_id, variation_id, image_id, listing_url }
async function uploadGradedItem(request, base, squareHeaders, env) {
  const provided = request.headers.get('X-Sake-Admin-Token') || '';
  if (!env.ADMIN_TOKEN) {
    return json({ error: 'admin_token_not_configured' }, 500);
  }
  if (!timingSafeEqual(provided, env.ADMIN_TOKEN)) {
    return json({ error: 'unauthorized' }, 401);
  }

  let body;
  try {
    body = await request.json();
  } catch (_err) {
    return json({ error: 'invalid_json' }, 400);
  }

  const card = body.card || {};
  const priceCents = Number(body.price_cents);
  const imageB64 = body.image_base64 || '';
  const imageFilename = body.image_filename || `graded-${card.cert_number || 'unknown'}.jpg`;
  const backB64 = body.back_image_base64 || '';
  const backFilename = body.back_image_filename || `graded-${card.cert_number || 'unknown'}-back.jpg`;

  if (!card.cert_number || !card.name) {
    return json({ error: 'missing_required_fields', required: ['card.cert_number', 'card.name'] }, 400);
  }
  if (!Number.isFinite(priceCents) || priceCents <= 0) {
    return json({ error: 'invalid_price_cents' }, 400);
  }
  if (!imageB64) {
    return json({ error: 'missing_image_base64' }, 400);
  }

  // Title: lead with the grade (buyers scan grade first), then year, set,
  // card name, number. Strip descriptors like "GEM MT" / "MINT" — keep just
  // "PSA 10" / "PSA 9".
  const gradeNum = card.grade
    ? (card.grade.match(/\b(\d{1,2})\b/) || [])[1] || ''
    : '';
  const titleParts = [];
  if (gradeNum)         titleParts.push(`PSA ${gradeNum}`);
  if (card.year)        titleParts.push(card.year);
  if (card.set_name)    titleParts.push(card.set_name);
  if (card.name)        titleParts.push(card.name);
  if (card.card_number) titleParts.push(`#${card.card_number}`);
  const title = titleParts.join(' ').trim();

  const descriptionLines = [
    `PSA Cert #: ${card.cert_number}`,
  ];
  if (card.set_name)    descriptionLines.push(`Set: ${card.set_name}${card.year ? ` (${card.year})` : ''}`);
  if (card.grade)       descriptionLines.push(`Grade: PSA ${card.grade}`);
  if (card.card_number) descriptionLines.push(`Card Number: ${card.card_number}`);
  descriptionLines.push('Verify cert at psacard.com before purchase.');
  const description = descriptionLines.join('\n');

  // 1. Create the catalog item + single ITEM_VARIATION (qty 1, fixed price).
  // Idempotency: UUID so re-uploads with changed metadata (price, title)
  // succeed. Trade-off: a script crash mid-flight could leave a phantom
  // item in Square — user can delete via dashboard.
  const itemPlaceholder = `#sk-graded-${card.cert_number}`;
  const variationPlaceholder = `#sk-graded-var-${card.cert_number}`;
  const createPayload = {
    idempotency_key: crypto.randomUUID(),
    object: {
      type: 'ITEM',
      id: itemPlaceholder,
      item_data: {
        name: title.slice(0, 255),
        description: description.slice(0, 4096),
        // Explicitly taxable so Square applies the FL sales tax rule we
        // set up in Dashboard. Default is already true, but pinning it
        // here guards against future Square API changes.
        is_taxable: true,
        variations: [{
          type: 'ITEM_VARIATION',
          id: variationPlaceholder,
          item_variation_data: {
            item_id: itemPlaceholder,
            name: 'Single',
            pricing_type: 'FIXED_PRICING',
            price_money: { amount: Math.round(priceCents), currency: 'USD' },
            track_inventory: true,
            sellable: true,
            stockable: true,
          },
        }],
      },
    },
  };
  const createRes = await fetch(`${base}/v2/catalog/object`, {
    method: 'POST', headers: squareHeaders, body: JSON.stringify(createPayload),
  });
  const createData = await createRes.json();
  if (!createRes.ok) {
    return json({ error: 'square_create_failed', detail: createData }, createRes.status);
  }
  const item = createData.catalog_object;
  const variation = item?.item_data?.variations?.[0];
  if (!item || !variation) {
    return json({ error: 'square_create_returned_no_variation', detail: createData }, 500);
  }

  // 2. Set inventory to 1 — graded cards are unique, qty 1.
  // Use a fresh UUID each call: occurred_at changes per attempt, and Square
  // rejects identical idempotency keys whose body has shifted.
  const invRes = await fetch(`${base}/v2/inventory/changes/batch-create`, {
    method: 'POST', headers: squareHeaders,
    body: JSON.stringify({
      idempotency_key: crypto.randomUUID(),
      changes: [{
        type: 'PHYSICAL_COUNT',
        physical_count: {
          catalog_object_id: variation.id,
          state: 'IN_STOCK',
          location_id: env.SQUARE_LOCATION_ID,
          quantity: '1',
          occurred_at: new Date().toISOString(),
        },
      }],
    }),
  });
  if (!invRes.ok) {
    // Don't bail — log and keep going so the image still uploads. Inventory
    // count is fixable in the Square dashboard but a missing image is
    // visually broken on the shop and harder to recover.
    const invData = await invRes.json().catch(() => ({}));
    console.warn('inventory step failed (continuing):', JSON.stringify(invData));
  }

  // 3. Upload + attach the listing image. Square wants multipart/form-data
  // with a JSON 'request' part and a binary 'image_file' part.
  const imageBytes = base64ToBytes(imageB64);
  const imageRequest = {
    idempotency_key: crypto.randomUUID(),
    object_id: item.id,
    image: {
      type: 'IMAGE',
      // Square requires a non-blank id for new objects; use a #-prefixed
      // temp ID and Square assigns the real one on create.
      id: `#sk-graded-img-${card.cert_number}-${Date.now()}`,
      image_data: {
        name: imageFilename.slice(0, 255),
        caption: 'Sake Kitty Cards graded listing',
      },
    },
    is_primary: true,
  };
  const fd = new FormData();
  fd.append(
    'request',
    new Blob([JSON.stringify(imageRequest)], { type: 'application/json' }),
  );
  fd.append(
    'image_file',
    new Blob([imageBytes], { type: 'image/jpeg' }),
    imageFilename,
  );
  // Strip the JSON Content-Type from squareHeaders so fetch sets multipart boundary.
  const imageHeaders = {
    'Square-Version': SQUARE_API_VERSION,
    'Authorization': `Bearer ${env.SQUARE_ACCESS_TOKEN}`,
  };
  const imgRes = await fetch(`${base}/v2/catalog/images`, {
    method: 'POST', headers: imageHeaders, body: fd,
  });
  const imgData = await imgRes.json();
  if (!imgRes.ok) {
    return json({
      error: 'square_image_upload_failed',
      item_id: item.id,
      detail: imgData,
    }, imgRes.status);
  }

  // 4. Optional back image — uploaded with is_primary: false so the
  // front stays as the gallery hero. Best-effort: log + continue on failure.
  let backImageId = null;
  if (backB64) {
    try {
      const backBytes = base64ToBytes(backB64);
      const backRequest = {
        idempotency_key: crypto.randomUUID(),
        object_id: item.id,
        image: {
          type: 'IMAGE',
          id: `#sk-graded-img-${card.cert_number}-back-${Date.now()}`,
          image_data: {
            name: backFilename.slice(0, 255),
            caption: 'Sake Kitty Cards graded listing — back',
          },
        },
        is_primary: false,
      };
      const fdBack = new FormData();
      fdBack.append(
        'request',
        new Blob([JSON.stringify(backRequest)], { type: 'application/json' }),
      );
      fdBack.append(
        'image_file',
        new Blob([backBytes], { type: 'image/jpeg' }),
        backFilename,
      );
      const backRes = await fetch(`${base}/v2/catalog/images`, {
        method: 'POST', headers: imageHeaders, body: fdBack,
      });
      const backData = await backRes.json();
      if (backRes.ok) {
        backImageId = backData.image?.id || null;
      } else {
        console.warn('back image upload failed (continuing):', JSON.stringify(backData));
      }
    } catch (e) {
      console.warn('back image upload threw:', e.message || e);
    }
  }

  return json({
    ok: true,
    item_id: item.id,
    variation_id: variation.id,
    image_id: imgData.image?.id,
    back_image_id: backImageId,
    title,
    listing_url: `https://sakekittycards.com/product.html?id=${encodeURIComponent(item.id)}`,
  });
}

// Admin: rename / re-describe an existing graded-card listing in Square.
// Used to fix titles when the OCR/lookup chain produced wrong card names.
// Auth: X-Sake-Admin-Token header. Body: { cert: '<cert>', card: { name,
// year, set_name, card_number, grade, grader } }. Looks the item up by
// "Cert #: <cert>" in the description, then UPSERTs with corrected
// metadata. Image links + variations + price are preserved.
async function updateGradedItem(request, base, squareHeaders, env) {
  const provided = request.headers.get('X-Sake-Admin-Token') || '';
  if (!env.ADMIN_TOKEN || !timingSafeEqual(provided, env.ADMIN_TOKEN)) {
    return json({ error: 'unauthorized' }, 401);
  }

  let body;
  try { body = await request.json(); } catch { return json({ error: 'invalid_json' }, 400); }

  const cert = String(body.cert || '').trim();
  const card = body.card || {};
  if (!cert) return json({ error: 'missing_cert' }, 400);

  // Find the item by "Cert #: <cert>" in its description. Walk paginated
  // /v2/catalog/list — for the current scale of the shop (a few dozen
  // graded items) this is fine; revisit with /search if the catalog
  // grows past a couple hundred.
  let cursor = '';
  let foundId = null;
  for (let page = 0; page < 20; page++) {
    const listUrl = `${base}/v2/catalog/list?types=ITEM${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`;
    const r = await fetch(listUrl, { headers: squareHeaders });
    const d = await r.json();
    if (!r.ok) return json({ error: 'square_list_failed', detail: d }, r.status);
    const objs = d.objects || [];
    const match = objs.find(o =>
      o.type === 'ITEM' &&
      (o.item_data?.description || '').includes(`Cert #: ${cert}`)
    );
    if (match) { foundId = match.id; break; }
    cursor = d.cursor || '';
    if (!cursor) break;
  }
  if (!foundId) return json({ error: 'item_not_found_for_cert', cert }, 404);

  // Re-read the full item so we get the latest version + preserve fields
  // we're not changing (variations, image_ids, present_at_*).
  const readRes = await fetch(
    `${base}/v2/catalog/object/${encodeURIComponent(foundId)}`,
    { headers: squareHeaders },
  );
  const readData = await readRes.json();
  if (!readRes.ok || !readData.object) {
    return json({ error: 'square_read_failed', detail: readData }, readRes.status);
  }
  const fullItem = readData.object;

  // Build the new title + description. Match the format uploadGradedItem
  // uses, but accept a `grader` override (PSA / CGC / BGS / etc.) so we
  // don't hard-code "PSA" on slabs from other companies. Grade is used
  // verbatim so qualifiers like "Pristine 10" or "Gem Mint 10" stay in
  // the title (otherwise the shop categorizer drops the slab into Singles
  // because it doesn't lead with a recognized grader-grade prefix).
  const grader = String(card.grader || 'PSA');  // case as supplied — caller picks display style
  const gradeStr = String(card.grade || '').trim();
  const titleParts = [];
  if (gradeStr)         titleParts.push(`${grader} ${gradeStr}`);
  else                  titleParts.push(grader);
  if (card.year)        titleParts.push(card.year);
  if (card.set_name)    titleParts.push(card.set_name);
  if (card.name)        titleParts.push(card.name);
  if (card.card_number) titleParts.push(`#${card.card_number}`);
  const title = titleParts.join(' ').trim();

  const descLines = [`PSA Cert #: ${cert}`];  // keep "PSA Cert #" key for cert-based lookups
  if (card.set_name)    descLines.push(`Set: ${card.set_name}${card.year ? ` (${card.year})` : ''}`);
  if (card.grade)       descLines.push(`Grade: ${grader} ${card.grade}`);
  if (card.card_number) descLines.push(`Card Number: ${card.card_number}`);
  descLines.push('Verify cert at psacard.com before purchase.');
  const description = descLines.join('\n');

  const updated = {
    ...fullItem,
    item_data: {
      ...fullItem.item_data,
      name: title.slice(0, 255),
      description: description.slice(0, 4096),
    },
  };
  const upRes = await fetch(`${base}/v2/catalog/object`, {
    method: 'POST',
    headers: squareHeaders,
    body: JSON.stringify({
      idempotency_key: crypto.randomUUID(),
      object: updated,
    }),
  });
  const upData = await upRes.json();
  if (!upRes.ok) return json({ error: 'square_update_failed', detail: upData }, upRes.status);

  return json({
    ok:       true,
    item_id:  foundId,
    title,
    listing_url: `https://sakekittycards.com/product.html?id=${encodeURIComponent(foundId)}`,
  });
}


// Admin: update the PRICE on an existing graded-card listing without touching
// title/description/images. Body: {cert, price_cents}. Looks up the item by
// "Cert #: <cert>" in description, walks its variations, sets each one's
// pricing_type to FIXED_PRICING and price_money.amount = price_cents.
// Used by the Card Ladder re-pricing flow so we don't need to delete +
// re-upload an item just to change its price.
async function updateGradedPrice(request, base, squareHeaders, env) {
  const provided = request.headers.get('X-Sake-Admin-Token') || '';
  if (!env.ADMIN_TOKEN || !timingSafeEqual(provided, env.ADMIN_TOKEN)) {
    return json({ error: 'unauthorized' }, 401);
  }

  let body;
  try { body = await request.json(); } catch { return json({ error: 'invalid_json' }, 400); }

  const cert = String(body.cert || '').trim();
  const priceCents = Number(body.price_cents);
  if (!cert) return json({ error: 'missing_cert' }, 400);
  if (!Number.isFinite(priceCents) || priceCents <= 0) return json({ error: 'invalid_price_cents' }, 400);

  // Find the item by "Cert #: <cert>" in description (same lookup pattern
  // as updateGradedItem). Walk paginated /v2/catalog/list.
  let cursor = '';
  let foundId = null;
  for (let page = 0; page < 20; page++) {
    const listUrl = `${base}/v2/catalog/list?types=ITEM${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`;
    const r = await fetch(listUrl, { headers: squareHeaders });
    const d = await r.json();
    if (!r.ok) return json({ error: 'square_list_failed', detail: d }, r.status);
    const objs = d.objects || [];
    const match = objs.find(o =>
      o.type === 'ITEM' &&
      (o.item_data?.description || '').includes(`Cert #: ${cert}`)
    );
    if (match) { foundId = match.id; break; }
    cursor = d.cursor || '';
    if (!cursor) break;
  }
  if (!foundId) return json({ error: 'item_not_found_for_cert', cert }, 404);

  // Re-read the full item so we have variation IDs + versions.
  const readRes = await fetch(
    `${base}/v2/catalog/object/${encodeURIComponent(foundId)}`,
    { headers: squareHeaders },
  );
  const readData = await readRes.json();
  if (!readRes.ok || !readData.object) {
    return json({ error: 'square_read_failed', detail: readData }, readRes.status);
  }
  const fullItem = readData.object;
  const variations = fullItem.item_data?.variations || [];
  if (!variations.length) return json({ error: 'no_variations_on_item' }, 422);

  // Update every variation's price. Most graded items have a single variation,
  // but loop in case Square ever produces multi-variation graded listings.
  const updatedVariations = variations.map(v => ({
    ...v,
    item_variation_data: {
      ...(v.item_variation_data || {}),
      pricing_type: 'FIXED_PRICING',
      price_money: { amount: Math.round(priceCents), currency: 'USD' },
    },
  }));

  const updated = {
    ...fullItem,
    item_data: {
      ...fullItem.item_data,
      variations: updatedVariations,
    },
  };

  const upRes = await fetch(`${base}/v2/catalog/object`, {
    method: 'POST',
    headers: squareHeaders,
    body: JSON.stringify({
      idempotency_key: crypto.randomUUID(),
      object: updated,
    }),
  });
  const upData = await upRes.json();
  if (!upRes.ok) return json({ error: 'square_update_failed', detail: upData }, upRes.status);

  return json({
    ok:       true,
    item_id:  foundId,
    price_cents: Math.round(priceCents),
    variations_updated: variations.length,
  });
}


// Admin: replace the front/back images on an existing graded-card listing.
// Used when re-cropping/re-processing yielded better scans for items that
// were already pushed to Square. Looks up the item by "Cert #: <cert>" in
// description, deletes its existing image objects, then attaches the new
// front (is_primary: true) and back (is_primary: false).
async function replaceGradedImages(request, base, squareHeaders, env) {
  const provided = request.headers.get('X-Sake-Admin-Token') || '';
  if (!env.ADMIN_TOKEN || !timingSafeEqual(provided, env.ADMIN_TOKEN)) {
    return json({ error: 'unauthorized' }, 401);
  }

  let body;
  try { body = await request.json(); } catch { return json({ error: 'invalid_json' }, 400); }

  const cert = String(body.cert || '').trim();
  if (!cert) return json({ error: 'missing_cert' }, 400);
  const frontB64 = String(body.image_base64 || '');
  const frontName = String(body.image_filename || `${cert}-front.jpg`);
  const backB64 = String(body.back_image_base64 || '');
  const backName = String(body.back_image_filename || `${cert}-back.jpg`);
  if (!frontB64) return json({ error: 'missing_image_base64' }, 400);

  // Find the item by cert (same approach as updateGradedItem).
  let cursor = '';
  let foundItem = null;
  for (let page = 0; page < 20; page++) {
    const listUrl = `${base}/v2/catalog/list?types=ITEM${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`;
    const r = await fetch(listUrl, { headers: squareHeaders });
    const d = await r.json();
    if (!r.ok) return json({ error: 'square_list_failed', detail: d }, r.status);
    const objs = d.objects || [];
    const match = objs.find(o =>
      o.type === 'ITEM' &&
      (o.item_data?.description || '').includes(`Cert #: ${cert}`)
    );
    if (match) { foundItem = match; break; }
    cursor = d.cursor || '';
    if (!cursor) break;
  }
  if (!foundItem) return json({ error: 'item_not_found_for_cert', cert }, 404);

  // Delete old image objects so they don't pile up. Best-effort: a stale
  // image left dangling isn't fatal, just messy.
  const oldImageIds = foundItem.item_data?.image_ids || [];
  const deleted = [];
  for (const imgId of oldImageIds) {
    try {
      const delRes = await fetch(`${base}/v2/catalog/object/${encodeURIComponent(imgId)}`, {
        method: 'DELETE', headers: squareHeaders,
      });
      if (delRes.ok) deleted.push(imgId);
    } catch {}
  }

  const imageHeaders = {
    'Square-Version': SQUARE_API_VERSION,
    'Authorization': `Bearer ${env.SQUARE_ACCESS_TOKEN}`,
  };

  // Upload new front (primary)
  const frontBytes = base64ToBytes(frontB64);
  const frontReq = {
    idempotency_key: crypto.randomUUID(),
    object_id: foundItem.id,
    image: {
      type: 'IMAGE',
      id: `#sk-graded-img-${cert}-${Date.now()}`,
      image_data: {
        name: frontName.slice(0, 255),
        caption: 'Sake Kitty Cards graded listing',
      },
    },
    is_primary: true,
  };
  const fdFront = new FormData();
  fdFront.append('request', new Blob([JSON.stringify(frontReq)], { type: 'application/json' }));
  fdFront.append('image_file', new Blob([frontBytes], { type: 'image/jpeg' }), frontName);
  const frontRes = await fetch(`${base}/v2/catalog/images`, {
    method: 'POST', headers: imageHeaders, body: fdFront,
  });
  const frontData = await frontRes.json();
  if (!frontRes.ok) {
    return json({
      error: 'square_front_upload_failed',
      item_id: foundItem.id,
      deleted_old_image_ids: deleted,
      detail: frontData,
    }, frontRes.status);
  }

  // Upload new back (best-effort)
  let backImageId = null;
  if (backB64) {
    try {
      const backBytes = base64ToBytes(backB64);
      const backReq = {
        idempotency_key: crypto.randomUUID(),
        object_id: foundItem.id,
        image: {
          type: 'IMAGE',
          id: `#sk-graded-img-${cert}-back-${Date.now()}`,
          image_data: {
            name: backName.slice(0, 255),
            caption: 'Sake Kitty Cards graded listing — back',
          },
        },
        is_primary: false,
      };
      const fdBack = new FormData();
      fdBack.append('request', new Blob([JSON.stringify(backReq)], { type: 'application/json' }));
      fdBack.append('image_file', new Blob([backBytes], { type: 'image/jpeg' }), backName);
      const backRes = await fetch(`${base}/v2/catalog/images`, {
        method: 'POST', headers: imageHeaders, body: fdBack,
      });
      const backData = await backRes.json();
      if (backRes.ok) backImageId = backData.image?.id || null;
    } catch {}
  }

  return json({
    ok: true,
    item_id: foundItem.id,
    deleted_old_image_ids: deleted,
    front_image_id: frontData.image?.id,
    back_image_id: backImageId,
  });
}


// Public: check the balance on a Sake Kitty Cards gift card by code.
// Read-only — calls Square's /v2/gift-cards/from-gan and returns just
// the balance + state. No PII, no admin auth required.
//
// Trade-off: anyone who guesses a code can read its balance. Square
// codes are 16 chars from a large alphabet so brute-force is
// impractical, and the response leaks only the amount loaded — not
// any customer info. Cloudflare Workers' built-in rate limiting on
// the free tier is sufficient for the volume we expect.
async function checkGiftCardBalance(request, base, squareHeaders, env) {
  let body;
  try { body = await request.json(); } catch { return json({ error: 'invalid_json' }, 400); }
  const gan = String(body.gan || '').trim().replace(/\s+/g, '');
  if (!gan) return json({ error: 'missing_gan' }, 400);
  if (gan.length < 4 || gan.length > 32) return json({ error: 'invalid_gan' }, 400);

  const r = await fetch(`${base}/v2/gift-cards/from-gan`, {
    method: 'POST',
    headers: squareHeaders,
    body: JSON.stringify({ gan }),
  });
  if (!r.ok) {
    // 404 = code doesn't exist. Anything else is a Square outage.
    if (r.status === 404) return json({ ok: false, error: 'not_found' }, 404);
    return json({ ok: false, error: 'square_error' }, 502);
  }
  const d = await r.json();
  if (!d.gift_card) return json({ ok: false, error: 'not_found' }, 404);
  return json({
    ok: true,
    balance_cents: d.gift_card.balance_money?.amount || 0,
    currency:      d.gift_card.balance_money?.currency || 'USD',
    state:         d.gift_card.state,
    last4:         gan.slice(-4),
  });
}


// Admin: hard-delete a Square catalog item by ID. Used for cleaning up
// duplicate listings that slipped through when the same cert went
// through both upload-graded and missing-certs paths.
async function adminDeleteItem(request, base, squareHeaders, env) {
  const provided = request.headers.get('X-Sake-Admin-Token') || '';
  if (!env.ADMIN_TOKEN || !timingSafeEqual(provided, env.ADMIN_TOKEN)) {
    return json({ error: 'unauthorized' }, 401);
  }
  let body;
  try { body = await request.json(); } catch { return json({ error: 'invalid_json' }, 400); }
  const itemId = String(body.item_id || '').trim();
  if (!itemId) return json({ error: 'missing_item_id' }, 400);

  const r = await fetch(
    `${base}/v2/catalog/object/${encodeURIComponent(itemId)}`,
    { method: 'DELETE', headers: squareHeaders },
  );
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    return json({ error: 'square_delete_failed', detail }, r.status);
  }
  const data = await r.json().catch(() => ({}));
  return json({ ok: true, item_id: itemId, detail: data });
}


function base64ToBytes(b64) {
  const cleaned = b64.replace(/^data:[^;]+;base64,/, '');
  const bin = atob(cleaned);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}


async function fetchPrintfulSyncVariantIdMap(env) {
  const cacheKey = new Request('https://internal.cache/printful-variant-id-map/v1');
  const cached = await caches.default.match(cacheKey);
  if (cached) {
    try { return await cached.json(); } catch {}
  }

  const pfHeaders = {
    'Authorization': `Bearer ${env.PRINTFUL_ACCESS_TOKEN}`,
    'X-PF-Store-Id': String(env.PRINTFUL_STORE_ID),
  };

  const listRes = await fetch('https://api.printful.com/sync/products?limit=100', { headers: pfHeaders });
  if (!listRes.ok) return {};
  const listData = await listRes.json();
  const products = Array.isArray(listData.result) ? listData.result : [];

  const details = await Promise.all(products.map(async p => {
    try {
      const r = await fetch(`https://api.printful.com/sync/products/${p.id}`, { headers: pfHeaders });
      if (!r.ok) return null;
      return (await r.json()).result;
    } catch { return null; }
  }));

  const map = {};
  for (const d of details) {
    for (const v of (d?.sync_variants || [])) {
      if (v.external_id && v.id) map[v.external_id] = v.id;
    }
  }

  await caches.default.put(cacheKey, new Response(JSON.stringify(map), {
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=600' },
  }));
  return map;
}

async function printfulFindOrderByExternalId(externalId, env) {
  const pfHeaders = {
    'Authorization': `Bearer ${env.PRINTFUL_ACCESS_TOKEN}`,
    'X-PF-Store-Id': String(env.PRINTFUL_STORE_ID),
  };
  // Printful's orders list does not filter by external_id directly via
  // query param; we fetch recent orders and look for a match. Limit 20
  // should be plenty in practice (webhook retries happen within minutes).
  const res = await fetch('https://api.printful.com/orders?limit=20', { headers: pfHeaders });
  if (!res.ok) return null;
  const data = await res.json();
  return (data.result || []).find(o => o.external_id === externalId) || null;
}

// ─── Crypto helpers ────────────────────────────────────────────────────────

async function computeHmacSha256Base64(secret, data) {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(data));
  const bytes = new Uint8Array(sig);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

function timingSafeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return mismatch === 0;
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  });
}
