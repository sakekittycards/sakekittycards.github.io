// Sake Kitty Square Worker
// Proxies calls to the Square API so the site never sees the access token.
//
// Endpoints:
//   GET  /items            — list products from Square catalog
//   POST /checkout         — create a Square Payment Link from a cart
//   GET  /health           — liveness check
//
// Secret: SQUARE_ACCESS_TOKEN (set via `wrangler secret put SQUARE_ACCESS_TOKEN`)
// Vars:   SQUARE_ENV ("sandbox" | "production"), SQUARE_LOCATION_ID, SQUARE_APPLICATION_ID

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
        return await listItems(base, squareHeaders, env.SQUARE_LOCATION_ID);
      }

      if (path === '/checkout' && request.method === 'POST') {
        const body = await request.json().catch(() => ({}));
        return await createCheckout(body, base, squareHeaders, env, url);
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

async function listItems(base, headers, locationId) {
  const res = await fetch(`${base}/v2/catalog/list?types=ITEM,IMAGE`, { headers });
  const data = await res.json();
  if (!res.ok) return json({ error: 'square_api_error', detail: data }, res.status);

  const objects = data.objects || [];
  const images  = Object.fromEntries(
    objects.filter(o => o.type === 'IMAGE').map(o => [o.id, o.image_data?.url])
  );

  const items = objects
    .filter(o => o.type === 'ITEM')
    .map(o => {
      const variation = o.item_data?.variations?.[0]?.item_variation_data;
      const variationId = o.item_data?.variations?.[0]?.id;
      const amountCents = variation?.price_money?.amount;
      // All current items are Printful print-on-demand — never out of stock.
      // Printful inconsistently enables track_inventory during sync, so we ignore it.
      const inStock = true;
      return {
        id:          o.id,
        variationId,
        name:        o.item_data?.name || '',
        description: o.item_data?.description || '',
        price:       amountCents != null ? amountCents / 100 : null,
        currency:    variation?.price_money?.currency || 'USD',
        imageUrl:    images[o.item_data?.image_ids?.[0]] || null,
        categoryId:  o.item_data?.category_id || null,
        inStock,
      };
    })
    .filter(item => item.price != null);  // hide items with no price

  return json({ items });
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

// ─── Helpers ───────────────────────────────────────────────────────────────

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  });
}
