"""SITE raw-singles pricing — JustTCG (exact-SKU market) + TCGplayer mpapi (actual last-solds).

Per single (keyed by its Square variation SKU = the TCGplayer SKU, which pins the
EXACT product + condition + printing — zero wrong-variant risk):
  1. JustTCG `/v1/cards` by tcgplayerSkuId  -> exact-variant MARKET price + the
     card's tcgplayerId (productId) + the variant's condition + printing.
  2. TCGplayer mpapi `/v2/product/{pid}/latestsales` -> the ACTUAL recent sales;
     filter to the SAME condition + printing, last-5 non-outlier.
  3. price = max(market, recent-sold) x 1.03.

CRITICAL (user 2026-06-12): we must be CERTAIN we pulled real mpapi last-solds. If
mpapi errors / returns no sales / no sales match the exact condition+printing ->
PARK the card (Make Offer via /admin/clear-single-price). Never a guessed/market-
only number when the sold data isn't verified.

Usage: python _site_reprice_singles.py [--live]
"""
from __future__ import annotations
import json, math, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{WORKER}/admin/inspect?types=ITEM"
UPDATE = f"{WORKER}/admin/update-single-price"
CLEAR = f"{WORKER}/admin/clear-single-price"
FEE = 1.03
LIVE = "--live" in sys.argv
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
GRADER = re.compile(r"^(PSA|BGS|CGC|SGC|HGA|AGS|TAG|GMA|ISA|CSG)\s", re.I)
SEALED = re.compile(r"\b(booster|pack|etb|elite\s*trainer|tin|collection|bundle|deck|case|box)\b", re.I)


def _reg(name):
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command",
            f"[Environment]::GetEnvironmentVariable('{name}','User')"],
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""

def admin_tok():
    return (os.environ.get("SK_ADMIN_TOKEN") or _reg("SK_ADMIN_TOKEN")).strip()

def justtcg_key():
    return (_reg("JUSTTCG_API_KEY") or os.environ.get("JUSTTCG_API_KEY") or "tcg_4568319217c045bca50bc5664d6c5001").strip()


def inspect_all(token):
    out, cur = [], None
    while True:
        u = INSPECT + (f"&cursor={cur}" if cur else "")
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={
            "X-Sake-Admin-Token": token, "User-Agent": UA, "Accept": "application/json"}), timeout=60).read())
        out += d.get("objects", []); cur = d.get("cursor")
        if not cur: break
    return out

def is_single(nm, desc):
    if GRADER.search(nm): return False
    if re.match(r"^(?:19|20)\d{2}\s", nm): return True
    if re.search(r"Card ID:", desc, re.I) and not SEALED.search(nm): return True
    return False

def price_of(it):
    for v in (it.get("item_data") or {}).get("variations", []):
        a = ((v.get("item_variation_data") or {}).get("price_money") or {}).get("amount")
        if a is not None: return a / 100
    return None


def justtcg_by_skus(skus):
    """{sku: {market, pid, cond, printing, name}} via JustTCG /v1/cards (batches of 100)."""
    key = justtcg_key(); out = {}
    for i in range(0, len(skus), 100):
        batch = skus[i:i + 100]
        body = json.dumps([{"tcgplayerSkuId": s} for s in batch]).encode()
        req = urllib.request.Request("https://api.justtcg.com/v1/cards", method="POST", data=body,
            headers={"x-api-key": key, "Content-Type": "application/json", "User-Agent": "curl/8.7.1", "Accept": "application/json"})
        try:
            payload = json.loads(urllib.request.urlopen(req, timeout=40).read())
        except Exception as e:
            print(f"  [justtcg] batch err: {str(e)[:100]}"); continue
        for card in payload.get("data", []):
            pid = card.get("tcgplayerId")
            for v in card.get("variants", []):
                vs = str(v.get("tcgplayerSkuId") or "")
                if vs in batch:
                    out[vs] = {"market": v.get("price"), "pid": pid,
                               "cond": (v.get("condition") or "").strip(),
                               "printing": (v.get("printing") or "").strip(),
                               "name": card.get("name") or ""}
        time.sleep(0.7)
    return out


