/**
 * Sake Kitty Wholesale — first-touch auto-reply, Gmail arm.
 *
 * This script is deliberately thin. It reads candidate mail, asks the
 * Cloudflare Worker what to do with each message, and carries that out.
 * Every rule, every term list and the kill switch live in the Worker, so
 * changing behaviour never means editing this file.
 *
 * Setup is in README.md in this folder. In short:
 *   1. Script Properties: WORKER_URL, ADMIN_TOKEN, START_AFTER
 *   2. Services > add "Gmail API" (advanced service, identifier `Gmail`)
 *   3. Run installTriggers() once
 *
 * Nothing here can send mail while the Worker is in shadow mode, and the
 * Worker ships in shadow mode with the kill switch on.
 */

// ─── Configuration ─────────────────────────────────────────────────────────

var LABELS = {
  seen: 'SK-AutoReply/seen',
  wouldReply: 'SK-AutoReply/would-reply',
  drafted: 'SK-AutoReply/drafted',
  sent: 'SK-AutoReply/sent',
  routed: 'SK-AutoReply/routed-to-Nick',
  error: 'SK-AutoReply/error'
};

/** Mail we look at. Anything already seen is excluded by label. */
var SEARCH_QUERY = 'in:inbox newer_than:3d -label:' + LABELS.seen.replace(/\//g, '-');

/** Never process more than this many messages in one run. */
var MAX_PER_RUN = 15;

// ─── Entry points ──────────────────────────────────────────────────────────

/** Run once by hand after setting the Script Properties. */
function installTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger('processInbox').timeBased().everyMinutes(5).create();
  ScriptApp.newTrigger('sendDailyDigest').timeBased().atHour(7).everyDays(1).create();

  // Refuse to look at anything that arrived before installation, so turning
  // this on never blasts the backlog.
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('START_AFTER')) {
    props.setProperty('START_AFTER', String(Math.floor(Date.now() / 1000)));
  }

  Logger.log('Triggers installed. START_AFTER=' + props.getProperty('START_AFTER'));
}

/** The 5-minute job. */
function processInbox() {
  var cfg = readConfig();
  var startAfter = Number(cfg.startAfter || 0);

  var threads = GmailApp.search(SEARCH_QUERY, 0, MAX_PER_RUN);
  var seenLabel = ensureLabel(LABELS.seen);
  var processed = 0;

  for (var i = 0; i < threads.length; i++) {
    var thread = threads[i];
    var messages = thread.getMessages();

    // First touch only: we look at the first message of a thread, and only
    // when it is the only one.
    var msg = messages[0];
    if (!msg) continue;

    if (msg.getDate().getTime() / 1000 < startAfter) {
      thread.addLabel(seenLabel);
      continue;
    }

    try {
      handleMessage(msg, thread, messages.length, cfg);
    } catch (err) {
      Logger.log('ERROR on ' + msg.getId() + ': ' + err);
      thread.addLabel(ensureLabel(LABELS.error));
      try {
        post(cfg, '/wholesale/autoreply/record', {
          gmailMessageId: msg.getId(),
          action: 'error',
          error: String(err)
        });
      } catch (e2) { /* the log write is best-effort */ }
    }

    thread.addLabel(seenLabel);
    processed++;
  }

  Logger.log('processInbox: ' + processed + ' message(s)');
}

// ─── Per-message handling ──────────────────────────────────────────────────

