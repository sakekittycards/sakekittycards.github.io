/**
 * feeds — social feed poller for the Sake Kitty Discord.
 *
 * Posts new Instagram posts -> #instagram and new YouTube uploads -> #youtube,
 * via the channel webhooks. Runs on a cron; no inbound webhook from Meta is
 * involved (Instagram has no "my own new post" webhook field — the only reliable
 * path for your own media is polling the Graph API).
 *
 * Deliberately separate from the `ig-bot` worker: that one is the offer bot's DM
 * intake (inbound customer messages -> KV -> local pricing runner). This is
 * outbound announcements. They share nothing but the word "Instagram".
 *
 * Endpoints:
 *   GET /health          liveness + which feeds are configured
 *   GET /debug?key=...   what a run WOULD post, without posting (FEED_KEY auth)
 *
 * Cron: see wrangler.toml (default every 15 min).
 *
 * Bindings:
 *   FEEDS (KV)  — de-dupe state, one `seen:<src>:<id>` key per item
 * Secrets (wrangler secret put):
 *   DISCORD_IG_WEBHOOK_URL   — #instagram channel webhook
 *   DISCORD_YT_WEBHOOK_URL   — #youtube channel webhook
 *   IG_TOKEN                 — Instagram Graph API long-lived token (IG feed is
 *                              skipped when absent, so YT can ship without it)
 *   FEED_KEY                 — shared key for /debug
 * Vars (wrangler.toml):
 *   YT_CHANNEL_ID            — resolved from the @handle; RSS needs the UC… id
 */

const YT_FEED = (id) => `https://www.youtube.com/feeds/videos.xml?channel_id=${id}`;
const IG_FIELDS = "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp";
const IG_FEED = (t) => `https://graph.instagram.com/me/media?fields=${IG_FIELDS}&limit=10&access_token=${t}`;
// The square worker's /items is already public (shop.html fetches it straight from
// the browser), so the shop feed needs no Square token and no webhook subscription.
const SQUARE_ITEMS = "https://sakekitty-square.nwilliams23999.workers.dev/items";
const SHOP_URL = (id) => `https://sakekittycards.com/product.html?id=${id}`;

// Never fire more than this many posts in one run. A backlog (or a bad bootstrap)
// should not dump 40 messages into the channel.
const MAX_PER_RUN = 5;
// KV keys are cheap; keep them long enough that an item can't age out and re-post.
const SEEN_TTL = 60 * 60 * 24 * 365;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({
        ok: true,
        instagram: Boolean(env.IG_TOKEN && env.DISCORD_IG_WEBHOOK_URL),
        youtube: Boolean(env.YT_CHANNEL_ID && env.DISCORD_YT_WEBHOOK_URL),
        shop: Boolean(env.DISCORD_SITE_WEBHOOK_URL),
      });
    }

    if (url.pathname === "/debug") {
      if (!env.FEED_KEY || url.searchParams.get("key") !== env.FEED_KEY) {
        return json({ ok: false }, 401);
      }
      const [yt, ig, sq] = await Promise.all([
        fetchYouTube(env),
        fetchInstagram(env),
        fetchSquare(env),
      ]);
      return json({ ok: true, youtube: yt, instagram: ig, shop: sq });
    }

    return json({ ok: false, error: "not found" }, 404);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(runAll(env));
  },
};

async function runAll(env) {
  const results = await Promise.allSettled([
    syncFeed(env, "yt", fetchYouTube, env.DISCORD_YT_WEBHOOK_URL, ytEmbed),
    syncFeed(env, "ig", fetchInstagram, env.DISCORD_IG_WEBHOOK_URL, igEmbed),
    syncSquare(env, fetchSquare, env.DISCORD_SITE_WEBHOOK_URL),
  ]);
  for (const r of results) {
    if (r.status === "rejected") console.error("feed run failed:", r.reason);
  }
}

/**
 * Shop feed -> #site-updates. Two events, not one:
 *   - a product id we've never seen  -> "New in the shop"
 *   - a known product going out-of-stock -> in-stock -> "Back in stock"
 *
 * The restock case is why this can't reuse syncFeed: that one de-dupes on "have I
 * seen this id", which by definition never fires twice for the same product. Here
 * we track each item's last known stock state and post on the transition.
 *
 * Merch is print-on-demand and never goes OOS, so restocks are effectively cards
 * and sealed — which is the interesting signal anyway.
 */
