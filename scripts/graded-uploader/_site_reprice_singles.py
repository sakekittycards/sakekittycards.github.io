"""SITE raw-singles pricing — EXACT via SKU -> TCGplayer MyPricing export.

The Square singles' variation SKU IS the TCGplayer SKU, which pins the exact
card + variant + condition. Join SKU -> newest Downloads\\TCGplayer__MyPricing_*.csv
"TCGplayer Id" -> "TCG Market Price" (already condition/variant-specific).
sell = market x 1.03 (market or 3% above; covers the <=3% fee). NO fuzzy
name/number matching against tcgsearch (numbers collide across sets -> wrong
variant). See memory feedback_site_pricing_methodology.

Read-only review -> _site_singles_review.csv. Does NOT write to Square.
"""
from __future__ import annotations
import csv, json, math, os, re, subprocess, sys, urllib.request, urllib.parse
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
DOWN = Path.home() / "Downloads"
WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{WORKER}/admin/inspect?types=ITEM"
UPDATE = f"{WORKER}/admin/update-single-price"
CLEAR = f"{WORKER}/admin/clear-single-price"
FEE = 1.03
LIVE = "--live" in sys.argv
GRADER = re.compile(r"^(PSA|BGS|CGC|SGC|HGA|AGS|TAG|GMA|ISA|CSG)\s", re.I)
SEALED = re.compile(r"\b(booster|pack|etb|elite\s*trainer|tin|collection|bundle|deck|case|box)\b", re.I)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
SB = "https://kwuqqoyuksvlnbgzaaim.supabase.co"
SB_KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt3dXFxb3l1a3N2bG5i"
          "Z3phYWltIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Mzk0NzA1NTIsImV4cCI6MjA1NTA0NjU1Mn0."
          "DIwS7KTAkLADALR8LMuzMvMP9Q3ErZgWsc3IWjMcjIs")


def _trim_mean(vals):
    v = sorted(float(x) for x in vals if x and float(x) > 0)
    if not v: return None
    if len(v) >= 5: v = v[1:-1]
    return round(sum(v) / len(v), 2)


def recent_sold(product_name, export_market):
    """Accurate recent-sold avg via tcgsearch Supabase (productId by exact name,
    market cross-checked vs the export) + TCGplayer mpapi /latestsales. Returns
    (recent_avg, productId). recent_avg is None when we can't get it ACCURATELY
    (no card match / market mismatch / no recent sales) -> caller shows Make Offer."""
    try:
        u = SB + "/rest/v1/cards?name=eq." + urllib.parse.quote(product_name) + \
            "&select=tcgplayer_product_id,tcgplayer_market_price&limit=2"
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u,
            headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY, "User-Agent": UA}), timeout=20).read())
    except Exception:
        return None, None
    if not d or not d[0].get("tcgplayer_product_id"):
        return None, None
    pid = d[0]["tcgplayer_product_id"]; sbm = d[0].get("tcgplayer_market_price")
    # confirm it's the right card: Supabase market must be near the export market
    if sbm and export_market and abs(float(sbm) - export_market) / export_market > 0.25:
        return None, pid
    try:
        req = urllib.request.Request(f"https://mpapi.tcgplayer.com/v2/product/{pid}/latestsales",
            method="POST", data=json.dumps({"listingType": "ListingWithoutPhotos", "limit": 25, "offset": 0}).encode(),
            headers={"User-Agent": UA, "Origin": "https://www.tcgplayer.com",
                     "Referer": "https://www.tcgplayer.com/", "Accept": "application/json", "Content-Type": "application/json"})
        sales = json.loads(urllib.request.urlopen(req, timeout=20).read()).get("data") or []
    except Exception:
        return None, pid
    prices = [s.get("purchasePrice") for s in sales if s.get("purchasePrice")][:10]
    return _trim_mean(prices), pid


def tok():
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t: return t.strip()
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"],
        capture_output=True, text=True, timeout=10)
    return (r.stdout or "").strip() or None