def mpapi_sold(pid, cond, printing):
    """ACTUAL last-solds off TCGplayer mpapi, filtered to EXACT condition+printing,
    last-5 non-outlier. Returns (avg, n_relevant, status). status: 'ok' | 'no_match'
    | 'no_data' | 'error'. We only PRICE on 'ok' (>=2 exact matches); anything else
    -> caller PARKS (must be certain we pulled real sold data)."""
    if not pid:
        return None, 0, "error"
    try:
        req = urllib.request.Request(f"https://mpapi.tcgplayer.com/v2/product/{pid}/latestsales",
            method="POST", data=json.dumps({"listingType": "ListingWithoutPhotos", "limit": 25, "offset": 0}).encode(),
            headers={"User-Agent": UA, "Origin": "https://www.tcgplayer.com", "Referer": "https://www.tcgplayer.com/",
                     "Accept": "application/json", "Content-Type": "application/json"})
        sales = json.loads(urllib.request.urlopen(req, timeout=20).read()).get("data")
    except Exception:
        return None, 0, "error"
    if sales is None:
        return None, 0, "error"
    if not sales:
        return None, 0, "no_data"
    rel = [s.get("purchasePrice") for s in sales
           if s.get("purchasePrice") and (s.get("condition") or "") == cond
           and (s.get("variant") or "Normal") == (printing or "Normal")]
    rel = [float(x) for x in rel if x][:5]
    if len(rel) < 2:
        return None, len(rel), "no_match"
    # last-5 EXCLUDING OUTLIERS: drop high+low, average the middle. The SKU already
    # pins the exact product+condition+printing, so these ARE the right card — the
    # spread is normal sale noise; the outlier trim handles it (no parking for it).
    p = sorted(rel)
    if len(p) >= 5: p = p[1:-1]
    return round(sum(p) / len(p), 2), len(rel), "ok"


def main():
    token = admin_tok()
    if not token: print("SK_ADMIN_TOKEN not set"); return 1
    items = inspect_all(token)
    singles = []
    for it in items:
        d = it.get("item_data") or {}; nm = d.get("name", "") or ""; desc = d.get("description", "") or ""
        if not is_single(nm, desc): continue
        v = (d.get("variations") or [{}])[0]; vd = v.get("item_variation_data") or {}
        sku = (vd.get("sku") or "").strip()
        if sku: singles.append({"sku": sku, "name": nm, "cur": price_of(it)})
    print(f"SINGLES: {len(singles)} | market=JustTCG(SKU) · last-sold=mpapi(exact cond+printing) · price=max x{FEE}")
    jt = justtcg_by_skus([s["sku"] for s in singles])

    rows = []
    for s in singles:
        j = jt.get(s["sku"])
        if not j or not j.get("market") or not j.get("pid"):
            rows.append({**s, "park": True, "why": "no JustTCG market/pid"}); continue
        market = float(j["market"]); cond = j["cond"]; printing = j["printing"]
        sold, n, status = mpapi_sold(j["pid"], cond, printing)
        if status != "ok":
            rows.append({**s, "market": market, "park": True, "why": f"mpapi {status}", "cond": cond, "printing": printing})
        else:
            sell = math.ceil(max(market, sold) * FEE)
            rows.append({**s, "market": market, "sold": sold, "n": n, "sell": sell,
                         "cond": cond, "printing": printing, "park": False,
                         "why": f"max(mkt {market:.0f}, sold {sold:.0f}) n={n}"})
        time.sleep(0.25)

    rows.sort(key=lambda r: -((r.get("cur") or 0)))
    priced = [r for r in rows if not r["park"]]
    parked = [r for r in rows if r["park"]]
    print(f"  PRICED {len(priced)} | PARKED(make-offer) {len(parked)}")
    print(f"  {'cur':>7} {'mkt':>7} {'sold':>7} {'NEW':>7}  card")
    for r in priced:
        tag = " (sold>mkt)" if r["sold"] > r["market"] else ""
        print(f"  {(r['cur'] or 0):>7.0f} {r['market']:>7.0f} {r['sold']:>7.0f} {r['sell']:>7}  {r['name'][:34]}{tag}")
    if parked:
        print("  --- PARKED (no verified mpapi last-solds) ---")
        for r in parked: print(f"    {r['name'][:40]}  [{r['why']}]")
    with (HERE / "_site_singles_review.csv").open("w", encoding="utf-8", newline="") as fh:
        import csv; w = csv.writer(fh)
        w.writerow(["sku", "name", "cond", "printing", "market", "sold", "n", "suggested", "parked", "why", "current"])
        for r in rows:
            w.writerow([r["sku"], r["name"], r.get("cond", ""), r.get("printing", ""), r.get("market"),
                        r.get("sold"), r.get("n"), r.get("sell"), r["park"], r["why"], r.get("cur")])
    print("  CSV -> _site_singles_review.csv")

    if not LIVE:
        print("  [dry-run] pass --live to push"); return 0
    ok = parkn = fail = 0
    for r in rows:
        try:
            if not r["park"]:
                req = urllib.request.Request(UPDATE, method="POST",
                    data=json.dumps({"card_id": r["sku"], "price_cents": int(round(r["sell"] * 100))}).encode(),
                    headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token, "User-Agent": UA})
                ok += 1 if json.loads(urllib.request.urlopen(req, timeout=60).read()).get("ok") else 0
            else:
                req = urllib.request.Request(CLEAR, method="POST",
                    data=json.dumps({"card_id": r["sku"]}).encode(),
                    headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token, "User-Agent": UA})
                parkn += 1 if json.loads(urllib.request.urlopen(req, timeout=60).read()).get("ok") else 0
        except Exception as e:
            fail += 1; print(f"  ERR {r['sku']}: {str(e)[:100]}")
        time.sleep(0.25)
    print(f"  singles: {ok} priced, {parkn} parked->Make Offer (fail {fail})")
    return 2 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