export async function syncSquare(env, fetcher, webhook, post = postDiscord) {
  if (!webhook) return;
  const items = await fetcher(env);
  if (!items.length) return;

  const bootstrapped = await env.FEEDS.get("bootstrap:sq");
  const events = [];

  for (const item of items) {
    const prev = await env.FEEDS.get(`sq:${item.id}`);
    const now = item.inStock ? "1" : "0";
    if (prev === null) {
      if (bootstrapped) events.push({ item, kind: "new" });
    } else if (prev === "0" && now === "1") {
      events.push({ item, kind: "restock" });
    }
  }

  if (!bootstrapped) {
    // Record the whole catalogue as the baseline; announce none of it.
    await Promise.all(items.map((i) => env.FEEDS.put(`sq:${i.id}`, i.inStock ? "1" : "0")));
    await env.FEEDS.put("bootstrap:sq", new Date().toISOString());
    console.log(`sq: bootstrapped ${items.length} products (not posted)`);
    return;
  }

  const batch = events.sort((a, b) => a.item.createdAt - b.item.createdAt).slice(-MAX_PER_RUN);
  for (const ev of batch) {
    await post(webhook, squareEmbed(ev));
    await env.FEEDS.put(`sq:${ev.item.id}`, ev.item.inStock ? "1" : "0");
    console.log(`sq: posted ${ev.kind} ${ev.item.id}`);
  }
  // Track stock for everything else too, so an OOS now is a restock later. Items
  // that dropped out of the catalogue keep their key; harmless and cheap.
  await Promise.all(
    items
      .filter((i) => !batch.some((e) => e.item.id === i.id))
      .map((i) => env.FEEDS.put(`sq:${i.id}`, i.inStock ? "1" : "0"))
  );
}

async function fetchSquare(env) {
  const res = await fetch(env.SQUARE_ITEMS_URL || SQUARE_ITEMS, {
    headers: { "user-agent": "sakekitty-feeds/1.0" },
  });
  if (!res.ok) throw new Error(`square items ${res.status}`);
  const body = await res.json();
  return (body.items || []).map((i) => ({
    id: i.id,
    name: i.name,
    description: i.description || "",
    price: i.price,
    currency: i.currency || "USD",
    image: i.imageUrl || (i.imageUrls && i.imageUrls[0]) || null,
    inStock: Boolean(i.inStock),
    createdAt: i.createdAt ? Date.parse(i.createdAt) : 0,
  }));
}

export function squareEmbed({ item, kind }) {
  const isNew = kind === "new";
  return {
    content: isNew ? "🛍️ **New in the shop!**" : "♻️ **Back in stock!**",
    embeds: [
      {
        title: truncate(item.name, 240),
        description: truncate(item.description, 300),
        url: SHOP_URL(item.id),
        color: isNew ? 0x2ecc71 : 0x3498db,
        image: item.image ? { url: item.image } : undefined,
        fields:
          item.price != null
            ? [{ name: "Price", value: `$${item.price}`, inline: true }]
            : undefined,
        footer: { text: "sakekittycards.com" },
      },
    ],
  };
}

/**
 * Shared pipeline: pull items, drop the ones we've already announced, post the
 * rest oldest-first so the channel reads chronologically.
 *
 * First run for a source announces NOTHING — it just records the current items as
 * seen. Without this, enabling the feed would replay the entire back catalogue
 * into Discord.
 */
export async function syncFeed(env, src, fetcher, webhook, toEmbed, post = postDiscord) {
  if (!webhook) return;
  const items = await fetcher(env);
  if (!items.length) return;

  const bootstrapped = await env.FEEDS.get(`bootstrap:${src}`);
  const unseen = [];
  for (const item of items) {
    if (!(await env.FEEDS.get(`seen:${src}:${item.id}`))) unseen.push(item);
  }
  if (!unseen.length) return;

  if (!bootstrapped) {
    await Promise.all(unseen.map((i) => markSeen(env, src, i.id)));
    await env.FEEDS.put(`bootstrap:${src}`, new Date().toISOString());
    console.log(`${src}: bootstrapped ${unseen.length} existing items (not posted)`);
    return;
  }

  const batch = unseen.sort((a, b) => a.published - b.published).slice(-MAX_PER_RUN);
  for (const item of batch) {
    // Mark seen only after Discord accepts it, so a failed post retries next run.
    await post(webhook, toEmbed(item));
    await markSeen(env, src, item.id);
    console.log(`${src}: posted ${item.id}`);
  }
}

