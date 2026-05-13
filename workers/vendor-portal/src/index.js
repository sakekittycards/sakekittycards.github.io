/**
 * Sake Kitty Vendor Portal — Cloudflare Worker
 *
 * Magic-link auth + outbound email + admin endpoints for the vendor portal at
 * https://sakekittycards.com/vendor-portal.html.
 *
 * Storage: a single KV namespace (VENDOR_KV) with three key prefixes:
 *   vendor:<email>   → { email, name, bookings: [...] }      (no TTL)
 *   token:<random>   → email                                  (TTL 1 hour)
 *   session:<random> → email                                  (TTL 30 days)
 *
 * Email: Resend (https://resend.com). Free tier is 3K emails/month — plenty
 * for vendor magic links + booking blasts.
 *
 * Deploy:    wrangler deploy
 * KV setup:  wrangler kv:namespace create VENDOR_KV  →  paste id into wrangler.toml
 * Secrets:   wrangler secret put RESEND_API_KEY
 *            wrangler secret put ADMIN_TOKEN
 */

const SESSION_COOKIE = 'sk_vendor_session';
const TOKEN_TTL_SECONDS = 60 * 60;          // magic links expire in 1 hour
const SESSION_TTL_SECONDS = 30 * 24 * 60 * 60;  // 30-day sessions

const ALLOWED_ORIGINS = new Set([
  'https://sakekittycards.com',
  'https://www.sakekittycards.com',
  'http://localhost:8080',
  'http://127.0.0.1:8080',
]);

function corsHeaders(req) {
  const origin = req.headers.get('Origin') || '';
  const allow = ALLOWED_ORIGINS.has(origin) ? origin : 'https://sakekittycards.com';
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, X-Sake-Admin-Token',
    'Access-Control-Allow-Credentials': 'true',
    'Vary': 'Origin',
  };
}

function jsonResp(req, body, init = {}) {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(req),
      ...(init.headers || {}),
    },
  });
}

function randHex(bytes = 32) {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('');
}

function parseCookies(req) {
  const cookie = req.headers.get('Cookie') || '';
  const out = {};
  cookie.split(';').forEach(part => {
    const [k, ...rest] = part.trim().split('=');
    if (k) out[k] = rest.join('=');
  });
  return out;
}

async function getSessionEmail(req, env) {
  const cookies = parseCookies(req);
  const sid = cookies[SESSION_COOKIE];
  if (!sid) return null;
  return await env.VENDOR_KV.get(`session:${sid}`);
}

async function sendEmail(env, { to, subject, html, text, replyTo }) {
  if (!env.RESEND_API_KEY) {
    throw new Error('RESEND_API_KEY secret not set — run `wrangler secret put RESEND_API_KEY`');
  }
  const r = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.RESEND_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: env.FROM_EMAIL || 'Sake Kitty Cards <nick@sakekittycards.com>',
      to: [to],
      subject,
      html,
      text,
      ...(replyTo ? { reply_to: replyTo } : {}),
    }),
  });
  if (!r.ok) {
    const errText = await r.text();
    throw new Error(`Resend ${r.status}: ${errText.slice(0, 300)}`);
  }
  return r.json();
}

