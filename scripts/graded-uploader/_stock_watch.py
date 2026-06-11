"""OS-level stock watch (run every 6h via Windows Task Scheduler).

Makes sure the top-50 raw singles listed on the website are STILL IN STOCK on
TCGplayer. Reads the newest `TCGplayer__MyPricing_*.csv` Nick exports to
Downloads, cross-checks every live single on Square (Card ID in its
description), and DELISTS any whose TCGplayer quantity has dropped to 0 (sold)
or that fell out of the export entirely.

Safety:
- Staleness guard: if the newest CSV is older than MAX_CSV_AGE_H, it only
  reports — it will NOT delist on stale data (env STALE_OK=1 overrides).
- DRY_RUN=1 reports without deleting.
- Appends a timestamped summary to _stock_watch.log and writes _stock_watch_status.json.

Env: SK_ADMIN_TOKEN (or the User env var, via get_token()).
"""
from __future__ import annotations
import csv, glob, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

from _multisource_reprice import WORKER_BASE, get_token

DOWNLOADS = Path(os.environ.get("DOWNLOADS_DIR", str(Path.home() / "Downloads")))
HERE = Path(__file__).resolve().parent
LOG = HERE / "_stock_watch.log"
STATUS = HERE / "_stock_watch_status.json"
TOP_N = int(os.environ.get("TOP_N", "50"))
MAX_CSV_AGE_H = float(os.environ.get("MAX_CSV_AGE_H", "26"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"
STALE_OK = os.environ.get("STALE_OK") == "1"
UA = {"User-Agent": "Mozilla/5.0"}


def num(x):
    try:
        return float((x or "0").replace(",", ""))
    except ValueError:
        return 0.0


def newest_csv() -> Path | None:
    files = glob.glob(str(DOWNLOADS / "TCGplayer__MyPricing_*.csv"))
    return Path(max(files, key=os.path.getmtime)) if files else None


def live_singles() -> list[dict]:
    """Square items that are raw singles (description carries 'Card ID:')."""
    import re
    d = json.loads(urllib.request.urlopen(
        urllib.request.Request(f"{WORKER_BASE}/items", headers=UA), timeout=90).read())
    items = d.get("items") or d.get("objects") or d
    out = []
    for i in items:
        desc = i.get("description") or ""
        m = re.search(r"Card ID:\s*(\S+)", desc)
        if m:
            out.append({"item_id": i.get("id"), "card_id": m.group(1).strip(),
                        "name": i.get("name", "")})
    return out


def delist(item_id: str, token: str) -> bool:
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{WORKER_BASE}/admin/delete-item", method="POST",
            data=json.dumps({"item_id": item_id}).encode(),
            headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token,
                     "User-Agent": "Mozilla/5.0"}), timeout=30)
        return True
    except Exception as e:
        log(f"   delete error {item_id}: {e!r}")
        return False


def log(msg: str):
    print(msg)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    log(f"\n===== stock-watch {now} =====")

    csv_path = newest_csv()
    if not csv_path:
        log(f"[stock] NO MyPricing CSV in {DOWNLOADS} — cannot check. Aborting.")
        return
    age_h = (time.time() - os.path.getmtime(csv_path)) / 3600
    log(f"[stock] CSV: {csv_path.name}  (age {age_h:.1f}h)")

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    owned_qty = {r["TCGplayer Id"]: num(r["Total Quantity"]) for r in rows}

    singles = live_singles()
    log(f"[stock] {len(singles)} singles live on site")

    sold, instock = [], []
    for s in singles:
        q = owned_qty.get(s["card_id"], 0)   # absent from export = treat as 0
        (instock if q > 0 else sold).append(s)

    log(f"[stock] in stock: {len(instock)} | SOLD/out: {len(sold)}")
    for s in sold:
        log(f"   SOLD  {s['card_id']}  {s['name']}")

    stale = age_h > MAX_CSV_AGE_H and not STALE_OK
    delisted = []
    if sold and stale:
        log(f"[stock] CSV is STALE (> {MAX_CSV_AGE_H}h) — NOT delisting. Export a fresh "
            f"MyPricing CSV (or set STALE_OK=1) to act.")
    elif sold and DRY_RUN:
        log("[stock] DRY_RUN — would delist the SOLD cards above.")
    elif sold:
        token = get_token()
        if not token:
            log("[stock] no SK_ADMIN_TOKEN — cannot delist.")
        else:
            for s in sold:
                if s["item_id"] and delist(s["item_id"], token):
                    delisted.append(s["card_id"])
                    log(f"   delisted {s['card_id']} {s['name']}")
                    time.sleep(0.3)

    # Informational: cards that are now top-N owned but not listed (needs relist).
    owned = [r for r in rows if num(r["Total Quantity"]) > 0 and num(r["TCG Market Price"]) > 0]
    owned.sort(key=lambda r: -num(r["TCG Market Price"]))
    top_ids = {r["TCGplayer Id"] for r in owned[:TOP_N]}
    listed_ids = {s["card_id"] for s in singles}
    missing = [r for r in owned[:TOP_N] if r["TCGplayer Id"] not in listed_ids]
    if missing:
        log(f"[stock] {len(missing)} top-{TOP_N} owned card(s) NOT listed (re-run lister to add):")
        for r in missing[:10]:
            log(f"   MISSING ${num(r['TCG Market Price']):.0f}  {r['TCGplayer Id']}  {r['Product Name']}")

    STATUS.write_text(json.dumps({
        "checked": now, "csv": csv_path.name, "csv_age_h": round(age_h, 1),
        "live": len(singles), "in_stock": len(instock), "sold": len(sold),
        "delisted": delisted, "stale_skipped": bool(sold and stale),
        "missing_top": [r["TCGplayer Id"] for r in missing],
    }, indent=2), encoding="utf-8")
    log(f"[stock] done. delisted {len(delisted)}.")


if __name__ == "__main__":
    main()
