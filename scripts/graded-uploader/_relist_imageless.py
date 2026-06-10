"""Re-list the entire graded catalog from a Card Ladder CSV with NO image and an
"(image soon)" title tag — Nick is shooting his own photos (2026-06-10).

No eBay scraping, no images: just create one imageless graded listing per CSV
row. The worker appends "(image soon)" to the title (image_soon flag) and stamps
the grader-aware title + cert (hidden from the public feed). The 151 Zapdos cert
stays marked CLAIMED.

Resume-safe: skips any cert already live on Square. Run _delete_all_graded.py
first for a clean rebuild.

Env: SK_ADMIN_TOKEN (auto-read on Windows). DRY_RUN=1 to print only.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from _relist_from_csv_ebay import build_record, CLAIMED_CERTS
from _price_and_list_new import live_square_certs
from _multisource_reprice import WORKER_BASE, get_token

CSV_PATH = Path(os.environ.get("RELIST_CSV",
                r"C:\Users\lunar\Downloads\Collection - Card Ladder (47).csv"))
UPLOAD_URL = f"{WORKER_BASE}/admin/upload-graded"


def upload(rec: dict, token: str) -> dict:
    card = {
        "cert_number": rec["cert"], "card_number": rec["number"],
        "name": rec["name"], "set_name": rec["set"], "year": rec["year"],
        "grader": rec["grader"], "grade": rec["grade"],
    }
    if rec["cert"] in CLAIMED_CERTS:
        card["listing_note"] = "CLAIMED — sale pending"
    payload = {"card": card, "price_cents": rec["price_cents"], "image_soon": True}
    req = urllib.request.Request(
        UPLOAD_URL, method="POST", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token,
                 "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:
        return {"error": str(e)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    dry = os.environ.get("DRY_RUN") == "1"

    rows = []
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("Graded Cert #") or "").strip():
                rows.append(row)
    recs = [build_record(r) for r in rows]

    token = get_token()
    if not token:
        print("[imageless] No SK_ADMIN_TOKEN — cannot upload."); return
    live = live_square_certs()
    todo = [r for r in recs if r["cert"] not in live]
    print(f"[imageless] CSV {len(recs)} | already live {len(recs)-len(todo)} | "
          f"to list {len(todo)}  DRY_RUN={dry}")

    ok = fail = 0
    for i, r in enumerate(todo, 1):
        title = (f"{r['grader']} {r['grade']} {r['year']} {r['set']} "
                 f"{r['name']} #{r['number']} (image soon)")
        claim = " [CLAIMED]" if r["cert"] in CLAIMED_CERTS else ""
        if dry:
            print(f"[imageless] {i:>2}/{len(todo)} DRY  {r['cert']}  {title[:70]}{claim}")
            continue
        res = upload(r, token)
        if res.get("ok"):
            ok += 1
            print(f"[imageless] {i:>2}/{len(todo)} OK  {r['cert']}  {res.get('item_id','')}  {title[:55]}{claim}")
        else:
            fail += 1
            print(f"[imageless] {i:>2}/{len(todo)} ERR {r['cert']}  {res}")
        time.sleep(0.35)
    print(f"\n[imageless] done — {ok} listed, {fail} failed.")


if __name__ == "__main__":
    main()
