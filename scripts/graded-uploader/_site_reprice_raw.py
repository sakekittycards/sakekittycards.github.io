"""Unified SITE pricing review — RAW SINGLES + SEALED pass (tcgsearch).

Methodology (user 2026-06-11): sell = max(tcgsearch market, recent-sold avg) x 1.03
(market or 3% above, minimal — covers the <=3% fee; shipping/tax separate).
"Sell everything at market or 3% above." No undercut. (Live-listings-only-raise
is a later refinement.)

Each Square single/sealed stores its TCGplayer productId as the variation SKU
(and "Card ID:" in the description), so we price via sk-scan-station/pricer.py:
  market + recent_sold (trimmed mean of recent clean sales) off tcgsearch.

Read-only review -> _site_reprice_raw_review.csv. Does NOT write to Square.
"""
from __future__ import annotations
import csv, json, math, os, re, subprocess, sys, threading, time
import urllib.request
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
SCAN = Path.home() / "OneDrive" / "Desktop" / "sk-scan-station"
sys.path.insert(0, str(SCAN))

WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{WORKER}/admin/inspect?types=ITEM"
FEE_MARKUP = 1.03

GRADER = re.compile(r"^(PSA|BGS|CGC|SGC|HGA|AGS|TAG|GMA|ISA|CSG)\s", re.I)
SEALED = re.compile(r"\b(booster|pack|etb|elite\s*trainer|tin|collection|bundle|deck|case|box)\b", re.I)
COND_MAP = {"NM": "Near Mint", "LP": "Lightly Played", "MP": "Moderately Played",
            "HP": "Heavily Played", "DMG": "Damaged", "DM": "Damaged"}


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


def price_of(it):
    for v in (it.get("item_data") or {}).get("variations", []):
        a = ((v.get("item_variation_data") or {}).get("price_money") or {}).get("amount")
        if a is not None: return a / 100
    return None


def cat(nm, desc):
    if GRADER.search(nm): return "graded"
    if re.match(r"^(?:19|20)\d{2}\s", nm): return "singles"
    if re.search(r"Card ID:", desc, re.I) and not SEALED.search(nm): return "singles"
    if SEALED.search(nm): return "sealed"
    return "merch"


def main():
    token = tok()
    if not token: print("SK_ADMIN_TOKEN not set"); return 1
    from pricer import Pricer

    items = inspect_all(token)
    work = []
    for it in items:
        d = it.get("item_data") or {}; nm = d.get("name", "") or ""; desc = d.get("description", "") or ""
        k = cat(nm, desc)
        if k not in ("singles", "sealed"): continue
        v = (d.get("variations") or [{}])[0]; vd = v.get("item_variation_data") or {}
        pid = (vd.get("sku") or "").strip()
        m = re.search(r"Card ID:\s*([0-9]+)", desc)
        if not pid and m: pid = m.group(1)
        if not pid or not pid.isdigit(): continue
        cm = re.search(r"Condition:\s*([A-Za-z]+)", desc)
        cond = COND_MAP.get((cm.group(1).upper() if cm else "NM"), "Near Mint")
        work.append({"pid": pid, "cond": cond, "cat": k, "name": nm, "cur": price_of(it)})

    print(f"RAW+SEALED review — {len(work)} items via tcgsearch (pricer.py). Grinding...", flush=True)
    pricer = Pricer()
    results = {}
    done = threading.Event(); remaining = {"n": len(work)}
    lock = threading.Lock()

    def mk_cb(w):
        def cb(res):
            results[w["pid"] + "|" + w["cat"]] = {**w, **res}
            with lock:
                remaining["n"] -= 1
                if remaining["n"] <= 0: done.set()
        return cb

    for w in work:
        pricer.submit(w["pid"], w["cond"], None, mk_cb(w))
    done.wait(timeout=420)

    rows = []
    for w in work:
        r = results.get(w["pid"] + "|" + w["cat"]) or w
        market = r.get("market"); recent = r.get("recent_sold")
        comp = max(market or 0, recent or 0)
        sell = math.ceil(comp * FEE_MARKUP) if comp > 0 else None
        delta = (sell - w["cur"]) if (sell and w["cur"] is not None) else None
        rows.append((w["cat"], w["pid"], w["cur"], market, recent, sell, delta,
                     r.get("n_sales", 0), w["name"]))

    rows.sort(key=lambda x: (x[0], -(abs(x[6]) if x[6] is not None else 0)))
    nopx = sum(1 for r in rows if r[5] is None)
    up = sum(1 for r in rows if r[6] and r[6] > 0.5)
    dn = sum(1 for r in rows if r[6] and r[6] < -0.5)
    print(f"\nRAW+SEALED — {len(rows)} items | sell=max(market,recent)x{FEE_MARKUP:.2f}")
    print(f"  RAISE {up} / LOWER {dn} / no-data {nopx}\n")
    print(f"  {'cat':<7} {'pid':>9} {'cur':>7} {'mkt':>7} {'recent':>7} {'NEW':>7} {'Δ':>7} {'n':>3}  card")
    for c, pid, cur, mkt, rec, sell, delta, n, nm in rows:
        f = lambda x: (f"{x:.0f}" if isinstance(x, (int, float)) else "—")
        print(f"  {c:<7} {pid:>9} {f(cur):>7} {f(mkt):>7} {f(rec):>7} {f(sell):>7} "
              f"{(('%+.0f'%delta) if delta is not None else '—'):>7} {n:>3}  {nm[:42]}")

    out = HERE / "_site_reprice_raw_review.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["cat", "pid", "current", "market", "recent_sold", "suggested", "delta", "n_sales", "card"])
        for r in rows: w.writerow(r)
    print(f"\n  review CSV -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
