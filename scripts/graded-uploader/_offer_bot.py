"""The conversation brain — turns an incoming seller DM into an offer + a reply.

This is the orchestrator the messaging adapters (Instagram / FB review-queue) call.
Given message text (and any links/attachments), it:
  1. Detects what the seller sent — PSA cert #s, a PriceCharting/Collectr link, or a
     typed card list.
  2. Pulls the cards (importers) and prices them (engine → combined offer PDF).
  3. Decides the next move and drafts the reply.

Extraction is deterministic (regex for certs + known URLs). Free-text list parsing
and reply polish use the Claude API when ANTHROPIC_API_KEY is set; otherwise a clean
templated reply is used, so this runs today without a key for the link/cert flows.

  handle_message(text, sender=None) -> {
     "action": "offer" | "need_input" | "review",
     "reply":  str,                 # what to send the seller
     "offer":  <make_offer result or None>,
     "pdf_path": str | None,
     "items_found": int, "source": str,
  }

CLI:  python _offer_bot.py "<paste a seller message>"
"""
from __future__ import annotations

import os
import re
import sys

from _offer_engine import make_offer

PC_URL_RE = re.compile(r"https?://(?:www\.)?pricecharting\.com/offers\?[^\s]+", re.I)
COLLECTR_RE = re.compile(r"https?://app\.getcollectr\.com/showcase/profile/@?[^\s/]+", re.I)
CERT_RE = re.compile(r"\b(\d{8,9})\b")
SELL_HINT = re.compile(r"\b(sell|selling|offer|buy|trade|cash|cert|psa|cgc|bgs|slab|collection|list)\b", re.I)


def extract(text):
    """Pull structured sellable signals out of a raw message."""
    pc = PC_URL_RE.search(text or "")
    co = COLLECTR_RE.search(text or "")
    certs = CERT_RE.findall(text or "")
    return {"pc_url": pc.group(0) if pc else None,
            "collectr_url": co.group(0) if co else None,
            "certs": list(dict.fromkeys(certs))}


def gather_items(text):
    """Return (items, source) from whatever the message contains."""
    sig = extract(text)
    if sig["pc_url"]:
        from _import_lists import import_pricecharting, split_graded_raw
        items = import_pricecharting(sig["pc_url"])
        graded, raw = split_graded_raw(items)
        return items, f"PriceCharting list ({len(graded)} graded / {len(raw)} raw)"
    if sig["collectr_url"]:
        from _import_lists import import_collectr
        items = import_collectr(sig["collectr_url"])
        return items, f"Collectr showcase ({len(items)} items)"
    if sig["certs"]:
        return [{"cert": c} for c in sig["certs"]], f"{len(sig['certs'])} PSA cert #(s)"
    # no link or certs — free-text understanding happens in handle_message
    return [], "none"


# ── reply composition ────────────────────────────────────────────────────────
def _types_phrase(res):
    a = res["accepted"]
    g = sum(1 for r in a if r.get("type", "graded") == "graded")
    rw = sum(1 for r in a if r.get("type") == "raw")
    s = sum(1 for r in a if r.get("type") == "sealed")
    bits = [f"{n} {lbl}" for n, lbl in [(g, "graded"), (rw, "raw"), (s, "sealed")] if n]
    return ", ".join(bits) or f"{len(a)} card(s)"


def _vague_note(meta):
    v = meta.get("vague") or []
    if not v:
        return ""
    return ("\nFor the rest (" + "; ".join(v[:2]) + ") I'll need specifics to quote — send a "
            "**typed list** (card + set), **clear photos laid out**, or a "
            "**PriceCharting / Collectr link**, and any graded ones just drop the **cert #s**.")


def _asking_note(meta, res):
    """Gentle expectation-set when the seller named an asking price above our cash offer."""
    ask = meta.get("asking_price")
    if not ask or not res or not res.get("accepted"):
        return ""
    cash, cred = res["totals"]["cash"], res["totals"]["credit"]
    if ask > cash * 1.05:
        return (f"\nYou mentioned ${ask:,.0f} for the lot — heads up, we buy at a percentage of "
                f"market so we can resell, so my number lands at **${cash:,.0f} cash / "
                f"${cred:,.0f} store credit**. Store credit always stretches the furthest. 🙂")
    return ""


