// ─────────────────────────────────────────────────────────────
// Sake Kitty Cards — TCG CSV Proxy (Cloudflare Worker)
//
// Purpose: Proxies requests to tcgcsv.com with proper CORS headers
// and Cloudflare edge caching so the trade-in tool can load card +
// sealed data directly in the browser (tcgcsv.com serves no CORS
// headers, so the browser cannot call it directly).
//
// History: originally dashboard-pasted from a loose cloudflare-worker.js
// in the repo root. Promoted to a real wrangler project 2026-07-30 when
// tcgcsv.com started rejecting the Workers default User-Agent (401
// "Your User-Agent has been blocked") — which silently killed sealed
// search, JP set-name search, and the TCG CSV price backfill on both
// customer forms. Per tcgcsv.com/docs#usage-guidelines every client
// must identify itself; see USER_AGENT below. Deploy from this folder:
//   npx wrangler deploy
//
// Routes:
//   GET /groups            → category 3 (English Pokémon)
//   GET /<id>/products     → category 3
//   GET /<id>/prices       → category 3
//   GET /jp/groups         → category 85 (Japanese Pokémon)
//   GET /jp/<id>/products  → category 85
//   GET /jp/<id>/prices    → category 85
// ─────────────────────────────────────────────────────────────

const UPSTREAM_BASE = 'https://tcgcsv.com/tcgplayer';

// tcgcsv.com blocks unidentified clients — this MUST stay on every
// upstream fetch. Same convention as tcgplayerpost/tcgcsv_client.py.
const USER_AGENT = 'SakeKittyCards-TradeInForm/1.0 (nick@sakekittycards.com)';

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

    // Resolve category from path prefix (defaults to 3 / English)
    let category = 3;
    let rest;
    const legacy = url.pathname.match(/^\/(groups|\d+\/(?:products|prices))$/);
    const japan  = url.pathname.match(/^\/jp\/(groups|\d+\/(?:products|prices))$/);
    if (legacy)       { rest = legacy[1]; }
    else if (japan)   { rest = japan[1];  category = 85; }
    else {
      return new Response('Not Found', { status: 404, headers: CORS_HEADERS });
    }

    // ?skv=2 is a cache-key version: the pre-UA-fix worker edge-cached 401s
    // for 6h, and bare paths kept serving them even after the fix deployed.
    // tcgcsv.com (S3/CloudFront) ignores unknown query params — verified 200.
    const target = `${UPSTREAM_BASE}/${category}/${rest}?skv=2`;

    // Try Cloudflare edge cache first
    const cacheKey = new Request(target, { method: 'GET' });
    const cache = caches.default;
    let response = await cache.match(cacheKey);

    if (!response) {
      // Miss → fetch upstream and cache. cacheTtlByStatus (not cacheTtl)
      // so an upstream error is never edge-cached for 6 hours — during
      // the UA-block outage a cached 401 would have pinned the outage in
      // place even after a fix deployed.
      const upstream = await fetch(target, {
        headers: { 'User-Agent': USER_AGENT },
        cf: { cacheEverything: true, cacheTtlByStatus: { '200-299': CACHE_SECONDS, '300-599': 0 } },
      });
      response = new Response(upstream.body, upstream);
      // Only successes are cacheable. The old worker stamped public/6h on
      // EVERYTHING, so during the UA-block outage customer browsers cached
      // the 401 itself and kept the form broken even after the fix shipped.
      if (upstream.ok) {
        response.headers.set('Cache-Control', `public, max-age=${CACHE_SECONDS}`);
        ctx.waitUntil(cache.put(cacheKey, response.clone()));
      } else {
        response.headers.set('Cache-Control', 'no-store');
      }
    }

    // Attach CORS headers on the way out
    const out = new Response(response.body, response);
    Object.entries(CORS_HEADERS).forEach(([k, v]) => out.headers.set(k, v));
    return out;
  },
};
