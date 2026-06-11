"""GRADED re-verify — cardladder.py (fixed grade regex) + eBay sanity-gate.

For every graded slab:
  1. Price via LIVE cardladder.py last-5-no-outlier (routed through the sk-queue ->
     worker.py). Requires worker.py RESTARTED so it loads the loosened grade
     regex (accepts "GEM MT 10" / "PRISTINE 10" titles — see cardladder.py
     _GRADE_LABELS, fixed 2026-06-11 after the Chinese Pikachu underprice).
  2. SANITY-GATE: a card is SUSPECT if cardladder n_sales < 4 OR its price moved
     > DEV_PCT vs the current Square price. For suspects only, cross-check eBay
     last-sold; if cardladder vs eBay disagree by > EBAY_DISAGREE, trust eBay
     (more reliable when cardladder's text-search mismatched) and flag it.
  3. Push the final price (x1.03 already baked into each comp avg) to Square.

Dry-run by default -> _graded_verify_review.csv. --live pushes.
Usage:  python _reprice_graded_verify.py [export.csv] [--live]
"""
from __future__ import annotations
import csv, json, math, os, re, subprocess, sys, time, urllib.error, urllib.request, pathlib

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = pathlib.Path(__file__).resolve().parent
DOWN = pathlib.Path.home() / "Downloads"
SCAN = pathlib.Path.home() / "OneDrive" / "Desktop" / "sk-scan-station"
SQ = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{SQ}/admin/inspect?types=ITEM"
UPDATE = f"{SQ}/admin/update-graded-price"
QUEUE = "https://sk-queue.nwilliams23999.workers.dev"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
FEE = 1.03
DEV_PCT = 0.30          # >30% move vs current -> suspect, eBay-check
EBAY_DISAGREE = 0.20    # cardladder vs eBay differ >20% -> trust eBay
LIVE = "--live" in sys.argv


def app_key():
    f = SCAN / "queue.env"
    return (dict(re.findall(r"^(\w+)=(.+)$", f.read_text(), re.M)).get("APP_KEY", "").strip() if f.exists() else "")


def sktok():
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t: return t.strip()
    return subprocess.run(["powershell", "-NoProfile", "-Command",
        "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"], capture_output=True, text=True).stdout.strip()


def jget(url, hdr):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=40).read())


def jpost(url, body, hdr):
    r = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(), headers={**hdr, "content-type": "application/json"})
    try: return True, json.loads(urllib.request.urlopen(r, timeout=60).read())
    except urllib.error.HTTPError as e: return False, e.read().decode("utf-8", "replace")[:160]


def inspect_prices(tok):
    """cert -> current Square price."""
    out, cur = {}, None
    while True:
        d = jget(INSPECT + (f"&cursor={cur}" if cur else ""), {"X-Sake-Admin-Token": tok, "User-Agent": UA, "Accept": "application/json"})
        for it in d.get("objects", []):
            desc = (it.get("item_data") or {}).get("description", "") or ""
            m = re.search(r"Cert #:\s*(\d+)", desc)
            if not m: continue
            for v in (it.get("item_data") or {}).get("variations", []):
                a = ((v.get("item_variation_data") or {}).get("price_money") or {}).get("amount")
                if a is not None: out[m.group(1)] = a / 100; break
        cur = d.get("cursor")
        if not cur: break
    return out


