"""Local runner — the bridge between the IG webhook Worker and the offer engine.

Loop: poll the Worker's /pending queue → price each message with the bot →
  • auto_ok offer  → send the reply (+ offer link) via the IG Send API
  • needs review   → drop into the local review queue for Nick, send a holding note
then mark the message /done.

Runs on Nick's machine because pricing needs the local Playwright stack. Configure:
  SK_IG_WORKER   = https://sakekitty-ig-bot.<acct>.workers.dev
  SK_BOT_KEY     = same shared key as the Worker's BOT_KEY secret
  SK_IG_TOKEN    = the Page/IG access token (graph.facebook.com Send API)
  SK_OFFER_BASE  = public base URL where built PDFs are hosted (see note below)

IG send caveat: Instagram DMs don't accept arbitrary file (PDF) attachments the way
Messenger does. So we host the built PDF (push to R2 / the Worker / Square site) and
send the LINK in the message. `_host_pdf()` is the one hook to wire to your host.

  python _bot_runner.py once     # single drain pass (use_ebay on)
  python _bot_runner.py poll     # loop forever, 20s interval
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request
import json as _json

WORKER = os.environ.get("SK_IG_WORKER", "").rstrip("/")
BOT_KEY = os.environ.get("SK_BOT_KEY", "")
IG_TOKEN = os.environ.get("SK_IG_TOKEN", "")
OFFER_BASE = os.environ.get("SK_OFFER_BASE", "")
GRAPH = "https://graph.facebook.com/v21.0/me/messages"


def _get(path):
    req = urllib.request.Request(WORKER + path, headers={"X-Bot-Key": BOT_KEY})
    return _json.loads(urllib.request.urlopen(req, timeout=30).read())


def _post(path, body):
    req = urllib.request.Request(WORKER + path, method="POST",
                                 data=_json.dumps(body).encode(),
                                 headers={"X-Bot-Key": BOT_KEY, "content-type": "application/json"})
    return _json.loads(urllib.request.urlopen(req, timeout=30).read())


def _host_pdf(pdf_path):
    """Publish a built PDF and return its public URL. TODO: wire to your host
    (R2 bucket, the ig-bot Worker, or the Square/GitHub-Pages site). For now returns
    a constructed URL under SK_OFFER_BASE if set, else None (link omitted)."""
    if not pdf_path or not OFFER_BASE:
        return None
    from pathlib import Path
    return OFFER_BASE.rstrip("/") + "/" + Path(pdf_path).name


def ig_send_text(recipient_id, text):
    body = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    req = urllib.request.Request(f"{GRAPH}?access_token={IG_TOKEN}", method="POST",
                                 data=_json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    return _json.loads(urllib.request.urlopen(req, timeout=30).read())


def handle_one(m):
    from _offer_bot import handle_message
    sender = m.get("sender") or "ig"
    out = handle_message(m.get("text", ""), sender=sender,
                         out_stem=f"SakeKitty_Offer_{sender}_{m.get('mid','x')[:8]}",
                         use_ebay=True)
    reply = out["reply"]
    pdf_url = _host_pdf(out.get("pdf_path"))
    if pdf_url:
        reply += f"\n\n📄 Your written offer: {pdf_url}"

    # Nick-facing buy-quality tag for the runner log (internal — not sent to the seller)
    dr, dl = out.get("deal_rating"), out.get("deal_label")
    deal_tag = f"  [deal {dr}/10 {dl}]" if dr else ""

    if out["action"] == "offer" and out["offer"] and out["offer"]["auto_ok"]:
        # clean, fully-priced offer → auto-send (Instagram only)
        if IG_TOKEN:
            ig_send_text(sender, reply)
        print(f"[runner] AUTO-SENT to {sender}: {out['offer']['summary']}{deal_tag}")
    else:
        # needs eyes → park for Nick, send a holding note
        from _review_queue import add as queue_add
        rec = queue_add(m.get("text", ""), sender=sender, use_ebay=False)
        print(f"[runner] QUEUED #{rec['id']} for review ({out['source']}){deal_tag}")
        if IG_TOKEN:
            ig_send_text(sender, "Got your list! Pricing it up now — I'll send your offer shortly. 🐱")
    return out


def drain():
    if not WORKER or not BOT_KEY:
        print("[runner] set SK_IG_WORKER + SK_BOT_KEY first."); return 0
    msgs = _get("/pending").get("messages", [])
    print(f"[runner] {len(msgs)} pending")
    for m in msgs:
        try:
            handle_one(m)
        except Exception as e:
            print("[runner] error on", m.get("mid"), e)
        finally:
            _post("/done", {"mid": m.get("mid")})
    return len(msgs)


def main(argv):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    mode = argv[0] if argv else "once"
    if mode == "once":
        drain()
    elif mode == "poll":
        print("[runner] polling every 20s — Ctrl-C to stop")
        while True:
            try: drain()
            except Exception as e: print("[runner] drain error:", e)
            time.sleep(20)
    else:
        print("usage: _bot_runner.py once|poll")


if __name__ == "__main__":
    main(sys.argv[1:])
