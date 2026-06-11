"""Export-driven reconcile: fresh Sake CardLadder export  vs  live Square graded catalog.

Drives the reconcile DIRECTLY off the freshly-exported Sake collection CSV (the
graded slabs Nick actually owns), NOT off the stale pricing.csv. This avoids the
"delete everything because pricing.csv is stale" trap, and it follows the Square
inspect cursor so it sees the WHOLE catalog (not just page 1).

Buckets every Square graded item by its Cert # against the Sake export certs:
  KEEP + REPRICE : Square cert IS in the Sake export    -> price updated
  DELETE (sold)  : Square graded cert NOT in Sake export -> no longer owned, delist
  CL-ONLY (add?) : Sake cert NOT yet on Square           -> would ADD, but we DON'T
                   auto-add (user rule) — reported only, never inserted.

Price = CardLadder export "Current Value" x 1.00 — i.e. AT market (user 2026-06-11:
"i can be at market on the site, its fine"; superseded the earlier 1.15/1.10). Site
labels it "Market Price" and keeps Make Offer (no direct checkout).

DEFAULT IS DRY-RUN (read-only; only GETs /admin/inspect). Pass --live to actually
write: update-graded-price by cert (keepers) + delete-item by id (sold). CL-only
slabs are NEVER added, in either mode.

Usage:  python _sync_dryrun.py [export.csv] [--live]
        (export defaults to newest 'Collection - Card Ladder*.csv' in Downloads)
"""
from __future__ import annotations
import argparse, csv, json, math, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
DOWN = Path.home() / "Downloads"
WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{WORKER}/admin/inspect?types=ITEM"
UPDATE_PRICE = f"{WORKER}/admin/update-graded-price"
DELETE_ITEM = f"{WORKER}/admin/delete-item"
MARKUP = 1.03   # market or 3% above (covers <=3% fee; "sell everything at market or 3% above").


def tok() -> str | None:
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t: return t.strip()
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
            "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"],
            capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip() or None
    except Exception: return None


def get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def post_json(url: str, body: dict, token: str) -> tuple[bool, dict | str]:
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token,
                 "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return True, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return False, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return False, str(e)


def inspect_all(token: str) -> list[dict]:
    """Follow the cursor so we see the WHOLE catalog, not just page 1."""
    out, cursor = [], None
    while True:
        url = INSPECT + (f"&cursor={cursor}" if cursor else "")
        d = get_json(url, token)
        out.extend(d.get("objects", []))
        cursor = d.get("cursor")
        if not cursor: break
    return out


def is_graded(it: dict) -> bool:
    data = it.get("item_data") or {}
    name = (data.get("name") or "").lower(); desc = (data.get("description") or "").lower()
    if "cert #" in desc: return True
    return any(k in name for k in (" psa ", " cgc ", " bgs ", " sgc ")) \
        or name.startswith(("psa ", "cgc ", "bgs ", "sgc "))


def cert_of(it: dict) -> str | None:
    desc = (it.get("item_data") or {}).get("description", "") or ""
    m = re.search(r"Cert #:\s*(\d+)", desc)
    return m.group(1) if m else None


def load_held() -> set[str]:
    """Certs reserved/held for a customer — never list; remove from site if present."""
    f = HERE / "_held_certs.txt"
    out = set()
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            ln = ln.split("#", 1)[0].strip()
            if ln: out.add(ln)
    return out


def newest_export() -> Path | None:
    fs = sorted(DOWN.glob("Collection - Card Ladder*.csv"),
                key=lambda p: p.stat().st_mtime, reverse=True)
    return fs[0] if fs else None