def _smart_ask(meta, res=None):
    """need-input reply that names what the seller mentioned + sets expectations."""
    meta = meta or {}
    named = meta.get("sealed_named") or []
    in_review = bool(res and res.get("review"))
    parts = ["Hey! 🐱 Happy to make you an offer."]
    if named:
        if in_review:
            parts.append("I'm confirming the current value on the **" + named[0] +
                         "** and will fold it into your offer.")
        else:
            parts.append("I can price the **" + named[0] + "** right away.")
    parts.append("For the singles I'll need the actual list to quote — send a **typed list** "
                 "(card + set), **clear photos laid out**, or a **PriceCharting / Collectr link**; "
                 "any graded ones, just drop the **cert #s**.")
    ask = meta.get("asking_price")
    if ask:
        parts.append(f"Quick heads-up so we're aligned: we buy at a percentage of market value "
                     f"(that's how we resell), so full retail around ${ask:,.0f} usually isn't doable — "
                     f"but once I see the list I'll send a clear written offer with **cash vs. store-credit**.")
    if not named and not ask:
        parts.append("Either way I'll price the whole lot and send a written offer right back. 👍")
    return _llm_polish_text(" ".join(parts))


def compose_reply(res, source, meta=None):
    meta = meta or {}
    if not res or not res["accepted"]:
        if res and res["rejected"] and not res["review"]:
            return ("Thanks for the list! Unfortunately these are all graded under $100, which we "
                    "can't take — the slab cost outweighs the card. Happy to look at anything else. 🙏")
        return _smart_ask(meta, res)
    t = res["totals"]
    lines = [
        f"Here's my offer on your {_types_phrase(res)} 👇",
        "",
        f"💵 **${t['cash']:,.2f} cash**  —  or  —  🎁 **${t['credit']:,.2f} store credit**",
        f"(on ${t['market']:,.2f} verified market value)",
        "",
        "Full card-by-card breakdown + how it works is in the attached PDF. Offer's good for 7 days.",
    ]
    if res["rejected"]:
        lines.append(f"\n(Note: {len(res['rejected'])} graded under $100 I can't take — slab cost outweighs them.)")
    if res["review"]:
        why = ", ".join(sorted({r["status"].replace("review_", "").replace("_", " ") for r in res["review"]}))
        lines.append(f"\n({len(res['review'])} item(s) I want to eyeball before quoting — {why} — I'll follow up.)")
    vn = _vague_note(meta)
    if vn: lines.append(vn)
    an = _asking_note(meta, res)
    if an: lines.append(an)
    lines.append("\nWant to move forward? I'll send packing + shipping details. 📦")
    return _llm_polish("\n".join(lines), res)


# ── main entry ───────────────────────────────────────────────────────────────
def handle_message(text, sender=None, out_stem="SakeKitty_Offer_incoming", use_ebay=True):
    items, source = gather_items(text)
    meta = {}
    if not items:                       # no link/cert → understand the free text
        meta = _understand(text)
        items = meta.get("items", [])
        source = f"{len(items)} parsed item(s)" if items else "free-text"

    if not items:
        return {"action": "need_input", "reply": compose_reply(None, source, meta),
                "offer": None, "pdf_path": None, "items_found": 0, "source": source}

    res = make_offer(items, out_stem=out_stem, use_ebay=use_ebay)
    reply = compose_reply(res, source, meta)
    action = "offer" if res["auto_ok"] else "review"
    # deal_rating is INTERNAL (Nick's review) — bubble it up alongside the offer, never into `reply`.
    return {"action": action, "reply": reply, "offer": res,
            "deal_rating": res.get("deal_rating"), "deal_label": res.get("deal_label"),
            "pdf_path": res["pdf_path"], "items_found": len(items), "source": source}


# ── optional Claude API hooks (no-op without ANTHROPIC_API_KEY) ───────────────
def _anthropic():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:
        return None


_MODEL = "claude-opus-4-8"
_POLISH_SYS = ("You are Sake Kitty Cards' friendly buyer texting a seller on Instagram. "
               "Keep it warm, concise, emoji-light, and DO NOT change any dollar amounts, "
               "counts, percentages, or the 7-day validity. Keep the markdown bold on prices.")


def _understand(text):
    """Free-text seller message → {items, vague, asking_price, sealed_named}.
    Claude when a key is set; regex fallback otherwise. Empty if not a sell message."""
    if not SELL_HINT.search(text or ""):
        return {"items": [], "vague": [], "asking_price": None, "sealed_named": []}
    u = _llm_understand(text)
    return u if u is not None else _basic_understand(text)


