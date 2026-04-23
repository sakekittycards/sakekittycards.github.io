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
        return await listItems(base, squareHeaders);
      }

      if (path === '/checkout' && request.method === 'POST') {
        const body = await request.json().catch(() => ({}));
        return await createCheckout(body, base, squareHeaders, env, url);
      }

      return json({ error: 'not found', path }, 404);
    } catch (err) {
      return json({ error: err.message || String(err) }, 500);
    }
  },
};

// ─── Handlers ──────────────────────────────────────────────────────────────

async function listItems(base, headers) {
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
      const amountCents = variation?.price_money?.amount;
      return {
        id:          o.id,
        variationId: o.item_data?.variations?.[0]?.id,
        name:        o.item_data?.name || '',
        description: o.item_data?.description || '',
        price:       amountCents != null ? amountCents / 100 : null,
        currency:    variation?.price_money?.currency || 'USD',
        imageUrl:    images[o.item_data?.image_ids?.[0]] || null,
        categoryId:  o.item_data?.category_id || null,
      };
    })
    .filter(item => item.price != null);  // hide items with no price

  return json({ items });
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
    const name     = String(item.name || 'Item').slice(0, 500);
    const quantity = String(Math.max(1, parseInt(item.quantity, 10) || 1));
    const cents    = Math.round(Number(item.price) * 100);
    if (!Number.isFinite(cents) || cents <= 0) throw new Error(`invalid price for ${name}`);
    return {
      name,
      quantity,
      base_price_money: { amount: cents, currency: 'USD' },
    };
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

// ─── Helpers ───────────────────────────────────────────────────────────────

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  });
}
