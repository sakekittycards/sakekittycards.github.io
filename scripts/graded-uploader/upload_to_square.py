"""
Upload priced graded cards from pricing.csv to Square via the Worker.

Reads pricing.csv (written by process_inbox.py), filters to rows that
have a `your_price` set, and POSTs each to the Worker's
`/admin/upload-graded` endpoint. The Worker holds the Square access
token as a secret — this script only sees the admin token.

Usage:
    SK_ADMIN_TOKEN=<token> python upload_to_square.py
    SK_ADMIN_TOKEN=<token> python upload_to_square.py --csv pricing.csv --dry-run

After a successful upload, marks the row's `your_price` cell with a
preceding `[uploaded]` (e.g. `275.00` -> `[uploaded]275.00`) so re-running the script is
idempotent and only uploads new rows.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"
ENDPOINT = f"{WORKER_BASE}/admin/upload-graded"


def parse_price_to_cents(raw: str) -> int | None:
    """Accept '275', '275.00', '$275.00', '[uploaded]275.00' (skip already-uploaded)."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("[uploaded]"):
        return None
    s = s.lstrip("$").replace(",", "").strip()
    if not s:
        return None
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return None


def load_image_b64(path: Path) -> tuple[str, str]:
    if not path.exists():
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    return base64.b64encode(raw).decode("ascii"), path.name