def _llm_understand(text):
    client = _anthropic()
    if not client:
        return None
    import json
    prompt = (
        "A person is messaging a Pokemon card shop to SELL. Extract ONLY this JSON object:\n"
        '{"items":[{"name":str,"set":str,"number":str,"grade":str,"kind":"graded|raw|sealed"}],'
        '"vague":[str],"asking_price":number_or_null,"sealed_named":[str]}\n'
        "Rules: items = only SPECIFIC named cards/products that can be looked up. A named sealed "
        'product IS an item with kind="sealed" — expand abbreviations (e.g. "Champions Path ETB" -> '
        'name "Champions Path Elite Trainer Box"). A generic phrase like "a bunch of EX/GX cards worth '
        '$1.2K" is NOT an item — put a short phrase in "vague". grade = "PSA 10" etc or "" if raw. '
        'asking_price = the total they want for everything in USD (1.2k -> 1200). sealed_named = '
        "display names of sealed products mentioned. Output ONLY the JSON.\n\nMessage:\n" + text)
    try:
        m = client.messages.create(model=_MODEL, max_tokens=1500,
                                   messages=[{"role": "user", "content": prompt}])
        raw = m.content[0].text
        d = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        for k, dv in (("items", []), ("vague", []), ("asking_price", None), ("sealed_named", [])):
            d.setdefault(k, dv)
        return d
    except Exception as e:
        print("[bot] understand failed:", e)
        return None


_PRICE_RE = re.compile(r"(?:looking for|want|asking|get|sell for)\s*\$?\s*([\d.,]+)\s*([kK])?", re.I)
_SEALED_NAME_RE = re.compile(
    r"((?:[A-Za-z0-9'&.]+\s+){0,4}(?:ETB|Elite Trainer Box|Booster Box|Booster Bundle|"
    r"Ultra[- ]Premium Collection|UPC|Collection Box|Tin))", re.I)


def _basic_understand(text):
    """Regex fallback: catch named sealed products, an asking price, and a vague-collection flag."""
    items, sealed_named, vague = [], [], []
    for m in _SEALED_NAME_RE.finditer(text or ""):
        nm = re.sub(r"\s+", " ", m.group(1)).strip()
        sealed_named.append(nm)
        items.append({"name": nm, "set": nm, "number": "", "grade": "", "kind": "sealed"})
    if re.search(r"collection|bunch|lot of|various|assorted|rare cards|bulk", text or "", re.I):
        vague.append("the loose cards you mentioned")
    ask = None
    pm = _PRICE_RE.search(text or "")
    if pm:
        try:
            n = float(pm.group(1).replace(",", ""))
            ask = n * 1000 if pm.group(2) else n
        except ValueError:
            pass
    return {"items": items, "vague": vague, "asking_price": ask, "sealed_named": sealed_named}


def _llm_polish(reply, res):
    """Rewrite a built offer reply in a warmer voice; falls back to the template."""
    client = _anthropic()
    if not client:
        return reply
    try:
        m = client.messages.create(model=_MODEL, max_tokens=700, system=_POLISH_SYS,
            messages=[{"role": "user", "content": "Polish this reply, keep all numbers exact:\n\n" + reply}])
        return m.content[0].text.strip()
    except Exception:
        return reply


def _llm_polish_text(text):
    """Polish a plain prompt-for-info reply (no offer numbers to protect beyond any quoted)."""
    client = _anthropic()
    if not client:
        return text
    try:
        m = client.messages.create(model=_MODEL, max_tokens=500, system=_POLISH_SYS,
            messages=[{"role": "user", "content": "Polish this into one natural DM, keep any dollar "
                       "amounts exact:\n\n" + text}])
        return m.content[0].text.strip()
    except Exception:
        return text


def main(argv):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    text = " ".join(argv) if argv else sys.stdin.read()
    out = handle_message(text)
    print("ACTION:", out["action"], "| source:", out["source"], "| items:", out["items_found"])
    if out["offer"]:
        print("SUMMARY:", out["offer"]["summary"], "| auto_ok:", out["offer"]["auto_ok"])
        dr, dl = out.get("deal_rating"), out.get("deal_label")
        if dr:
            print(f"DEAL RATING (internal): {dr}/10 ({dl})  liquidity {out['offer'].get('liquidity_rating')}  [10=amazing buy, 1=pass]")
        print("PDF:", out["pdf_path"])
    print("\n--- REPLY ---\n" + out["reply"])


if __name__ == "__main__":
    main(sys.argv[1:])