def load_sake(p: Path) -> dict[str, dict]:
    """cert -> {name, grade, value, price} from the CardLadder export."""
    out = {}
    for r in csv.DictReader(p.open("r", encoding="utf-8-sig")):
        cert = (r.get("Graded Cert #") or "").strip()
        if not cert: continue
        try: val = float((r.get("Current Value") or "0").replace(",", "") or 0)
        except ValueError: val = 0.0
        out[cert] = {"name": (r.get("Card") or "").strip(),
                     "grade": (r.get("Condition") or "").strip(),
                     "value": val,
                     "price": math.ceil(val * MARKUP) if val else 0}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("export", nargs="?", default=None)
    ap.add_argument("--live", action="store_true", help="apply writes to Square (default: dry-run)")
    args = ap.parse_args()
    LIVE = args.live

    token = tok()
    if not token: print("SK_ADMIN_TOKEN not set"); return 1

    src = Path(args.export) if args.export else newest_export()
    if not src or not src.exists(): print("no Sake export found"); return 1
    sake = load_sake(src)
    held = load_held()
    sake_certs = set(sake) - held   # held slabs are not sellable inventory
    print(f"Sake export : {src.name}")
    print(f"            : {len(sake)} graded slabs owned (unique certs)  | mode={'LIVE' if LIVE else 'DRY-RUN'}")
    if held: print(f"            : {len(held)} HELD cert(s) excluded (reserved for customers)")
    print()

    print("Inspecting Square catalog (all pages)...")
    items = inspect_all(token)
    graded = [i for i in items if is_graded(i)]
    print(f"Square      : {len(items)} items total | {len(graded)} graded | "
          f"{len(items)-len(graded)} merch/singles (never touched)\n")

    keep, delete, held_on_site, no_cert = [], [], [], []   # tuples: (cert, item_id, name)
    sq_certs = set()
    for it in graded:
        c = cert_of(it); nm = (it.get("item_data") or {}).get("name", ""); iid = it.get("id")
        if not c: no_cert.append(nm); continue
        sq_certs.add(c)
        if c in held:                       # reserved -> must come OFF the site
            held_on_site.append((c, iid, nm))
        elif c in sake_certs:               # owned & sellable -> reprice
            keep.append((c, iid, nm))
        else:                               # not in Sake -> sold straggler
            delete.append((c, iid, nm))
    # held slabs on the site are deleted just like sold ones
    delete.extend(held_on_site)
    add_candidates = sorted(sake_certs - sq_certs)

    print("=== RECONCILE (%s) ===" % ("LIVE" if LIVE else "DRY-RUN, nothing written"))
    print(f"KEEP + REPRICE : {len(keep):>3}  (Square cert in Sake export)")
    print(f"DELETE         : {len(delete):>3}  (sold stragglers + {len(held_on_site)} held-on-site)")
    print(f"CL-ONLY        : {len(add_candidates):>3}  (in Sake, not on site — auto-add is OFF)")
    if no_cert:
        print(f"NO CERT PARSED : {len(no_cert):>3}  (graded on Square w/o readable Cert # — never deleted)")

    print("\n--- KEEP & new Market Price (CL value x1.10) ---")
    for c, _iid, nm in sorted(keep, key=lambda x: -sake[x[0]]["price"]):
        s = sake[c]
        print(f"  cert {c:<11} ${s['price']:>6}  (val ${s['value']:.2f})  {nm[:60]}")

    print("\n--- DELETE (off the site: sold or held) ---")
    if not delete: print("  (none — Square has no sold/held graded item)")
    for c, _iid, nm in delete:
        tag = "[HELD] " if c in held else "[sold] "
        print(f"  {tag}cert {c:<11}  {nm[:65]}")

    print("\n--- CL-ONLY (owned per CardLadder, not yet on site) — NOT added automatically ---")
    if not add_candidates: print("  (none — every Sake slab already has a Square listing)")
    for c in add_candidates:
        s = sake[c]
        print(f"  cert {c:<11} ${s['price']:>6}  {s['name'][:60]}")

    if no_cert:
        print("\n--- graded on Square with NO parseable Cert # (left alone) ---")
        for nm in no_cert: print(f"  {nm[:75]}")

    if not LIVE:
        print("\n[dry-run only — no Square writes]")
        return 0

    # ===== LIVE EXECUTE (gated by --live / SK_SYNC_LIVE=1 upstream) =====
    print("\n=== APPLYING TO SQUARE ===")
    ok_u = fail_u = 0
    for c, _iid, nm in keep:
        cents = int(round(sake[c]["price"] * 100))
        if cents <= 0:
            print(f"  SKIP cert {c} (no price)"); continue
        ok, resp = post_json(UPDATE_PRICE, {"cert": c, "price_cents": cents}, token)
        if ok and (not isinstance(resp, dict) or resp.get("ok", True)):
            ok_u += 1
        else:
            fail_u += 1
            print(f"  ERR price cert {c}: {resp if isinstance(resp, str) else resp.get('error','?')}")
        time.sleep(0.35)
    print(f"  prices updated: {ok_u}/{len(keep)}" + (f"  ({fail_u} failed)" if fail_u else ""))

    ok_d = fail_d = 0
    for c, iid, nm in delete:
        ok, resp = post_json(DELETE_ITEM, {"item_id": iid}, token)
        if ok: ok_d += 1
        else:
            fail_d += 1
            print(f"  ERR delete {iid}: {resp if isinstance(resp, str) else resp.get('error','?')}")
        time.sleep(0.3)
    print(f"  sold deleted: {ok_d}/{len(delete)}" + (f"  ({fail_d} failed)" if fail_d else ""))

    print(f"\n[LIVE done] repriced {ok_u}, deleted {ok_d}, added 0 (auto-add off)")
    return 2 if (fail_u or fail_d) else 0


if __name__ == "__main__":
    raise SystemExit(main())
