"""One-shot: clear ALL graded + raw-single prices in Square -> Make Offer.

Nick 2026-06-15: graded prices were coming out wrong; stop auto-pricing and make
everything Make Offer. The site display is already forced to Make Offer for all
graded/raw/sealed; this also wipes the wrong PRICES out of Square so the backend
(POS/checkout) matches. Each cleared item becomes VARIABLE_PRICING (no price).

Graded -> /admin/clear-graded-price by "Cert #: <cert>" (from description).
Singles -> /admin/clear-single-price by "Card ID: <id>" (from description).
Sealed  -> no per-item clear endpoint (priced via /admin/sync-sealed-inventory);
           reported, not touched — the site shows Make Offer for it regardless.

Usage: python _clear_all_to_make_offer.py [--live]   (dry-run without --live)
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, urllib.error, urllib.request

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{WORKER}/admin/inspect?types=ITEM"
CLEAR_GRADED = f"{WORKER}/admin/clear-graded-price"
CLEAR_SINGLE = f"{WORKER}/admin/clear-single-price"
LIVE = "--live" in sys.argv
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
GRADER = re.compile(r"^(PSA|BGS|CGC|SGC|HGA|AGS|TAG|GMA|ISA|CSG)\b", re.I)
SEALED = re.compile(r"\b(booster|pack|etb|elite\s*trainer|tin|collection|bundle|deck|case|box)\b", re.I)
CERT_RX = re.compile(r"Cert\s*#?\s*:\s*([A-Za-z0-9\-]+)", re.I)
CARDID_RX = re.compile(r"Card\s*ID\s*:\s*([A-Za-z0-9\-]+)", re.I)


def _reg(name):
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command",
            f"[Environment]::GetEnvironmentVariable('{name}','User')"],
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""

def admin_tok():
    return (os.environ.get("SK_ADMIN_TOKEN") or _reg("SK_ADMIN_TOKEN")).strip()


def inspect_all(token):
    out, cur = [], None
    while True:
        u = INSPECT + (f"&cursor={cur}" if cur else "")
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={
            "X-Sake-Admin-Token": token, "User-Agent": UA, "Accept": "application/json"}), timeout=60).read())
        out += d.get("objects", []); cur = d.get("cursor")
        if not cur: break
    return out

def price_of(it):
    for v in (it.get("item_data") or {}).get("variations", []):
        a = ((v.get("item_variation_data") or {}).get("price_money") or {}).get("amount")
        if a is not None: return a / 100
    return None

def post(url, payload, token):
    req = urllib.request.Request(url, method="POST", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token, "User-Agent": UA})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def main():
    token = admin_tok()
    if not token: print("SK_ADMIN_TOKEN not set"); return 1
    items = inspect_all(token)
    graded, singles, sealed, skipped = [], [], [], []
    for it in items:
        d = it.get("item_data") or {}; nm = d.get("name", "") or ""; desc = d.get("description", "") or ""
        price = price_of(it)
        if GRADER.search(nm):
            m = CERT_RX.search(desc)
            (graded if m else skipped).append((nm, price, m.group(1) if m else None))
        elif SEALED.search(nm):
            sealed.append((nm, price))
        elif CARDID_RX.search(desc):
            singles.append((nm, price, CARDID_RX.search(desc).group(1)))
    print(f"INSPECT: {len(items)} items | graded {len(graded)} | singles {len(singles)} | "
          f"sealed {len(sealed)} | graded-no-cert {len(skipped)}")
    print(f"  mode: {'LIVE — clearing prices' if LIVE else 'DRY-RUN (pass --live)'}")

    g_ok = g_fail = s_ok = s_fail = 0
    for nm, price, cert in graded:
        if not LIVE:
            print(f"   [graded] would clear {cert}  ({nm[:46]}  ${price})"); continue
        try:
            r = post(CLEAR_GRADED, {"cert": cert}, token)
            if r.get("ok"): g_ok += 1
            else: g_fail += 1; print(f"   graded {cert}: {str(r)[:80]}")
        except urllib.error.HTTPError as e:
            if e.code != 404: g_fail += 1; print(f"   graded {cert}: {e.code}")
        except Exception as e:
            g_fail += 1; print(f"   graded {cert}: {str(e)[:80]}")
        time.sleep(0.2)
    for nm, price, cid in singles:
        if not LIVE:
            print(f"   [single] would clear {cid}  ({nm[:46]}  ${price})"); continue
        try:
            r = post(CLEAR_SINGLE, {"card_id": cid}, token)
            if r.get("ok"): s_ok += 1
            else: s_fail += 1; print(f"   single {cid}: {str(r)[:80]}")
        except urllib.error.HTTPError as e:
            if e.code != 404: s_fail += 1; print(f"   single {cid}: {e.code}")
        except Exception as e:
            s_fail += 1; print(f"   single {cid}: {str(e)[:80]}")
        time.sleep(0.2)

    if skipped:
        print("  graded items with NO parseable cert (left as-is):")
        for nm, price, _ in skipped: print(f"    {nm[:60]}  ${price}")
    sealed_priced = [s for s in sealed if s[1]]
    if sealed_priced:
        print(f"  SEALED with prices in Square ({len(sealed_priced)}) — site shows Make Offer; "
              f"no per-item clear endpoint, left in Square:")
        for nm, price in sealed_priced[:40]: print(f"    {nm[:60]}  ${price}")

    if LIVE:
        print(f"\n  CLEARED -> Make Offer: graded {g_ok} (fail {g_fail}) | singles {s_ok} (fail {s_fail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
