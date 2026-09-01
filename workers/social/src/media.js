/**
 * Media storage.
 *
 * Instagram's publishing API does not accept an upload. It accepts a URL and
 * fetches it itself, which means every asset we post has to be reachable
 * unauthenticated for the duration of the call. R2 behind this worker is the
 * smallest thing that satisfies that without making the bucket public: objects
 * are addressed by a 32-byte random token, served read-only, and the R2 key is
 * never derivable from the URL.
 *
 * Provenance is stored for every asset, not just fetched ones. When a flyer
 * turns out to belong to someone who would rather we did not repost it, the
 * question "where did this come from and when" has to have an answer.
 */
import { stableId, sha256Hex, nowMs, fetchT } from './util.js';

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;      // Instagram's own image ceiling
const MAX_VIDEO_BYTES = 1024 * 1024 * 1024;   // Reels ceiling

const ALLOWED_TYPES = new Set([
  'image/jpeg', 'image/png', 'video/mp4', 'video/quicktime',
]);

export function publicToken() {
  const b = new Uint8Array(24);
  crypto.getRandomValues(b);
  return [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
}

export async function storeMedia(env, bytes, {
  kind = 'image',
  contentType = 'image/jpeg',
  width = null,
  height = null,
  template = null,
  sourceKind = 'generated',
  sourceUrl = null,
  sourceDomain = null,
  acquisition = 'rendered',
  originalName = null,
  retrievedAt = null,
  provenance = null,
  at = nowMs(),
} = {}) {
  if (!ALLOWED_TYPES.has(contentType)) {
    throw new Error(`storeMedia: content type ${contentType} not allowed`);
  }
  const limit = kind === 'video' ? MAX_VIDEO_BYTES : MAX_IMAGE_BYTES;
  if (bytes.byteLength > limit) {
    throw new Error(`storeMedia: ${bytes.byteLength} bytes exceeds the ${limit}-byte limit for ${kind}`);
  }

  const sha = await sha256Hex(new Uint8Array(bytes));

  // Content-addressed: re-rendering an identical graphic reuses the row and the
  // object instead of filling the bucket with byte-identical copies.
  const existing = await env.DB.prepare(
    'SELECT * FROM media_assets WHERE sha256 = ? AND kind = ?'
  ).bind(sha, kind).first();
  if (existing) return { ...existing, reused: true };

  const id = await stableId('med', sha, kind);
  const token = publicToken();
  const ext = contentType === 'image/png' ? 'png'
    : contentType === 'video/mp4' ? 'mp4'
      : contentType === 'video/quicktime' ? 'mov' : 'jpg';
  const key = `${kind}/${sha.slice(0, 2)}/${sha}.${ext}`;

  await env.MEDIA.put(key, bytes, {
    httpMetadata: {
      contentType,
      // Immutable because the key is the content hash: the bytes at this key can
      // never change, so nothing downstream needs to revalidate.
      cacheControl: 'public, max-age=31536000, immutable',
    },
  });

  await env.DB.prepare(
    `INSERT INTO media_assets (id, kind, r2_key, content_type, bytes, width, height, sha256,
       public_token, template, source_kind, source_url, source_domain, acquisition, retrieved_at,
       original_name, provenance, created_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
  ).bind(
    id, kind, key, contentType, bytes.byteLength, width, height, sha, token, template,
    sourceKind, sourceUrl, sourceDomain, acquisition, retrievedAt,
    originalName, provenance ? JSON.stringify(provenance) : null, at
  ).run();

  return {
    id, kind, r2_key: key, content_type: contentType, bytes: bytes.byteLength,
    width, height, sha256: sha, public_token: token, reused: false,
  };
}

export async function getMedia(env, id) {
  return env.DB.prepare('SELECT * FROM media_assets WHERE id = ?').bind(id).first();
}

export async function mediaByToken(env, token) {
  return env.DB.prepare('SELECT * FROM media_assets WHERE public_token = ?').bind(token).first();
}

export function mediaUrl(env, media) {
  const base = String(env.PUBLIC_BASE || '').replace(/\/+$/, '');
  return `${base}/m/${media.public_token}`;
}

/**
 * Serve an object to whoever has the token — in practice, Instagram's fetcher.
 *
 * Range support is not optional: Instagram's video ingest issues ranged reads,
 * and a server that answers 200-with-everything to a Range request gets treated
 * as a broken source.
 */
export async function serveMedia(env, token, request) {
  const row = await mediaByToken(env, token);
  if (!row) return new Response('not found', { status: 404 });

  const range = request.headers.get('range');
  const obj = range
    ? await env.MEDIA.get(row.r2_key, { range: parseRange(range, row.bytes) })
    : await env.MEDIA.get(row.r2_key);
  if (!obj) return new Response('gone', { status: 404 });

  const headers = new Headers();
  headers.set('content-type', row.content_type);
  headers.set('cache-control', 'public, max-age=31536000, immutable');
  headers.set('accept-ranges', 'bytes');
  headers.set('x-content-type-options', 'nosniff');
  // These bytes are for a platform fetcher, never for a browser to interpret.
  headers.set('content-security-policy', "default-src 'none'; sandbox");

  if (range && obj.range) {
    const start = obj.range.offset;
    const end = start + obj.range.length - 1;
    headers.set('content-range', `bytes ${start}-${end}/${row.bytes}`);
    headers.set('content-length', String(obj.range.length));
    return new Response(obj.body, { status: 206, headers });
  }
  headers.set('content-length', String(row.bytes));
  return new Response(obj.body, { status: 200, headers });
}

function parseRange(header, size) {
  const m = /^bytes=(\d*)-(\d*)$/.exec(String(header).trim());
  if (!m) return undefined;
  const [, s, e] = m;
  if (s === '' && e !== '') return { suffix: Number(e) };
  const offset = Number(s || 0);
  const end = e === '' ? size - 1 : Number(e);
  return { offset, length: Math.max(0, Math.min(end, size - 1) - offset + 1) };
}

/**
 * Fetch a candidate flyer from a first-party source and validate it before it
 * is ever stored.
 *
 * The rules that matter are refusals: HTTPS only, no redirect off the host we
 * were pointed at, a declared image type, and a size floor that rejects the
 * tracking pixels and social-icon sprites that a naive og:image scrape returns.
 * Nothing here searches for images — a caller must already have a specific URL
 * from a specific event or organizer page.
 */
export async function fetchCandidate(env, url, { referer = null, at = nowMs() } = {}) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(`flyer: ${url} is not a URL`);
  }
  if (parsed.protocol !== 'https:') throw new Error('flyer: source must be https');

  // Timed out rather than plain fetch: a show organizer's site that accepts the
  // connection and then stalls would otherwise hold the request open until the
  // platform kills it, and this runs inside a content pass.
  const res = await fetchT(parsed.toString(), {
    redirect: 'follow',
    headers: {
      // Identify ourselves. Several show-organizer sites sit behind rules that
      // 403 an unnamed client, and a silent 403 looks like "no flyer exists".
      'user-agent': 'sakekitty-social/1.0 (+https://sakekittycards.com)',
      accept: 'image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8',
      ...(referer ? { referer } : {}),
    },
  }, 15000);
  if (!res.ok) throw new Error(`flyer: source returned ${res.status}`);

  const finalUrl = new URL(res.url);
  if (finalUrl.hostname !== parsed.hostname && !finalUrl.hostname.endsWith(`.${parsed.hostname}`)) {
    throw new Error(`flyer: redirected off-host to ${finalUrl.hostname} — refusing`);
  }

  const ct = (res.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
  if (!ct.startsWith('image/')) throw new Error(`flyer: ${ct || 'unknown type'} is not an image`);

  const buf = new Uint8Array(await res.arrayBuffer());
  if (buf.byteLength < 12000) {
    throw new Error(`flyer: ${buf.byteLength} bytes is too small to be event artwork`);
  }
  if (buf.byteLength > MAX_IMAGE_BYTES * 3) throw new Error('flyer: source image is too large');

  return {
    bytes: buf,
    contentType: ct,
    sourceUrl: res.url,
    sourceDomain: finalUrl.hostname,
    retrievedAt: at,
    originalName: decodeURIComponent(finalUrl.pathname.split('/').pop() || ''),
  };
}
