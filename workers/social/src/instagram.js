/**
 * Instagram Graph API client.
 *
 * The official Content Publishing API, not browser automation. Publishing is a
 * two-step handshake and the split is the source of every subtle bug in this
 * area, so it is worth stating plainly:
 *
 *   POST /{ig-user-id}/media          -> a container id. Instagram now goes and
 *                                        fetches our image or video URL itself.
 *   GET  /{container-id}?fields=status_code
 *                                     -> IN_PROGRESS | FINISHED | ERROR.
 *                                        Images are usually instant; a Reel is
 *                                        not, and publishing an unfinished
 *                                        container fails.
 *   POST /{ig-user-id}/media_publish  -> the actual post.
 *
 * The container is the idempotency key. If the publish call times out we do NOT
 * make a second container — we reuse the one we already have, which is why the
 * id is persisted before the call rather than after.
 *
 * Errors are classified rather than retried blindly. Retrying a permanent error
 * burns the 50-posts-per-24h quota and, in the worst case, double-posts.
 */
import { fetchT } from './util.js';

const API_VERSION = 'v21.0';
const BASE = `https://graph.facebook.com/${API_VERSION}`;

export class IgError extends Error {
  constructor(message, { kind = 'transient', status = 0, code = null, subcode = null, body = null } = {}) {
    super(message);
    this.name = 'IgError';
    this.kind = kind;          // 'transient' | 'permanent' | 'rate_limit' | 'auth'
    this.status = status;
    this.code = code;
    this.subcode = subcode;
    this.body = body;
  }
}

/**
 * Meta's error codes, mapped to what we should actually do.
 *
 * 190 / 102        the token is dead — no amount of retrying fixes it, and a
 *                  retry loop on an expired token looks exactly like an attack.
 * 4 / 17 / 32 / 613  rate or quota. Back off, keep the item scheduled.
 * 1 / 2            genuine platform transient.
 * 9004 / 2207xxx   we handed Instagram media it could not fetch or decode —
 *                  permanent until the media changes.
 */
function classify(status, err) {
  const code = err && err.code;
  const sub = err && err.error_subcode;
  if (code === 190 || code === 102 || code === 10 || status === 401) {
    return 'auth';
  }
  if (code === 4 || code === 17 || code === 32 || code === 613 || status === 429) {
    return 'rate_limit';
  }
  if (code === 1 || code === 2 || status >= 500) return 'transient';
  if (code === 9004 || (typeof code === 'number' && code >= 2207000 && code < 2208000)) {
    return 'permanent';
  }
  if (status >= 400 && status < 500) return 'permanent';
  return 'transient';
}

async function call(env, method, path, params = {}, { timeoutMs = 30000 } = {}) {
  const token = env.IG_ACCESS_TOKEN;
  if (!token) throw new IgError('IG_ACCESS_TOKEN is not set on this worker', { kind: 'auth' });

  const url = new URL(`${BASE}${path}`);
  let init = { method, headers: {} };

  if (method === 'GET') {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
    // The token goes in a header, never the query string: query strings land in
    // access logs, error reports and referrers.
    init.headers.authorization = `Bearer ${token}`;
  } else {
    const body = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) body.set(k, String(v));
    }
    init.body = body;
    init.headers['content-type'] = 'application/x-www-form-urlencoded';
    init.headers.authorization = `Bearer ${token}`;
  }

  let res;
  try {
    res = await fetchT(url.toString(), init, timeoutMs);
  } catch (e) {
    throw new IgError(`network error calling ${path}: ${String(e)}`, { kind: 'transient' });
  }

  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { _raw: text }; }

  if (!res.ok || data.error) {
    const err = data.error || {};
    throw new IgError(
      err.message || `Instagram returned ${res.status} for ${path}`,
      {
        kind: classify(res.status, err),
        status: res.status,
        code: err.code ?? null,
        subcode: err.error_subcode ?? null,
        body: text.slice(0, 1200),
      }
    );
  }
  return data;
}

/** Who are we posting as? Also the cheapest possible token health check. */
export async function account(env) {
  const id = env.IG_USER_ID;
  if (!id) throw new IgError('IG_USER_ID is not set on this worker', { kind: 'auth' });
  const me = await call(env, 'GET', `/${id}`, {
    fields: 'id,username,name,profile_picture_url,followers_count,media_count',
  });
  return me;
}

/**
 * Remaining posts in the rolling 24h window.
 *
 * Instagram allows 50 API-published posts per 24 hours. Checking costs one cheap
 * call and turns a hard failure at post time into a scheduling decision.
 */
export async function publishingLimit(env) {
  const id = env.IG_USER_ID;
  const d = await call(env, 'GET', `/${id}/content_publishing_limit`, {
    fields: 'config,quota_usage',
  });
  const row = (d.data && d.data[0]) || {};
  const quota = (row.config && row.config.quota_total) || 50;
  const used = row.quota_usage || 0;
  return { used, quota, remaining: Math.max(0, quota - used) };
}

export async function createImageContainer(env, { imageUrl, caption }) {
  const d = await call(env, 'POST', `/${env.IG_USER_ID}/media`, {
    image_url: imageUrl,
    caption,
  });
  if (!d.id) throw new IgError('no container id returned', { kind: 'transient', body: JSON.stringify(d) });
  return d.id;
}

