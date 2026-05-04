// Sake Kitty Prices Worker
// Scrapes recent sold-listing prices for graded Pokémon cards from 130point,
// with spoofed browser headers + response caching. Used by trade-in.html.
//
// Endpoints:
//   GET /health                       — liveness
//   GET /lookup?q=<query>             — search + return summarized prices (130point graded sold)
//   GET /dev/raw?q=<query>            — raw HTML passthrough (for debugging parser)
//   GET /tcg/lastsold?productId=<id>  — TCGplayer recent sold avg via mpapi.tcgplayer.com
//                                       (used by trade-in.html to fill in market price for raw
//                                       cards TCG CSV / pokemontcg.io don't have a marketPrice
//                                       for — older JP promos, vintage sets, etc.)

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Max-Age': '86400',
};

// Full browser-ish header set so 130point/PSA are less likely to see us as a bot.
const BROWSER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.9',
  'Accept-Encoding': 'gzip, deflate, br',
  'Sec-Ch-Ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
  'Sec-Ch-Ua-Mobile': '?0',
  'Sec-Ch-Ua-Platform': '"Windows"',
  'Sec-Fetch-Dest': 'document',
  'Sec-Fetch-Mode': 'navigate',
  'Sec-Fetch-Site': 'none',
  'Sec-Fetch-User': '?1',
  'Upgrade-Insecure-Requests': '1',
  'DNT': '1',
};

export default {
  async fetch(request, env, ctx) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url  = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    try {
      if (path === '/health') {
        return json({ ok: true });
      }

      if (path === '/lookup' && request.method === 'GET') {
        const q = (url.searchParams.get('q') || '').trim();
        if (!q) return json({ error: 'q parameter required' }, 400);
        return await lookupPrice(q, ctx, env);
      }

      if (path === '/dev/raw' && request.method === 'GET') {
        const q = (url.searchParams.get('q') || '').trim();
        if (!q) return new Response('q parameter required', { status: 400 });
        return await fetch130pointRaw(q);
      }

      if (path === '/tcg/lastsold' && request.method === 'GET') {
        const pid = (url.searchParams.get('productId') || '').trim();
        if (!/^\d+$/.test(pid)) return json({ error: 'productId must be numeric' }, 400);
        return await fetchTcgLastSold(pid, ctx, env);
      }

      return json({ error: 'not found', path }, 404);
    } catch (err) {
      return json({ error: err.message || String(err) }, 500);
    }
  },
};

// ─── Lookup (with edge cache) ──────────────────────────────────────────────
async function lookupPrice(query, ctx, env) {
  const cache    = caches.default;
  const cacheUrl = new URL('https://sakekitty-prices.internal/cache/lookup');
  cacheUrl.searchParams.set('q', query.toLowerCase());
  const cacheKey = new Request(cacheUrl.toString(), { method: 'GET' });

  const hit = await cache.match(cacheKey);
  if (hit) return hit;

  const result   = await fetch130point(query);
  const ttl      = Number(env.CACHE_TTL_SECONDS) || 21600;

  const response = new Response(JSON.stringify(result), {
    headers: {
      ...CORS_HEADERS,
      'Content-Type': 'application/json',
      // Only cache successful, non-empty results so failures don't stick.
      'Cache-Control': result.ok && result.summary
        ? `public, max-age=${ttl}`
        : 'no-store',
    },
  });

  if (result.ok && result.summary) {
    ctx.waitUntil(cache.put(cacheKey, response.clone()));
  }
  return response;
}

