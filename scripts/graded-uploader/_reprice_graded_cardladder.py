"""GRADED reprice via LIVE cardladder.py — routed through the sk-queue.

Prices graded off CardLadder's last-5-most-recent-SOLD, outlier-trimmed average
(cardladder.py `last5_no_outlier`) — the CORRECT metric, NOT the export's stale
"Current Value" (which underpriced cards; user caught it 2026-06-11).

Mechanism (no classifier issue, no profile lock): submit `price` jobs to the
sk-queue (the same POST /req the phone uses) — the already-running worker.py
fulfills each with cardladder.py and posts the result back. We poll, take the
last-5-no-outlier market, x1.03, and push to Square (update-graded-price by cert).

REQUIRES: worker.py running AND its CardLadder session valid (run
`CardLadder Login.cmd` in sk-scan-station if it reports "session expired").
NOTE the Cloudflare bot wall: requests MUST send a browser User-Agent or they
get "error code: 1010" before the worker is even reached.

Usage:  python _reprice_graded_cardladder.py [sake_export.csv] [--live]
        (default export = newest 'Collection - Card Ladder*.csv' in Downloads)
"""
from __future__ import annotations
import csv, json, math, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
DOWN = Path.home() / "Downloads"
SCAN = Path.home() / "OneDrive" / "Desktop" / "sk-scan-station"
WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{WORKER}/admin/inspect?types=ITEM"
UPDATE = f"{WORKER}/admin/update-graded-price"
QUEUE = "https://sk-queue.nwilliams23999.workers.dev"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
FEE = 1.03
LIVE = "--live" in sys.argv


def _app_key():
    env = {}
    f = SCAN / "queue.env"
    if f.exists():
        env = dict(re.findall(r"^(\w+)=(.+)$", f.read_text(), re.M))
    return (env.get("APP_KEY") or "").strip()


def sktok():
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t: return t.strip()
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"],
        capture_output=True, text=True, timeout=10)
    return (r.stdout or "").strip() or None


def q_post(path, body, app):
    r = urllib.request.Request(QUEUE + path, method="POST", data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-app-key": app, "user-agent": UA, "accept": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())


def q_get(path, app):
    r = urllib.request.Request(QUEUE + path, headers={"x-app-key": app, "user-agent": UA, "accept": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())


def sq_post(url, body, tok):
    r = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "X-Sake-Admin-Token": tok, "user-agent": UA})
    try:
        return True, json.loads(urllib.request.urlopen(r, timeout=60).read())
    except urllib.error.HTTPError as e:
        return False, e.read().decode("utf-8", "replace")[:200]


def newest_export():
    fs = sorted(DOWN.glob("Collection - Card Ladder*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return fs[0] if fs else None


def parse_grade(cond):
    g = re.match(r"\s*([A-Za-z]+)", cond or ""); n = re.search(r"(\d+(?:\.\d+)?)", cond or "")
    return (g.group(1).upper() if g else "PSA"), (n.group(1) if n else "10")


def main():
    app = _app_key()
    if not app: print("no APP_KEY in sk-scan-station/queue.env"); return 1
    src = None
    for a in sys.argv[1:]:
        if not a.startswith("-"): src = Path(a)
    src = src or newest_export()
    if not src or not src.exists(): print("no Sake export"); return 1

    # cert -> card identity from the export
    cards = []
    for r in csv.DictReader(src.open(encoding="utf-8-sig")):
        cert = (r.get("Graded Cert #") or "").strip()
        if not cert: continue
        grader, grade = parse_grade(r.get("Condition"))
        cards.append({"cert": cert, "name": (r.get("Subject") or "").strip(),
                      "set": (r.get("Set") or "").strip(), "number": (r.get("Number") or "").strip(),
                      "grader": grader, "grade": grade,
                      "cv": float((r.get("Current Value") or "0").replace(",", "") or 0)})
    print(f"GRADED via cardladder.py (sk-queue) — {len(cards)} slabs. sell=last5-no-outlier x{FEE}")

    # submit all price jobs
    jobs = []
    for c in cards:
        try:
            jid = q_post("/req", {"type": "price", "payload": {"graded": True, "name": c["name"],
                "set": c["set"], "number": c["number"], "grader": c["grader"], "grade": c["grade"]}}, app)["id"]
            jobs.append((c, jid))
        except Exception as e:
            print(f"  submit ERR {c['cert']}: {str(e)[:80]}")
    # poll
    results = {}
    deadline = time.time() + 600
    pending = {jid: c for c, jid in jobs}
    while pending and time.time() < deadline:
        for jid in list(pending):
            try:
                d = q_get("/req/" + jid, app)
            except Exception:
                continue
            if d.get("status") in ("done", "error"):
                results[jid] = d; pending.pop(jid)
        if pending: time.sleep(2)

    rows, errs = [], 0
    for c, jid in jobs:
        d = results.get(jid) or {}
        if d.get("status") != "done":
            errs += 1; rows.append({**c, "market": None, "n": 0, "err": (d.get("result") or {}).get("error") if isinstance(d.get("result"), dict) else d.get("status")}); continue
        r = d["result"]; mkt = r.get("market")
        rows.append({**c, "market": mkt, "n": r.get("n_sales"), "sell": (math.ceil(mkt * FEE) if mkt else None)})
    ok = [r for r in rows if r.get("sell")]
    print(f"  priced: {len(ok)}/{len(cards)}  (errors {errs})")
    if errs and errs == len(cards):
        ex = next((r for r in rows if r.get("err")), {})
        print(f"  >>> all failed: {ex.get('err')}  (refresh CardLadder: run CardLadder Login.cmd)")
    for r in sorted(ok, key=lambda x: -(x["sell"] or 0))[:12]:
        print(f"    {r['cert']:<11} ${r['sell']:>6} (last5=${r['market']}, n={r['n']}, cv=${r['cv']:.0f})  {r['name'][:34]}")

    out = HERE / "_graded_cardladder_review.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["cert", "name", "set", "number", "grade", "last5_market", "n_sales", "current_value", "suggested"])
        for r in rows:
            w.writerow([r["cert"], r["name"], r["set"], r["number"], f"{r['grader']} {r['grade']}", r.get("market"), r.get("n"), r["cv"], r.get("sell")])
    print(f"  review CSV -> {out.name}")

    if not LIVE:
        print("  [dry-run] pass --live to push to Square"); return 0
    if not ok:
        print("  nothing priced — not pushing"); return 1
    tok = sktok()
    if not tok: print("SK_ADMIN_TOKEN not set"); return 1
    up = fail = 0
    for r in ok:
        good, resp = sq_post(UPDATE, {"cert": r["cert"], "price_cents": int(round(r["sell"] * 100))}, tok)
        if good and (not isinstance(resp, dict) or resp.get("ok", True)): up += 1
        else: fail += 1; print(f"  push ERR {r['cert']}: {resp}")
        time.sleep(0.3)
    print(f"  pushed {up}/{len(ok)} graded to Square" + (f" ({fail} failed)" if fail else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