function magicLinkEmail(link, name) {
  const greeting = name ? `Hey ${name},` : 'Hey,';
  const html = `
    <div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Inter,sans-serif;max-width:520px;padding:32px 28px;background:#0c0c14;color:#fff;border-radius:14px;line-height:1.55">
      <div style="font-family:Bangers,sans-serif;font-size:28px;letter-spacing:.04em;background:linear-gradient(135deg,#ff6a00,#ff0080);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px">Sake Kitty Cards</div>
      <div style="text-transform:uppercase;letter-spacing:1.5px;font-size:11px;color:rgba(255,255,255,0.55);margin-bottom:24px;font-weight:700">Vendor Portal · Log in</div>
      <p style="margin:0 0 18px">${greeting}</p>
      <p style="margin:0 0 24px">Click below to log in. This link works for 1 hour and can only be used once.</p>
      <p style="margin:0 0 28px">
        <a href="${link}" style="display:inline-block;padding:13px 24px;background:linear-gradient(135deg,#ff6a00,#ff0080);color:#fff;text-decoration:none;border-radius:8px;font-weight:800;letter-spacing:.3px;font-size:14px">Open the vendor portal →</a>
      </p>
      <p style="margin:0 0 4px;color:rgba(255,255,255,0.55);font-size:13px">If the button doesn't work:</p>
      <p style="margin:0 0 24px;color:rgba(255,255,255,0.45);font-size:12px;word-break:break-all">${link}</p>
      <p style="margin:0;color:rgba(255,255,255,0.40);font-size:12px;border-top:1px solid rgba(255,255,255,0.08);padding-top:18px">Didn't request this? You can ignore the email — your account stays locked.</p>
    </div>
  `;
  const text = `${greeting}\n\nLog in to the Sake Kitty Vendor Portal:\n${link}\n\n(Link expires in 1 hour and is single-use.)\n\nDidn't request this? Ignore this email.`;
  return { html, text };
}

function bookingsToHtml(bookings) {
  if (!bookings || !bookings.length) return '<p style="color:rgba(255,255,255,0.55);font-size:13px">No bookings on file yet.</p>';
  const rows = bookings.map(b => {
    const status = b.paid
      ? `<span style="color:#5fe39b;font-weight:700">Paid</span>`
      : `<span style="color:#ff7a3c;font-weight:700">$${b.owed} owed</span>`;
    const dateRange = b.endDate ? `${b.startDate} – ${b.endDate}` : b.startDate;
    return `<tr><td style="padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.08)">${b.event}</td><td style="padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.08);color:rgba(255,255,255,0.65)">${dateRange}</td><td style="padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.08);text-align:right">${status}</td></tr>`;
  }).join('');
  return `<table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:13px">${rows}</table>`;
}

