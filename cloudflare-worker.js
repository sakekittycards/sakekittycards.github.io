// ─────────────────────────────────────────────────────────────
// Sake Kitty Cards — TCG CSV Proxy (Cloudflare Worker)
//
// Purpose: Proxies requests to tcgcsv.com with proper CORS headers
// and Cloudflare edge caching so the trade-in tool can load card +
// sealed data directly in the browser.
//
// Deploy steps:
//   1. Sign in at https://dash.cloudflare.com/ (free account)
//   2. Sidebar → Workers & Pages → Create → Hello World Worker
//   3. Name it something like "tcgcsv-proxy" → Deploy
//   4. Click "Edit code", delete the default, paste THIS file
//   5. Click "Deploy"
//   6. Copy the *.workers.dev URL it gives you and send it to Claude
//
// Routes it handles (forwarded to tcgcsv.com/tcgplayer/3/...):
//   GET /groups                     → all Pokémon sets
//   GET /<groupId>/products         → products in a set
//   GET /<groupId>/prices           → prices for a set
// ─────────────────────────────────────────────────────────────

const UPSTREAM = 'https://tcgcsv.com/tcgplayer/3';

// 6-hour cache — TCG CSV refreshes daily, so this is plenty fresh.
const CACHE_SECONDS = 6 * 60 * 60;

const CORS_HEADERS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Max-Age':       '86400',
};

export default {
  async fetch(request, env, ctx) {
    // Preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }
    if (request.method !== 'GET') {
      return new Response('Method Not Allowed', { status: 405, headers: CORS_HEADERS });
    }

    const url = new URL(request.url);

    // Allow only the three patterns we need, so this proxy can't be
    // used as a generic open relay.
    const allowed = /^\/(groups|\d+\/(products|prices))$/;
    if (!allowed.test(url.pathname)) {
      return new Response('Not Found', { status: 404, headers: CORS_HEADERS });
    }

    const target = `${UPSTREAM}${url.pathname}`;

    // Try Cloudflare edge cache first
    const cacheKey = new Request(target, { method: 'GET' });
    const cache = caches.default;
    let response = await cache.match(cacheKey);

    if (!response) {
      // Miss → fetch upstream and cache
      const upstream = await fetch(target, {
        cf: { cacheEverything: true, cacheTtl: CACHE_SECONDS },
      });
      response = new Response(upstream.body, upstream);
      response.headers.set('Cache-Control', `public, max-age=${CACHE_SECONDS}`);
      if (upstream.ok) {
        ctx.waitUntil(cache.put(cacheKey, response.clone()));
      }
    }

    // Attach CORS headers on the way out
    const out = new Response(response.body, response);
    Object.entries(CORS_HEADERS).forEach(([k, v]) => out.headers.set(k, v));
    return out;
  },
};
