/**
 * The activity stream.
 *
 * The design goal is that Nick can answer "what did the system do and why"
 * without opening `wrangler tail`. Every line is written to be read by a person:
 * a real sentence, with the subject named, not a key/value dump. The structured
 * bits go in `detail` for the console to expand.
 */

export async function log(env, level, scope, subject, message, detail = null, at = Date.now()) {
  try {
    await env.DB.prepare(
      'INSERT INTO activity (at, level, scope, subject, message, detail) VALUES (?,?,?,?,?,?)'
    ).bind(at, level, scope, subject, message, detail ? JSON.stringify(detail).slice(0, 8000) : null).run();
  } catch (e) {
    // Logging must never be the reason a publish fails.
    console.error('activity log failed:', String(e));
  }
}

export async function recent(env, { limit = 120, scope = null, subject = null } = {}) {
  let sql = 'SELECT * FROM activity';
  const binds = [];
  const where = [];
  if (scope) { where.push('scope = ?'); binds.push(scope); }
  if (subject) { where.push('subject = ?'); binds.push(subject); }
  if (where.length) sql += ' WHERE ' + where.join(' AND ');
  sql += ' ORDER BY at DESC LIMIT ?';
  binds.push(Math.min(limit, 500));
  const rows = await env.DB.prepare(sql).bind(...binds).all();
  return rows.results || [];
}

/**
 * Mirror the loud lines to Discord if a webhook is configured.
 *
 * Optional on purpose — the system is fully usable without it, and a Discord
 * outage must not surface as a publishing failure.
 */
export async function notify(env, text) {
  if (!env.DISCORD_WEBHOOK) return false;
  try {
    const r = await fetch(env.DISCORD_WEBHOOK, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ content: text.slice(0, 1900) }),
    });
    return r.ok;
  } catch {
    return false;
  }
}