def inspect_all(token):
    out, cur = [], None
    while True:
        u = INSPECT + (f"&cursor={cur}" if cur else "")
        req = urllib.request.Request(u, headers={"X-Sake-Admin-Token": token,
            "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read())
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


def newest_mypricing():
    fs = sorted(DOWN.glob("TCGplayer__MyPricing_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return fs[0] if fs else None


def fnum(v):
    try: return float(str(v).replace("$", "").replace(",", "") or 0)
    except Exception: return 0.0


def main():
    token = tok()
    if not token: print("SK_ADMIN_TOKEN not set"); return 1
    pathargs = [a for a in sys.argv[1:] if not a.startswith("-")]
    exp = Path(pathargs[0]) if pathargs else newest_mypricing()
    if not exp or not exp.exists(): print("no TCGplayer MyPricing export in Downloads"); return 1
    idx = { (r.get("TCGplayer Id") or "").strip(): r
            for r in csv.DictReader(exp.open(encoding="utf-8-sig")) }

    items = inspect_all(token)
    rows = []
    for it in items:
        d = it.get("item_data") or {}; nm = d.get("name", "") or ""; desc = d.get("description", "") or ""
        if not is_single(nm, desc): continue
        v = (d.get("variations") or [{}])[0]; vd = v.get("item_variation_data") or {}
        sku = (vd.get("sku") or "").strip()
        r = idx.get(sku)
        cur = price_of(it)
        if not r:
            rows.append(dict(sku=sku, name=nm, cur=cur, mkt=None, sell=None, delta=None, miss=True)); continue
        mkt = fnum(r.get("TCG Market Price")); low = fnum(r.get("TCG Low Price"))
        cond = (r.get("Condition") or "").strip()
        is_nm = "near mint" in cond.lower() or cond.lower().startswith("nm")
        pname = (r.get("Product Name") or "").strip()
        # price = max(market, recent-sold) x1.03 — but ONLY when we have an
        # ACCURATE recent-sold (NM card + confirmed mpapi sales). Otherwise show
        # Make Offer rather than a market-only (possibly-stale/underpriced) number.
        rs, sell, offer = None, None, False
        if mkt > 0 and is_nm:
            rs, _pid = recent_sold(pname, mkt)
            if rs:
                sell = math.ceil(max(mkt, rs) * FEE)
            else:
                offer = True   # NM but no accurate recent-sold
        else:
            offer = True       # non-NM: no reliable condition-specific sold -> Make Offer
        rows.append(dict(sku=sku, setn=(r.get("Set Name") or "").strip(), name=pname,
            num=(r.get("Number") or "").strip(), cond=cond, mkt=mkt, low=low, recent=rs,
            sell=sell, offer=offer, cur=cur,
            delta=(sell - cur if (sell and cur is not None) else None), miss=False))
    rows.sort(key=lambda z: -((z["cur"] or 0)))
    miss = sum(1 for z in rows if z.get("miss"))
    priced = [z for z in rows if z.get("sell")]
    offers = [z for z in rows if z.get("offer")]
    print(f"SINGLES via SKU->{exp.name}.  sell=max(market,recent-sold)x{FEE} | {len(rows)} items")
    print(f"  priced {len(priced)} | make-offer {len(offers)} (no accurate recent-sold / non-NM) | SKU-miss {miss}")
    print(f"  {'cur':>7} {'mkt':>7} {'recent':>7} {'NEW':>7}  card [cond]")
    for z in priced:
        rec = z.get("recent")
        tag = " (recent>mkt)" if (rec and rec > z["mkt"]) else ""
        print(f"  {(z['cur'] or 0):>7.0f} {z['mkt']:>7.0f} {(rec or 0):>7.0f} {z['sell']:>7}  {z['name'][:30]} [{z['cond'][:14]}]{tag}")
    if offers:
        print("  --- Make Offer (no accurate recent-sold) ---")
        for z in offers: print(f"    {z['name'][:40]} [{z['cond'][:18]}]")
    out = HERE / "_site_singles_review.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["sku", "set", "name", "number", "condition", "market", "recent_sold", "suggested", "make_offer", "current"])
        for z in rows:
            w.writerow([z["sku"], z.get("setn", ""), z["name"], z.get("num", ""), z.get("cond", ""),
                        z.get("mkt"), z.get("recent"), z.get("sell"), bool(z.get("offer")), z["cur"]])
    print(f"\n  CSV -> {out.name}")

    if not LIVE:
        print("  [dry-run] pass --live to push to Square")
        return 0

    # ===== LIVE: price-only update (max market/recent) OR clear-to-Make-Offer =====
    print("\n=== APPLYING singles to Square ===")
    ok = cleared = fail = skip = 0
    import time as _t
    for z in rows:
        if z.get("miss"):
            skip += 1; continue
        try:
            if z.get("sell"):
                req = urllib.request.Request(UPDATE, method="POST",
                    data=json.dumps({"card_id": z["sku"], "price_cents": int(round(z["sell"] * 100))}).encode(),
                    headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token, "User-Agent": UA})
                if json.loads(urllib.request.urlopen(req, timeout=60).read()).get("ok"): ok += 1
                else: fail += 1
            elif z.get("offer"):
                req = urllib.request.Request(CLEAR, method="POST",
                    data=json.dumps({"card_id": z["sku"]}).encode(),
                    headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token, "User-Agent": UA})
                if json.loads(urllib.request.urlopen(req, timeout=60).read()).get("ok"): cleared += 1
                else: fail += 1
            else:
                skip += 1
        except Exception as e:
            fail += 1; print(f"  ERR {z['sku']}: {str(e)[:120]}")
        _t.sleep(0.3)
    print(f"  singles: {ok} priced, {cleared} -> Make Offer (skip {skip}, fail {fail})")
    return 2 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