def upload_card(row: dict, admin_token: str, dry_run: bool = False) -> dict:
    price_cents = parse_price_to_cents(row.get("your_price", ""))
    if price_cents is None:
        return {"skipped": True, "reason": "no your_price set or already uploaded"}

    front_path = Path(row["front_image"])
    img_b64, img_name = load_image_b64(front_path)

    back_b64 = ""
    back_name = ""
    back_raw = row.get("back_image", "").strip()
    if back_raw:
        back_path = Path(back_raw)
        if back_path.exists():
            back_b64, back_name = load_image_b64(back_path)

    payload = {
        "card": {
            "cert_number":      row.get("cert"),
            "card_number":      row.get("number"),
            "name":             row.get("name"),
            "set_name":         row.get("set"),
            "year":             row.get("year"),
            "grade":            row.get("grade"),
            "pokemontcg_set_id": row.get("pokemontcg_set_id"),
            "offer_min":        row.get("offer_min") or None,
            "condition_note":   row.get("condition_note") or "",
        },
        "price_cents":         price_cents,
        "image_base64":        img_b64,
        "image_filename":      img_name,
        "back_image_base64":   back_b64,
        "back_image_filename": back_name,
    }

    if dry_run:
        preview = {**payload, "image_base64": f"<{len(img_b64)} chars>"}
        return {"dry_run": True, "payload": preview}

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        method="POST", data=body,
        headers={
            "Content-Type":         "application/json",
            "X-Sake-Admin-Token":   admin_token,
            # Cloudflare's Browser Integrity Check blocks Python-urllib's
            # default UA with error 1010 — pretend to be a real browser.
            "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36",
            "Accept":               "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"http_error": e.code, "body": body}


def mark_uploaded(csv_path: Path, cert: str):
    """Prefix the matching row's your_price with [uploaded] so re-runs skip it."""
    if not csv_path.exists():
        return
    rows: list[dict] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for r in reader:
            if r.get("cert") == cert and not r.get("your_price", "").startswith("[uploaded]"):
                r["your_price"] = "[uploaded]" + r["your_price"]
            rows.append(r)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def sync_from_edit_csv(canonical_csv: Path, edit_csv: Path) -> int:
    """
    Pull prices/notes/offer_min from the sheet-friendly pricing-edit.csv
    into the canonical pricing.csv (matched on cert).

    Skips rows whose canonical your_price is already marked [uploaded] so
    we never re-upload an item just because it's still in the edit sheet.
    Returns the number of rows updated.
    """
    if not edit_csv.exists():
        return 0
    edits: dict[str, dict] = {}
    with edit_csv.open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            edits[r.get("cert", "")] = {
                "your_price":     r.get("your_price", "").strip(),
                "condition_note": r.get("condition_note", "").strip(),
                "offer_min":      r.get("offer_min", "").strip(),
            }

    rows: list[dict] = []
    fieldnames: list[str] = []
    updated = 0
    with canonical_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for r in reader:
            cert = r.get("cert", "")
            if cert in edits and not r.get("your_price", "").startswith("[uploaded]"):
                e = edits[cert]
                changed = False
                # `your_price` is the editable column. An empty value in the
                # edit sheet should NOT clobber a value already typed into
                # the canonical CSV — only overwrite when the sheet has
                # something or the canonical is blank.
                if e["your_price"] and e["your_price"] != r.get("your_price", ""):
                    r["your_price"] = e["your_price"]
                    changed = True
                if e["condition_note"] and e["condition_note"] != r.get("condition_note", ""):
                    r["condition_note"] = e["condition_note"]
                    changed = True
                if e["offer_min"] and e["offer_min"] != r.get("offer_min", ""):
                    r["offer_min"] = e["offer_min"]
                    changed = True
                if changed:
                    updated += 1
            rows.append(r)

    if updated:
        with canonical_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return updated


def main():
    here = Path(__file__).parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=here / "pricing.csv")
    ap.add_argument("--edit-csv", type=Path, default=here / "pricing-edit.csv",
                    help="Sheet-friendly CSV; prices typed here are synced into the canonical CSV before upload")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be uploaded without hitting the Worker")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}")
        sys.exit(1)

    synced = sync_from_edit_csv(args.csv, args.edit_csv)
    if synced:
        print(f"Synced {synced} row(s) from {args.edit_csv.name} into {args.csv.name}")

    admin_token = os.environ.get("SK_ADMIN_TOKEN", "")
    if not args.dry_run and not admin_token:
        print("Set SK_ADMIN_TOKEN env var (the same value as the Worker's ADMIN_TOKEN secret).")
        print("Or pass --dry-run to preview the payload without uploading.")
        sys.exit(1)

    rows = list(csv.DictReader(args.csv.open("r", encoding="utf-8", newline="")))
    pending = [r for r in rows if parse_price_to_cents(r.get("your_price", "")) is not None]

    if not pending:
        print(f"Nothing to upload. {len(rows)} rows in CSV, but none have a fresh your_price set.")
        print(f"Edit {args.csv} to fill in your_price (rows already uploaded are marked with [uploaded]).")
        return

    print(f"Uploading {len(pending)} card(s) to Square via {ENDPOINT}")
    if args.dry_run:
        print("(dry-run — no requests will be sent)")

    for i, row in enumerate(pending, 1):
        cert = row.get("cert", "?")
        name = row.get("name", "?")
        price = row.get("your_price", "?")
        print(f"[{i}/{len(pending)}] cert={cert}  {name}  ${price}")
        try:
            res = upload_card(row, admin_token, dry_run=args.dry_run)
        except Exception as e:
            print(f"   ERROR: {e}")
            continue

        if res.get("skipped"):
            print(f"   skipped: {res.get('reason')}")
            continue
        if res.get("dry_run"):
            print(f"   would post: title={res['payload']['card']['name']!r}  price_cents={res['payload']['price_cents']}")
            continue
        if res.get("ok"):
            print(f"   created Square item {res['item_id']}")
            print(f"   listing: {res['listing_url']}")
            mark_uploaded(args.csv, cert)
            mark_uploaded(args.edit_csv, cert)
        elif "http_error" in res:
            print(f"   HTTP {res['http_error']}: {res['body']}")
        else:
            print(f"   error from Worker: {res}")

        time.sleep(0.3)  # gentle throttle so Square doesn't rate-limit on big batches


if __name__ == "__main__":
    main()