export async function createReelContainer(env, { videoUrl, caption, coverUrl = null, shareToFeed = true }) {
  const d = await call(env, 'POST', `/${env.IG_USER_ID}/media`, {
    media_type: 'REELS',
    video_url: videoUrl,
    caption,
    share_to_feed: shareToFeed ? 'true' : 'false',
    ...(coverUrl ? { cover_url: coverUrl } : {}),
  }, { timeoutMs: 60000 });
  if (!d.id) throw new IgError('no container id returned', { kind: 'transient', body: JSON.stringify(d) });
  return d.id;
}

/**
 * Stories are the same handshake with `media_type=STORIES` and no caption —
 * built so the surface exists, but nothing schedules one by default.
 */
export async function createStoryContainer(env, { imageUrl = null, videoUrl = null }) {
  const params = { media_type: 'STORIES' };
  if (imageUrl) params.image_url = imageUrl;
  else if (videoUrl) params.video_url = videoUrl;
  else throw new IgError('story needs an image or video url', { kind: 'permanent' });
  const d = await call(env, 'POST', `/${env.IG_USER_ID}/media`, params, { timeoutMs: 60000 });
  return d.id;
}

export async function containerStatus(env, containerId) {
  const d = await call(env, 'GET', `/${containerId}`, { fields: 'status_code,status' });
  return { code: d.status_code, detail: d.status || null };
}

/**
 * Poll a container to FINISHED.
 *
 * A Reel container regularly takes 20-60s. The worker's own CPU budget is not
 * the constraint (this is nearly all wall-clock waiting), but a publish that
 * cannot finish inside one invocation must fail *without* consuming the
 * container — the next scheduler tick picks up the same container id and
 * resumes, which is exactly why `ig_creation_id` is persisted.
 */
export async function waitForContainer(env, containerId, { timeoutMs = 90000, intervalMs = 4000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    const st = await containerStatus(env, containerId);
    last = st;
    if (st.code === 'FINISHED') return st;
    if (st.code === 'ERROR' || st.code === 'EXPIRED') {
      throw new IgError(`container ${containerId} ${st.code}: ${st.detail || 'no detail'}`,
        { kind: st.code === 'EXPIRED' ? 'transient' : 'permanent' });
    }
    await sleep(intervalMs);
  }
  throw new IgError(
    `container ${containerId} still ${last ? last.code : 'unknown'} after ${timeoutMs}ms — will resume next tick`,
    { kind: 'transient' }
  );
}

export async function publishContainer(env, containerId) {
  const d = await call(env, 'POST', `/${env.IG_USER_ID}/media_publish`, {
    creation_id: containerId,
  }, { timeoutMs: 60000 });
  if (!d.id) throw new IgError('publish returned no media id', { kind: 'transient', body: JSON.stringify(d) });
  return d.id;
}

export async function mediaPermalink(env, mediaId) {
  const d = await call(env, 'GET', `/${mediaId}`, { fields: 'permalink,timestamp,media_type' });
  return d;
}

/**
 * Did a container we lost track of actually publish?
 *
 * The dangerous failure is a publish call that succeeded on Instagram's side and
 * timed out on ours. Before retrying we look at recent media and try to match;
 * if we find it, we adopt the existing post instead of making a second one.
 */
export async function findRecentByCaption(env, caption, { withinMs = 3600e3 } = {}) {
  const d = await call(env, 'GET', `/${env.IG_USER_ID}/media`, {
    fields: 'id,caption,timestamp,permalink,media_type',
    limit: 10,
  });
  const cutoff = Date.now() - withinMs;
  const needle = String(caption || '').trim().slice(0, 120);
  if (!needle) return null;
  for (const m of d.data || []) {
    const ts = Date.parse(m.timestamp || '');
    if (!Number.isFinite(ts) || ts < cutoff) continue;
    if (String(m.caption || '').trim().slice(0, 120) === needle) return m;
  }
  return null;
}

/**
 * Post performance. Metric names have churned across API versions, so unknown
 * metrics are dropped rather than failing the whole collection.
 */
export async function insights(env, mediaId, mediaType) {
  const metrics = mediaType === 'VIDEO' || mediaType === 'REELS'
    ? ['reach', 'likes', 'comments', 'shares', 'saved', 'views', 'ig_reels_video_view_total_time']
    : ['reach', 'likes', 'comments', 'shares', 'saved', 'profile_visits', 'follows', 'views'];
  try {
    const d = await call(env, 'GET', `/${mediaId}/insights`, { metric: metrics.join(',') });
    const out = {};
    for (const row of d.data || []) {
      const val = row.values && row.values[0] ? row.values[0].value : null;
      out[row.name] = val;
    }
    return out;
  } catch (e) {
    if (e instanceof IgError && e.kind === 'permanent') return {};
    throw e;
  }
}

/**
 * Long-lived tokens last 60 days and can be refreshed once they are 24h old.
 * Left un-refreshed, publishing dies silently two months after setup.
 */
export async function refreshToken(env) {
  const url = new URL('https://graph.instagram.com/refresh_access_token');
  url.searchParams.set('grant_type', 'ig_refresh_token');
  url.searchParams.set('access_token', env.IG_ACCESS_TOKEN);
  const res = await fetchT(url.toString(), {}, 20000);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.access_token) {
    throw new IgError(`token refresh failed: ${JSON.stringify(data).slice(0, 300)}`, { kind: 'auth' });
  }
  return { token: data.access_token, expiresIn: data.expires_in };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