// ─── 130point scraper ─────────────────────────────────────────────────────
async function fetch130point(query) {
  // Step 1: warm up a browser-ish session by hitting the homepage — picks up
  // any cookies the site hands out, and makes the subsequent search look like
  // an in-session navigation rather than a bare bot fetch.
  let cookie = '';
  try {
    const warm = await fetch('https://130point.com/sales/', {
      headers: {
        ...BROWSER_HEADERS,
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-Mode': 'navigate',
      },
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    const setCookies = warm.headers.get('set-cookie');
    if (setCookies) {
      cookie = setCookies.split(',').map(c => c.split(';')[0].trim()).join('; ');
    }
  } catch { /* proceed without cookies — better than nothing */ }

  const searchUrl = `https://130point.com/sales/?q=${encodeURIComponent(query)}&search=1`;

  let res;
  try {
    res = await fetch(searchUrl, {
      headers: {
        ...BROWSER_HEADERS,
        Referer: 'https://130point.com/sales/',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-Mode': 'navigate',
        ...(cookie ? { Cookie: cookie } : {}),
      },
      cf: { cacheTtl: 0, cacheEverything: false },
    });
  } catch (err) {
    return { ok: false, source: '130point', error: `fetch threw: ${err.message || err}` };
  }

  if (!res.ok) {
    return {
      ok: false,
      source: '130point',
      error: `HTTP ${res.status}`,
      status: res.status,
      hint: res.status === 403
        ? 'likely blocked — 130point detected automated traffic'
        : undefined,
    };
  }

  const html   = await res.text();
  const prices = parsePrices(html);

  if (prices.length === 0) {
    return {
      ok: true,
      source:  '130point',
      query,
      prices:  [],
      summary: null,
      note:    'page returned 200 but no prices parsed — may need parser update',
      htmlBytes: html.length,
    };
  }

  return {
    ok: true,
    source:  '130point',
    query,
    prices,
    summary: summarize(prices),
  };
}

async function fetch130pointRaw(query) {
  const searchUrl = `https://130point.com/sales/?q=${encodeURIComponent(query)}&search=1`;
  const res = await fetch(searchUrl, {
    headers: { ...BROWSER_HEADERS, Referer: 'https://130point.com/' },
  });
  const body = await res.text();
  return new Response(body, {
    status: res.status,
    headers: {
      ...CORS_HEADERS,
      'Content-Type': 'text/html; charset=utf-8',
      'X-Upstream-Status': String(res.status),
    },
  });
}

// ─── Parsing ──────────────────────────────────────────────────────────────
function parsePrices(html) {
  // Grab dollar amounts that look like sold prices. Filter by plausibility.
  // We'll refine with DOM-aware parsing once we can see the actual HTML shape.
  const matches = html.match(/\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+\.\d{2})/g);
  if (!matches) return [];
  const nums = matches
    .map(m => parseFloat(m.replace(/[$,]/g, '')))
    .filter(v => Number.isFinite(v) && v >= 1 && v <= 100000);
  // Dedupe a bit to reduce UI/nav number noise.
  return nums;
}

function summarize(prices) {
  if (prices.length === 0) return null;
  const sorted = [...prices].sort((a, b) => a - b);
  const sum    = sorted.reduce((a, b) => a + b, 0);
  return {
    count:  sorted.length,
    avg:    Math.round((sum / sorted.length) * 100) / 100,
    median: sorted[Math.floor(sorted.length / 2)],
    min:    sorted[0],
    max:    sorted[sorted.length - 1],
  };
}

// ─── TCGplayer recent sold (mpapi /latestsales) ────────────────────────────
// Free, no auth, no SkuId required (just productId). Returns last 25 sold
// transactions for the product, across all conditions/variants/languages.
// We average purchasePrice on the most recent N sales as a market anchor for
// cards TCG CSV doesn't carry a marketPrice for. Edge-cached aggressively
// because TCGplayer IP-blocks workers that hammer it.
async function fetchTcgLastSold(productId, ctx, env) {
  const cache    = caches.default;
  const cacheKey = new Request(`https://sakekitty-prices.internal/tcg/lastsold?id=${productId}`, { method: 'GET' });

  const hit = await cache.match(cacheKey);
  if (hit) return hit;

  let upstream;
  try {
    upstream = await fetch(`https://mpapi.tcgplayer.com/v2/product/${productId}/latestsales`, {
      method:  'POST',
      headers: {
        'User-Agent':  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept':      'application/json',
        'Content-Type':'application/json',
        'Origin':      'https://www.tcgplayer.com',
        'Referer':     `https://www.tcgplayer.com/product/${productId}`,
      },
      body: JSON.stringify({ limit: 25, offset: 0, listingType: 'All', conditions: [], languages: [], variants: [] }),
      cf:   { cacheTtl: 0, cacheEverything: false },
    });
  } catch (err) {
    return json({ ok: false, error: `fetch threw: ${err.message || err}` });
  }

  if (!upstream.ok) {
    return json({ ok: false, error: `HTTP ${upstream.status}`, status: upstream.status });
  }

  let payload;
  try {
    payload = await upstream.json();
  } catch (err) {
    return json({ ok: false, error: 'non-json upstream response' });
  }

  // Drop ListingWithPhotos — those are typically off-center / abnormal copies
  // that skew the average. Same filter the reprice pipeline applies.
  const sales = (payload?.data || [])
    .filter(s => s && s.listingType !== 'ListingWithPhotos' && Number.isFinite(+s.purchasePrice) && +s.purchasePrice > 0);

  let avg = null;
  let recentSamples = [];
  if (sales.length) {
    // Use up to the most recent 10 sales for a stable but recent average. Drop
    // the highest+lowest if we have ≥5 to trim outliers.
    const recent = sales.slice(0, 10).map(s => +s.purchasePrice).sort((a, b) => a - b);
    const trimmed = recent.length >= 5 ? recent.slice(1, -1) : recent;
    avg = +(trimmed.reduce((a, b) => a + b, 0) / trimmed.length).toFixed(2);
    recentSamples = recent.slice(0, 5);
  }

  const ttl = Number(env.CACHE_TTL_SECONDS) || 21600;
  const body = JSON.stringify({
    ok:        true,
    productId,
    sales:     sales.length,
    avgPrice:  avg,
    samples:   recentSamples,
  });
  const response = new Response(body, {
    headers: {
      ...CORS_HEADERS,
      'Content-Type':  'application/json',
      'Cache-Control': `public, max-age=${ttl}`,
    },
  });
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

// ─── Helpers ───────────────────────────────────────────────────────────────
function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  });
}