const markSeen = (env, src, id) =>
  env.FEEDS.put(`seen:${src}:${id}`, "1", { expirationTtl: SEEN_TTL });

async function fetchYouTube(env) {
  if (!env.YT_CHANNEL_ID) return [];
  const res = await fetch(YT_FEED(env.YT_CHANNEL_ID), {
    headers: { "user-agent": "sakekitty-feeds/1.0" },
  });
  if (!res.ok) throw new Error(`youtube rss ${res.status}`);
  return parseYouTube(await res.text());
}

// The RSS is small and predictably shaped; a regex walk beats pulling in an XML
// parser for four fields.
export function parseYouTube(xml) {
  const out = [];
  for (const entry of xml.split("<entry>").slice(1)) {
    const id = pick(entry, "yt:videoId");
    const title = pick(entry, "title");
    const published = pick(entry, "published");
    if (!id) continue;
    out.push({
      id,
      title: decodeXml(title || "New video"),
      url: `https://www.youtube.com/watch?v=${id}`,
      thumb: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`,
      published: published ? Date.parse(published) : 0,
    });
  }
  return out;
}

async function fetchInstagram(env) {
  if (!env.IG_TOKEN) return [];
  const res = await fetch(IG_FEED(env.IG_TOKEN));
  if (!res.ok) {
    // A dead/expired token is the common case here and it is not retryable —
    // surface it loudly rather than failing silently every 15 minutes forever.
    throw new Error(`instagram graph ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  const body = await res.json();
  return (body.data || []).map((m) => ({
    id: m.id,
    title: firstLine(m.caption) || "New post",
    caption: m.caption || "",
    url: m.permalink,
    thumb: m.media_type === "VIDEO" ? m.thumbnail_url : m.media_url,
    published: m.timestamp ? Date.parse(m.timestamp) : 0,
  }));
}

export function ytEmbed(item) {
  // Plain content (not an embed) so Discord unfurls the real YouTube player card.
  return { content: `🎬 **New video!**\n${item.url}` };
}

export function igEmbed(item) {
  return {
    content: "📸 **New Instagram post!**",
    embeds: [
      {
        title: truncate(item.title, 240),
        description: truncate(item.caption, 500),
        url: item.url,
        color: 0xff8fc7, // Kitten pink — matches the SK role color
        image: item.thumb ? { url: item.thumb } : undefined,
        footer: { text: "@sakekittycards" },
        timestamp: item.published ? new Date(item.published).toISOString() : undefined,
      },
    ],
  };
}

async function postDiscord(webhook, payload) {
  const res = await fetch(webhook, {
    method: "POST",
    // Send an explicit User-Agent: Discord blocklists some library defaults at the
    // edge — a real post with `Python-urllib/3.14` got a 403 while the identical
    // body with any other UA got a 200. Absence of a UA is fine, and so is curl's
    // default, so this is insurance against that class of block, not a requirement.
    headers: {
      "content-type": "application/json",
      "user-agent": "sakekitty-feeds/1.0 (+https://sakekittycards.com)",
    },
    body: JSON.stringify(payload),
  });
  if (res.status === 429) {
    const retry = Number(res.headers.get("retry-after") || 2);
    await sleep(Math.min(retry, 10) * 1000);
    return postDiscord(webhook, payload);
  }
  if (!res.ok) throw new Error(`discord ${res.status}: ${(await res.text()).slice(0, 200)}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function pick(xml, tag) {
  const m = xml.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`));
  return m ? m[1].trim() : "";
}

const decodeXml = (s) =>
  s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");

const firstLine = (s) => (s || "").split("\n")[0].trim();
const truncate = (s, n) => (!s ? undefined : s.length <= n ? s : s.slice(0, n - 1) + "…");

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}