function handleMessage(msg, thread, threadMessageCount, cfg) {
  var payload = {
    gmailMessageId: msg.getId(),
    gmailThreadId: thread.getId(),
    from: msg.getFrom(),
    subject: msg.getSubject(),
    bodyText: msg.getPlainBody(),
    headers: collectHeaders(msg),
    hasAttachments: msg.getAttachments({ includeInlineImages: false }).length > 0,
    threadMessageCount: threadMessageCount,
    labels: thread.getLabels().map(function (l) { return l.getName(); })
  };

  var res = post(cfg, '/wholesale/autoreply/classify', payload);
  if (!res) return;

  switch (res.action) {
    case 'route':
      thread.addLabel(ensureLabel(LABELS.routed));
      record(cfg, msg.getId(), 'labelled', null, null);
      break;

    case 'shadow':
      // Would have replied, but we are still only watching.
      thread.addLabel(ensureLabel(LABELS.wouldReply));
      record(cfg, msg.getId(), 'none', null, null);
      break;

    case 'draft': {
      var draftId = createDraft(res.reply, thread, msg);
      thread.addLabel(ensureLabel(LABELS.drafted));
      record(cfg, msg.getId(), 'drafted', draftId, null);
      break;
    }

    case 'send': {
      var sentId = sendReply(res.reply, thread, msg);
      thread.addLabel(ensureLabel(LABELS.sent));
      record(cfg, msg.getId(), 'sent', sentId, null);
      break;
    }

    default:
      // 'none' — dropped. Labelled seen by the caller, nothing else to do.
      break;
  }
}

/**
 * Build the RFC822 message. Done by hand rather than through GmailApp so we
 * can set Auto-Submitted, which is what stops two autoresponders talking to
 * each other forever.
 */
function buildRaw(reply, inReplyToMessage) {
  var lines = [];
  lines.push('From: Sake Kitty Wholesale <' + reply.from + '>');
  lines.push('To: ' + reply.to);
  lines.push('Subject: ' + encodeHeader(reply.subject));
  lines.push('MIME-Version: 1.0');
  lines.push('Content-Type: text/plain; charset=UTF-8');
  lines.push('Content-Transfer-Encoding: base64');
  lines.push('Auto-Submitted: auto-replied');
  lines.push('X-Auto-Response-Suppress: All');
  lines.push('Precedence: auto_reply');

  // Thread onto the original, unless it came through the site form, in
  // which case there is nothing of the sender's to reply to.
  if (!reply.newThread && inReplyToMessage) {
    var mid = inReplyToMessage.getHeader('Message-ID');
    if (mid) {
      lines.push('In-Reply-To: ' + mid);
      lines.push('References: ' + mid);
    }
  }

  lines.push('');
  lines.push(Utilities.base64Encode(Utilities.newBlob(reply.body).getBytes()));

  return Utilities.base64EncodeWebSafe(
    Utilities.newBlob(lines.join('\r\n')).getBytes()
  );
}

/** RFC 2047 encode a header value when it is not plain ASCII. */
function encodeHeader(value) {
  if (/^[\x20-\x7E]*$/.test(value)) return value;
  return '=?UTF-8?B?' + Utilities.base64Encode(Utilities.newBlob(value).getBytes()) + '?=';
}

function createDraft(reply, thread, msg) {
  var resource = { message: { raw: buildRaw(reply, msg) } };
  if (!reply.newThread) resource.message.threadId = thread.getId();
  var draft = Gmail.Users.Drafts.create(resource, 'me');
  return draft.id;
}

function sendReply(reply, thread, msg) {
  var resource = { raw: buildRaw(reply, msg) };
  if (!reply.newThread) resource.threadId = thread.getId();
  var sent = Gmail.Users.Messages.send(resource, 'me');
  return sent.id;
}

// ─── Daily digest ──────────────────────────────────────────────────────────

function sendDailyDigest() {
  var cfg = readConfig();
  var d = get(cfg, '/wholesale/autoreply/digest');
  if (!d) return;

  var L = [];
  L.push('Wholesale auto-reply — ' + new Date().toDateString());
  L.push('');
  L.push('Mode: ' + d.mode + (d.killSwitch ? '  (kill switch ON)' : ''));
  L.push('Clean drafts toward auto-send: ' + d.cleanDraftStreak + ' of ' + d.cleanDraftsRequired);
  L.push('');
  L.push('Last 24 hours: ' + d.last24h.total + ' message(s)');
  L.push('  auto-replied: ' + d.last24h.replied);
  L.push('  drafted:      ' + d.last24h.drafted);
  L.push('  routed to you:' + d.last24h.routed);
  L.push('  dropped:      ' + d.last24h.dropped);
  L.push('');

  if (d.last24h.rows.length) {
    L.push('Detail:');
    d.last24h.rows.forEach(function (r) {
      L.push('  [' + r.decision + '] ' + (r.sender_name || r.sender_email));
      L.push('      ' + (r.subject || '(no subject)'));
      L.push('      ' + r.reasons);
    });
    L.push('');
  }

  if (d.awaitingNick.count) {
    L.push('--- STILL WAITING ON YOU (' + d.awaitingNick.count + ') ---');
    d.awaitingNick.rows.forEach(function (r) {
      L.push('  ' + r.created_at.slice(0, 10) + '  ' + (r.sender_name || r.sender_email));
      L.push('      ' + (r.subject || '(no subject)'));
    });
  } else {
    L.push('Nothing routed to you is unanswered. ');
  }

  GmailApp.sendEmail(
    'nick@sakekittycards.com',
    'Wholesale auto-reply digest — ' + d.last24h.total + ' in, ' + d.awaitingNick.count + ' waiting on you',
    L.join('\n')
  );
}

