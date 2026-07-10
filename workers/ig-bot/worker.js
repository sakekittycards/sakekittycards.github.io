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
      // TODO(verify): validate X-Hub-Signature-256 against APP_SECRET before trusting.
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
