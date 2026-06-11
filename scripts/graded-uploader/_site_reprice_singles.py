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
import csv, json, math, os, re, subprocess, sys, urllib.request
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
DOWN = Path.home() / "Downloads"
WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{WORKER}/admin/inspect?types=ITEM"
UPDATE = f"{WORKER}/admin/update-single-price"
FEE = 1.03
LIVE = "--live" in sys.argv
GRADER = re.compile(r"^(PSA|BGS|CGC|SGC|HGA|AGS|TAG|GMA|ISA|CSG)\s", re.I)
SEALED = re.compile(r"\b(booster|pack|etb|elite\s*trainer|tin|collection|bundle|deck|case|box)\b", re.I)


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
        sell = math.ceil(mkt * FEE) if mkt > 0 else None
        rows.append(dict(sku=sku, setn=(r.get("Set Name") or "").strip(), name=(r.get("Product Name") or "").strip(),
            num=(r.get("Number") or "").strip(), cond=(r.get("Condition") or "").strip(),
            mkt=mkt, low=low, sell=sell, cur=cur, delta=(sell - cur if (sell and cur is not None) else None), miss=False))
    rows.sort(key=lambda z: -((z["cur"] or 0)))
    miss = sum(1 for z in rows if z.get("miss"))
    up = sum(1 for z in rows if z["delta"] and z["delta"] > 0.5)
    dn = sum(1 for z in rows if z["delta"] and z["delta"] < -0.5)
    print(f"SINGLES via SKU->{exp.name}.  sell=market x{FEE}  | {len(rows)} items, {miss} SKU-miss")
    print(f"  {up} raise / {dn} lower\n  {'cur':>7} {'mkt':>7} {'NEW':>7} {'d':>7}  card [cond]")
    for z in rows:
        if z.get("miss"):
            print(f"  {(z['cur'] or 0):>7.0f} {'?':>7} {'?':>7} {'?':>7}  {z['name'][:40]}  (SKU not in export)"); continue
        ds = f"{z['delta']:+.0f}" if z["delta"] is not None else "—"
        print(f"  {(z['cur'] or 0):>7.0f} {z['mkt']:>7.0f} {str(z['sell']):>7} {ds:>7}  {z['name'][:32]} #{z['num']} [{z['cond'][:20]}]")
    out = HERE / "_site_singles_review.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["sku", "set", "name", "number", "condition", "market", "low", "suggested", "current", "delta"])
        for z in rows:
            w.writerow([z["sku"], z.get("setn", ""), z["name"], z.get("num", ""), z.get("cond", ""),
                        z.get("mkt"), z.get("low"), z.get("sell"), z["cur"], z.get("delta")])
    print(f"\n  CSV -> {out.name}")

    if not LIVE:
        print("  [dry-run] pass --live to push prices to Square")
        return 0

    # ===== LIVE: push price-only updates by SKU (worker /admin/update-single-price) =====
    print("\n=== APPLYING singles to Square (price-only) ===")
    ok = fail = skip = 0
    import time as _t
    for z in rows:
        if z.get("miss") or not z.get("sell"):
            skip += 1; continue
        try:
            req = urllib.request.Request(UPDATE, method="POST",
                data=json.dumps({"card_id": z["sku"], "price_cents": int(round(z["sell"] * 100))}).encode(),
                headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0"})
            r = json.loads(urllib.request.urlopen(req, timeout=60).read())
            if r.get("ok"): ok += 1
            else: fail += 1; print(f"  ERR {z['sku']}: {r}")
        except Exception as e:
            fail += 1; print(f"  ERR {z['sku']}: {str(e)[:120]}")
        _t.sleep(0.3)
    print(f"  singles updated: {ok}/{len(rows)}  (skip {skip}, fail {fail})")
    return 2 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