// ─── Plumbing ──────────────────────────────────────────────────────────────

function readConfig() {
  var props = PropertiesService.getScriptProperties();
  var workerUrl = props.getProperty('WORKER_URL');
  var adminToken = props.getProperty('ADMIN_TOKEN');
  if (!workerUrl || !adminToken) {
    throw new Error('Set WORKER_URL and ADMIN_TOKEN in Script Properties first.');
  }
  return {
    workerUrl: workerUrl.replace(/\/+$/, ''),
    adminToken: adminToken,
    startAfter: props.getProperty('START_AFTER')
  };
}

function post(cfg, path, body) {
  return call(cfg, path, { method: 'post', payload: JSON.stringify(body) });
}

function get(cfg, path) {
  return call(cfg, path, { method: 'get' });
}

function call(cfg, path, opts) {
  var params = {
    method: opts.method,
    contentType: 'application/json',
    headers: {
      'X-Sake-Admin-Token': cfg.adminToken,
      // Cloudflare answers the default Apps Script agent with a 403/1010.
      'User-Agent': 'Mozilla/5.0 (compatible; SakeKittyWholesaleAutoReply/1.0)'
    },
    muteHttpExceptions: true
  };
  if (opts.payload) params.payload = opts.payload;

  var res = UrlFetchApp.fetch(cfg.workerUrl + path, params);
  var code = res.getResponseCode();
  var text = res.getContentText();

  if (code < 200 || code >= 300) {
    throw new Error('Worker ' + path + ' returned ' + code + ': ' + text.slice(0, 300));
  }
  return JSON.parse(text);
}

function record(cfg, gmailMessageId, action, resultMessageId, error) {
  post(cfg, '/wholesale/autoreply/record', {
    gmailMessageId: gmailMessageId,
    action: action,
    resultMessageId: resultMessageId,
    error: error
  });
}

function collectHeaders(msg) {
  var wanted = [
    'Auto-Submitted', 'List-Id', 'List-Unsubscribe', 'List-Post',
    'Precedence', 'In-Reply-To', 'References',
    'X-Autoreply', 'X-Autorespond', 'X-Auto-Response-Suppress'
  ];
  var out = {};
  wanted.forEach(function (h) {
    var v = msg.getHeader(h);
    if (v) out[h] = v;
  });
  return out;
}

function ensureLabel(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

// ─── Manual helpers ────────────────────────────────────────────────────────

/** Classify recent mail without acting on any of it. Safe to run any time. */
function dryRun() {
  var cfg = readConfig();
  var threads = GmailApp.search('in:inbox newer_than:14d', 0, 25);
  threads.forEach(function (thread) {
    var msg = thread.getMessages()[0];
    if (!msg) return;
    var res = post(cfg, '/wholesale/autoreply/classify', {
      gmailMessageId: 'dryrun-' + msg.getId(),
      gmailThreadId: thread.getId(),
      from: msg.getFrom(),
      subject: msg.getSubject(),
      bodyText: msg.getPlainBody(),
      headers: collectHeaders(msg),
      hasAttachments: msg.getAttachments().length > 0,
      threadMessageCount: thread.getMessageCount(),
      labels: []
    });
    Logger.log(res.decision + '  ' + msg.getFrom() + '  ' + res.reasons.join(', '));
  });
}