function bookingBlastEmail(name, bookings, portalLink) {
  const html = `
    <div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Inter,sans-serif;max-width:560px;padding:32px 28px;background:#0c0c14;color:#fff;border-radius:14px;line-height:1.55">
      <div style="font-family:Bangers,sans-serif;font-size:28px;letter-spacing:.04em;background:linear-gradient(135deg,#ff6a00,#ff0080);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px">Sake Kitty Cards</div>
      <div style="text-transform:uppercase;letter-spacing:1.5px;font-size:11px;color:rgba(255,255,255,0.55);margin-bottom:22px;font-weight:700">Booking confirmation</div>
      <p style="margin:0 0 16px">Hey ${name || 'there'},</p>
      <p style="margin:0 0 12px">Here's where things stand on the shows you're booked for:</p>
      ${bookingsToHtml(bookings)}
      <p style="margin:16px 0 8px;color:rgba(255,255,255,0.86);font-weight:600">Payment</p>
      <p style="margin:0 0 10px;color:rgba(255,255,255,0.78);font-size:13px">Venmo · PayPal · Cash App. (No Zelle.) Anything outstanding, please send when you can.</p>
      <p style="margin:0 0 22px;padding:11px 14px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.22);border-radius:8px;color:rgba(255,255,255,0.86);font-size:13px"><strong style="color:#4dd9ff">Add in the payment note:</strong> Venue · # of tables · Event name. (e.g. "BCCC · 1 table · Card Party 7/26".) Makes reconciling 10× faster.</p>
      <p style="margin:0 0 26px">
        <a href="${portalLink}" style="display:inline-block;padding:12px 22px;background:linear-gradient(135deg,#ff6a00,#ff0080);color:#fff;text-decoration:none;border-radius:8px;font-weight:800;letter-spacing:.3px;font-size:14px">Open the vendor portal →</a>
      </p>
      <p style="margin:0;color:rgba(255,255,255,0.45);font-size:12px;border-top:1px solid rgba(255,255,255,0.08);padding-top:18px">Questions? Just reply — this email reaches Nick directly.</p>
    </div>
  `;
  const lines = (bookings || []).map(b => `• ${b.event} (${b.endDate ? b.startDate + ' – ' + b.endDate : b.startDate}) — ${b.paid ? 'PAID' : '$' + b.owed + ' owed'}`).join('\n');
  const text = `Hey ${name || 'there'},\n\nBooking status:\n${lines}\n\nPayment: Venmo · PayPal · Cash App (no Zelle).\nPlease include in the payment note: Venue · # of tables · Event name. (e.g. "BCCC · 1 table · Card Party 7/26")\n\nLog in to the portal: ${portalLink}\n\n— Nick · Sake Kitty Cards`;
  return { html, text };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const path = url.pathname;
    const method = req.method;

    if (method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(req) });
    }

    try {
      // ── Health check ────────────────────────────────────────────────
      if (path === '/health' || path === '/') {
        return jsonResp(req, { ok: true, service: 'sakekitty-vendor' });
      }

      // ── Vendor auth: magic-link request ─────────────────────────────
      if (path === '/vendor/login' && method === 'POST') {
        const { email } = await req.json();
        if (!email || typeof email !== 'string') {
          return jsonResp(req, { error: 'email required' }, { status: 400 });
        }
        const norm = email.trim().toLowerCase();
        const vendorJson = await env.VENDOR_KV.get(`vendor:${norm}`, 'json');
        // Don't reveal whether the email is on our list — same 200 either way
        // so attackers can't enumerate vendor addresses.
        if (vendorJson) {
          const token = randHex(32);
          await env.VENDOR_KV.put(`token:${token}`, norm, { expirationTtl: TOKEN_TTL_SECONDS });
          const link = `${env.SITE_BASE || 'https://sakekittycards.com'}/vendor-portal.html?auth=${token}`;
          const { html, text } = magicLinkEmail(link, vendorJson.name);
          await sendEmail(env, {
            to: norm,
            subject: 'Sake Kitty Vendor Portal — log in link',
            html,
            text,
          });
        }
        return jsonResp(req, { ok: true });
      }

      // ── Vendor auth: token → session cookie ─────────────────────────
      if (path === '/vendor/verify' && method === 'GET') {
        const token = url.searchParams.get('token');
        if (!token) return jsonResp(req, { error: 'token required' }, { status: 400 });
        const email = await env.VENDOR_KV.get(`token:${token}`);
        if (!email) {
          return jsonResp(req, { error: 'invalid or expired token' }, { status: 401 });
        }
        await env.VENDOR_KV.delete(`token:${token}`);
        const sid = randHex(32);
        await env.VENDOR_KV.put(`session:${sid}`, email, { expirationTtl: SESSION_TTL_SECONDS });
        return jsonResp(req, { ok: true, email }, {
          headers: {
            'Set-Cookie': `${SESSION_COOKIE}=${sid}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${SESSION_TTL_SECONDS}; Domain=.sakekittycards.com`,
          },
        });
      }

      // ── Vendor: current session ─────────────────────────────────────
      if (path === '/vendor/me' && method === 'GET') {
        const email = await getSessionEmail(req, env);
        if (!email) return jsonResp(req, { authenticated: false });
        const vendor = await env.VENDOR_KV.get(`vendor:${email}`, 'json');
        return jsonResp(req, { authenticated: true, email, vendor });
      }

      // ── Vendor: log out ─────────────────────────────────────────────
      if (path === '/vendor/logout' && method === 'POST') {
        const cookies = parseCookies(req);
        const sid = cookies[SESSION_COOKIE];
        if (sid) await env.VENDOR_KV.delete(`session:${sid}`);
        return jsonResp(req, { ok: true }, {
          headers: {
            'Set-Cookie': `${SESSION_COOKIE}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0; Domain=.sakekittycards.com`,
          },
        });
      }

      // ── Admin endpoints (X-Sake-Admin-Token gated) ──────────────────
      const adminTok = req.headers.get('X-Sake-Admin-Token');
      const isAdmin = adminTok && env.ADMIN_TOKEN && adminTok === env.ADMIN_TOKEN;

      if (path === '/admin/vendor/upsert' && method === 'POST') {
        if (!isAdmin) return jsonResp(req, { error: 'unauthorized' }, { status: 401 });
        const body = await req.json();
        const norm = (body.email || '').trim().toLowerCase();
        if (!norm) return jsonResp(req, { error: 'email required' }, { status: 400 });
        const record = {
          email: norm,
          name: body.name || '',
          bookings: body.bookings || [],
          updatedAt: new Date().toISOString(),
        };
        await env.VENDOR_KV.put(`vendor:${norm}`, JSON.stringify(record));
        return jsonResp(req, { ok: true, vendor: record });
      }

      if (path === '/admin/vendor/list' && method === 'GET') {
        if (!isAdmin) return jsonResp(req, { error: 'unauthorized' }, { status: 401 });
        const list = await env.VENDOR_KV.list({ prefix: 'vendor:' });
        const vendors = await Promise.all(list.keys.map(k => env.VENDOR_KV.get(k.name, 'json')));
        return jsonResp(req, { vendors: vendors.filter(Boolean) });
      }

      if (path === '/admin/vendor/delete' && method === 'POST') {
        if (!isAdmin) return jsonResp(req, { error: 'unauthorized' }, { status: 401 });
        const { email } = await req.json();
        const norm = (email || '').trim().toLowerCase();
        if (!norm) return jsonResp(req, { error: 'email required' }, { status: 400 });
        await env.VENDOR_KV.delete(`vendor:${norm}`);
        return jsonResp(req, { ok: true });
      }

      // POST /admin/blast — send a booking-status email to a vendor.
      //   { email }            — uses stored bookings to build the email
      //   { email, custom: { subject, html, text } }  — one-off custom email
      if (path === '/admin/blast' && method === 'POST') {
        if (!isAdmin) return jsonResp(req, { error: 'unauthorized' }, { status: 401 });
        const body = await req.json();
        const norm = (body.email || '').trim().toLowerCase();
        if (!norm) return jsonResp(req, { error: 'email required' }, { status: 400 });
        if (body.custom) {
          await sendEmail(env, {
            to: norm,
            subject: body.custom.subject,
            html: body.custom.html,
            text: body.custom.text,
          });
          return jsonResp(req, { ok: true });
        }
        const vendor = await env.VENDOR_KV.get(`vendor:${norm}`, 'json');
        if (!vendor) return jsonResp(req, { error: 'vendor not found' }, { status: 404 });
        const portalLink = `${env.SITE_BASE || 'https://sakekittycards.com'}/vendor-portal.html`;
        const { html, text } = bookingBlastEmail(vendor.name, vendor.bookings, portalLink);
        await sendEmail(env, {
          to: norm,
          subject: 'Your Sake Kitty bookings + payment status',
          html,
          text,
        });
        return jsonResp(req, { ok: true });
      }

      // POST /admin/blast-all — send to every vendor in KV.
      if (path === '/admin/blast-all' && method === 'POST') {
        if (!isAdmin) return jsonResp(req, { error: 'unauthorized' }, { status: 401 });
        const list = await env.VENDOR_KV.list({ prefix: 'vendor:' });
        const results = [];
        const portalLink = `${env.SITE_BASE || 'https://sakekittycards.com'}/vendor-portal.html`;
        for (const k of list.keys) {
          const vendor = await env.VENDOR_KV.get(k.name, 'json');
          if (!vendor) continue;
          try {
            const { html, text } = bookingBlastEmail(vendor.name, vendor.bookings, portalLink);
            await sendEmail(env, {
              to: vendor.email,
              subject: 'Your Sake Kitty bookings + payment status',
              html,
              text,
            });
            results.push({ email: vendor.email, ok: true });
          } catch (e) {
            results.push({ email: vendor.email, ok: false, error: e.message });
          }
        }
        return jsonResp(req, { ok: true, results });
      }

      return jsonResp(req, { error: 'not found', path }, { status: 404 });
    } catch (e) {
      return jsonResp(req, { error: e.message }, { status: 500 });
    }
  },
};
