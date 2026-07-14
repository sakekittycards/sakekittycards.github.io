/**
 * ig-bot — Instagram/Messenger webhook intake for the Sake Kitty offer bot.
 *
 * Why a Worker + a local runner (not all-in-Worker): pricing needs the local
 * Playwright stack (PSA cert lookup + tcgsearch + eBay all need a real browser on a
 * clean residential IP — a CF datacenter IP can't clear PSA's Cloudflare gate). So
 * this Worker is just the public webhook: it verifies the subscription, receives
 * inbound DMs, and parks them in KV. The local `_bot_runner.py` polls /pending,
 * prices + builds the PDF, and replies via the IG Send API directly.
 *
 * Endpoints:
 *   GET  /webhook            Meta verification handshake (hub.challenge)
 *   POST /webhook            Inbound message events  -> KV queue
 *   GET  /pending            Local runner pulls queued messages   (X-Bot-Key auth)
 *   POST /done               Local runner marks a message handled  (X-Bot-Key auth)
 *   GET  /health
 *
 * Secrets (wrangler secret put): VERIFY_TOKEN, APP_SECRET, BOT_KEY
 * KV binding: QUEUE
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const { pathname } = url;

    if (pathname === "/health") return json({ ok: true });

    // ── Meta verification handshake ──
    if (pathname === "/webhook" && request.method === "GET") {
      const mode = url.searchParams.get("hub.mode");
      const token = url.searchParams.get("hub.verify_token");
      const challenge = url.searchParams.get("hub.challenge");
      if (mode === "subscribe" && token === env.VERIFY_TOKEN) {
        return new Response(challenge, { status: 200 });
      }
      return new Response("forbidden", { status: 403 });
    }

    // ── inbound message events ──
    if (pathname === "/webhook" && request.method === "POST") {
      const body = await request.text();

      // Meta signs every webhook body with the app secret. Without this check the
      // endpoint takes anyone's JSON: a forged payload picks its own sender id, and
      // the local runner will price it and DM that person back. Verify before trust.
      //
      // When APP_SECRET is unset we accept-and-warn rather than reject, because that
      // is exactly today's deployed behaviour — this must not black-hole real DMs the
      // moment it ships. Setting the secret is what turns enforcement on.
      if (env.APP_SECRET) {
        const sig = request.headers.get("x-hub-signature-256");
        if (!(await verifySignature(body, sig, env.APP_SECRET))) {
          console.warn("webhook: bad or missing signature — rejected");
          return json({ ok: false, error: "bad signature" }, 403);
        }
      } else {
        console.warn("webhook: APP_SECRET unset — accepting UNVERIFIED payload");
      }

      let data;
      try { data = JSON.parse(body); } catch { return json({ ok: false }, 400); }
      const msgs = extractMessages(data);
      for (const m of msgs) {
        // de-dupe by message id; store newest-first queue entry
        await env.QUEUE.put(`msg:${m.mid}`, JSON.stringify({ ...m, status: "pending", ts: Date.now() }),
          { expirationTtl: 60 * 60 * 24 * 7 });
      }
      return json({ ok: true, queued: msgs.length });
    }

    // ── local runner: pull pending ──
    if (pathname === "/pending" && request.method === "GET") {
      if (request.headers.get("X-Bot-Key") !== env.BOT_KEY) return json({ ok: false }, 401);
      const list = await env.QUEUE.list({ prefix: "msg:" });
      const out = [];
      for (const k of list.keys) {
        const v = await env.QUEUE.get(k.name, "json");
        if (v && v.status === "pending") out.push(v);
      }
      return json({ ok: true, messages: out });
    }

    // ── local runner: mark handled ──
    if (pathname === "/done" && request.method === "POST") {
      if (request.headers.get("X-Bot-Key") !== env.BOT_KEY) return json({ ok: false }, 401);
      const { mid } = await request.json();
      const key = `msg:${mid}`;
      const v = await env.QUEUE.get(key, "json");
      if (v) { v.status = "done"; await env.QUEUE.put(key, JSON.stringify(v), { expirationTtl: 60 * 60 * 24 }); }
      return json({ ok: true });
    }

    return json({ ok: false, error: "not found" }, 404);
  },
};

/**
 * Verify Meta's `X-Hub-Signature-256: sha256=<hex>` — an HMAC-SHA256 of the RAW
 * request body under the app secret. It must be the raw text: re-serializing the
 * parsed JSON would change the bytes (key order, spacing) and never match.
 */
export async function verifySignature(rawBody, header, secret) {
  if (!header || !secret) return false;
  const [algo, sent] = header.split("=");
  if (algo !== "sha256" || !sent) return false;

  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(rawBody));
  const expected = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return timingSafeEqual(expected, sent.toLowerCase());
}

// Constant-time compare: a plain === leaks how much of the digest matched via
// early exit, which is enough to forge a signature byte by byte.
function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// Flatten IG/Messenger webhook payload -> [{mid, sender, text, attachments}]
// Messenger/IG deliver media as message.attachments[{type:"image|video|file|audio",
// payload:{url}}]. We forward those URLs so the local runner's media intake (screenshots,
// card photos, fan-through videos, csv/xlsx/pdf) can price them. A message with ONLY
// attachments (no text) is still queued.
function extractMessages(data) {
  const out = [];
  for (const entry of data.entry || []) {
    for (const ev of entry.messaging || []) {
      const msg = ev.message;
      if (!msg || msg.is_echo) continue;
      const atts = (msg.attachments || [])
        .filter((a) => a && a.payload && a.payload.url && a.type !== "audio")
        .map((a) => ({ type: a.type, url: a.payload.url }));
      if ((msg.text && msg.text.trim()) || atts.length) {
        out.push({
          mid: msg.mid, sender: ev.sender && ev.sender.id,
          text: msg.text || "", attachments: atts,
        });
      }
    }
  }
  return out;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });
}