def newest_export():
    fs = sorted(DOWN.glob("Collection - Card Ladder*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return fs[0] if fs else None


def clean_name(n):
    return re.sub(r"^\s*(full art|fa)\s*/\s*", "", n, flags=re.I).strip()


def parse_grade(cond):
    g = re.match(r"\s*([A-Za-z]+)", cond or ""); n = re.search(r"(\d+(?:\.\d+)?)", cond or "")
    return (g.group(1).upper() if g else "PSA"), (n.group(1) if n else "10")


def held():
    f = HERE / "_held_certs.txt"; out = set()
    if f.exists():
        for ln in f.read_text().splitlines():
            ln = ln.split("#", 1)[0].strip()
            if ln: out.add(ln)
    return out


def main():
    app = app_key()
    if not app: print("no APP_KEY"); return 1
    tok = sktok()
    src = next((pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")), None) or newest_export()
    if not src or not src.exists(): print("no export"); return 1
    HELD = held()

    cards = []
    for r in csv.DictReader(src.open(encoding="utf-8-sig")):
        cert = (r.get("Graded Cert #") or "").strip()
        if not cert or cert in HELD: continue
        grader, grade = parse_grade(r.get("Condition"))
        cv = float((r.get("Current Value") or "0").replace(",", "") or 0)
        cards.append({"cert": cert, "name": clean_name(r.get("Subject") or ""), "set": (r.get("Set") or "").strip(),
                      "number": (r.get("Number") or "").strip(), "grader": grader, "grade": grade,
                      "cv": (math.ceil(cv * FEE) if cv else None)})
    print(f"GRADED re-verify — {len(cards)} slabs (cardladder + eBay sanity-gate)")
    current = inspect_prices(tok)

    qh = {"x-app-key": app, "User-Agent": UA, "Accept": "application/json", "content-type": "application/json"}
    jobs = []
    for c in cards:
        try:
            jid = jpost(QUEUE + "/req", {"type": "price", "payload": {"graded": True, "name": c["name"],
                "set": c["set"], "number": c["number"], "grader": c["grader"], "grade": c["grade"]}}, qh)[1]["id"]
            jobs.append((c, jid))
        except Exception as e:
            print("  submit err", c["cert"], str(e)[:60])
    res = {}; deadline = time.time() + 700
    while len(res) < len(jobs) and time.time() < deadline:
        for c, jid in jobs:
            if jid in res: continue
            try:
                d = jget(QUEUE + "/req/" + jid, qh)
                if d.get("status") in ("done", "error"): res[jid] = d
            except Exception: pass
        if len(res) < len(jobs): time.sleep(2)

    # eBay helper (lazy import; only for suspects)
    def ebay_price(c):
        try:
            sys.path.insert(0, str(HERE))
            from _ebay_chrome import fetch_or_cache, average_last_5
            q = f"{c['name']} {c['number']} {c['set']} {c['grader']} {c['grade']}"
            g = fetch_or_cache({c["cert"]: q}, force_fresh=False)
            avg = average_last_5(g.get(c["cert"]) or g.get(q) or [], c["grade"])
            return (math.ceil(avg * FEE) if avg else None)
        except Exception as e:
            print("    ebay err", c["cert"], str(e)[:60]); return None

    rows = []
    for c, jid in jobs:
        d = res.get(jid, {}); cur = current.get(c["cert"])
        cl = None; n = 0
        if d.get("status") == "done":
            r = d["result"]; m = r.get("market"); n = r.get("n_sales") or 0
            cl = math.ceil(m * FEE) if m else None
        suspect = (n < 4) or (cl and cur and abs(cl - cur) / cur > DEV_PCT) or (cl is None)
        final, src_used, note = cl, "cardladder", ""
        if suspect:
            eb = ebay_price(c)
            cv = c.get("cv")
            # CV (the export Current Value) is the stable sanity anchor. Trust a
            # live source only if it's within 0.6-1.6x of CV; this rejects thin
            # eBay mismatches (Ceruledge $938 vs CV $50) AND cardladder mismatches
            # (Chinese Pikachu $3062 vs CV $4584) without dragging good fresh
            # comps to the stale CV (Pikachu eBay $5047 is 1.10x CV -> trusted).
            near = lambda x: bool(x and cv and 0.6 <= x / cv <= 1.6)
            if near(eb):
                final, src_used, note = eb, "ebay", f"suspect -> eBay {eb} (within band of CV {cv})"
            elif near(cl):
                final, src_used, note = cl, "cardladder", f"suspect(n={n}) -> cardladder {cl} (within band of CV {cv})"
            elif cv:
                final, src_used, note = cv, "cv", f"cl {cl}/eBay {eb} both off CV -> CV {cv}"
            elif eb:
                final, src_used, note = eb, "ebay", f"no CV; cardladder no-data -> eBay {eb}"
        rows.append({**c, "current": cur, "cl": cl, "n": n, "final": final, "src": src_used, "note": note})

    moved = [r for r in rows if r["final"] and r["current"] and abs(r["final"] - r["current"]) >= 1]
    print(f"  priced {sum(1 for r in rows if r['final'])}/{len(rows)} | ebay-overrides {sum(1 for r in rows if r['src']=='ebay')} | moved-vs-current {len(moved)}")
    for r in sorted(rows, key=lambda x: -(abs((x['final'] or 0)-(x['current'] or 0))))[:15]:
        print(f"    {r['cert']:<11} cur={str(r['current']):>7} -> {str(r['final']):>7} [{r['src']:<10} n={r['n']}] {r['name'][:26]} {r['note']}")
    with (HERE / "_graded_verify_review.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["cert", "name", "set", "grade", "current", "cardladder", "n_sales", "final", "source", "note"])
        for r in rows: w.writerow([r["cert"], r["name"], r["set"], f"{r['grader']} {r['grade']}", r["current"], r["cl"], r["n"], r["final"], r["src"], r["note"]])
    print("  review CSV -> _graded_verify_review.csv")

    if not LIVE:
        print("  [dry-run] pass --live to push"); return 0
    up = fail = 0
    for r in rows:
        if not r["final"]: continue
        ok, resp = jpost(UPDATE, {"cert": r["cert"], "price_cents": int(round(r["final"] * 100))}, {"X-Sake-Admin-Token": tok, "User-Agent": UA})
        if ok and (not isinstance(resp, dict) or resp.get("ok", True)): up += 1
        else: fail += 1; print("   push err", r["cert"], resp)
        time.sleep(0.25)
    print(f"  pushed {up} graded" + (f" ({fail} failed)" if fail else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
