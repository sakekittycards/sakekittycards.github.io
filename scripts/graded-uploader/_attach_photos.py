"""Rebuild the graded catalog from CSV 48 with Nick's own front/back photos.

Per card: crop + deskew the slab (rembg) and BLUR the cert number, then create
the Square listing with front (primary) + back image and a CLEAN title (no
"(image soon)"). Cards with no photo stay imageless with the "(image soon)" tag.
Identical cards (e.g. the 8 Chinese Cubones) share photos — a cert with no photo
of its own borrows a same-card sibling's.

Reads _photo_map.json (from _match_photos.py). Processed images are cached under
_processed_photos/ so re-runs are fast. DRY_RUN=1 to process + report only.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from _photo_crop import crop_deskew
from _relist_from_csv_ebay import build_record, CLAIMED_CERTS, censor_cert
from _price_and_list_new import live_square_certs
from _multisource_reprice import WORKER_BASE, get_token

HERE = Path(__file__).resolve().parent
CSV_PATH = Path(os.environ.get("RELIST_CSV",
                r"C:\Users\lunar\Downloads\Collection - Card Ladder (48).csv"))
# Nick renames each photo "<cert>F" / "<cert>B" (front/back). Map straight from
# filenames — 100% reliable, no OCR. Point PHOTO_DIR at the renamed folder.
PHOTO_DIR = Path(os.environ.get("PHOTO_DIR",
                 r"D:\Dropbox\Camera Uploads\Grade Photos 6.10.26"))
PROC_DIR = HERE / "_processed_photos"


def build_photo_map(folder: Path) -> dict:
    """Scan <cert>F / <cert>B named photos into {cert: {front, back}}."""
    import glob
    import re
    m = {}
    pat = re.compile(r"^\D*?(\d{6,})\D*?([FB])\D*\.(jpe?g|png)$", re.I)
    files = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
        files += glob.glob(str(folder / ext))
    for f in files:
        mm = pat.match(os.path.basename(f))
        if not mm:
            continue
        cert, side = mm.group(1), mm.group(2).upper()
        m.setdefault(cert, {"front": None, "back": None})
        m[cert]["front" if side == "F" else "back"] = f
    return m
UPLOAD_URL = f"{WORKER_BASE}/admin/upload-graded"
DELETE_URL = f"{WORKER_BASE}/admin/delete-item"


def process_photo(src: str, dst: Path) -> bytes:
    """Crop+deskew the slab and blur the cert; cache to dst. Returns JPEG bytes."""
    if dst.exists():
        return dst.read_bytes()
    crop = crop_deskew(src)
    img, _n = censor_cert(crop)          # blur the cert digit-run(s)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    data = out.getvalue()
    dst.write_bytes(data)
    return data


def upload(rec, front_b64, back_b64, token):
    card = {
        "cert_number": rec["cert"], "card_number": rec["number"],
        "name": rec["name"], "set_name": rec["set"], "year": rec["year"],
        "grader": rec["grader"], "grade": rec["grade"],
    }
    if rec["cert"] in CLAIMED_CERTS:
        card["listing_note"] = "CLAIMED — sale pending"
    payload = {"card": card, "price_cents": rec["price_cents"]}
    if front_b64:
        payload["image_base64"] = front_b64
        payload["image_filename"] = f"graded-{rec['cert']}-front.jpg"
        if back_b64:
            payload["back_image_base64"] = back_b64
            payload["back_image_filename"] = f"graded-{rec['cert']}-back.jpg"
    else:
        payload["image_soon"] = True
    req = urllib.request.Request(
        UPLOAD_URL, method="POST", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token,
                 "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:
        return {"error": str(e)}


def delete_all_graded(token):
    import urllib.parse
    cert_re = None
    out = []
    cursor = ""
    for _ in range(50):
        u = f"{WORKER_BASE}/admin/inspect?types=ITEM" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        req = urllib.request.Request(u, headers={"X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        for o in d.get("objects", []):
            if o.get("type") != "ITEM":
                continue
            data = o.get("item_data") or {}
            name = (data.get("name") or "").lower()
            desc = (data.get("description") or "").lower()
            if "cert #" in desc or any(k in name for k in (" psa ", " cgc ", " bgs ", " sgc ")) \
               or name.startswith(("psa ", "cgc ", "bgs ", "sgc ")):
                out.append(o["id"])
        cursor = d.get("cursor") or ""
        if not cursor:
            break
    for iid in out:
        body = json.dumps({"item_id": iid}).encode()
        req = urllib.request.Request(DELETE_URL, method="POST", data=body,
            headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0"})
        try:
            urllib.request.urlopen(req, timeout=30)
        except Exception:
            pass
        time.sleep(0.25)
    return len(out)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    dry = os.environ.get("DRY_RUN") == "1"
    PROC_DIR.mkdir(exist_ok=True)

    rows = [r for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig"))
            if (r.get("Graded Cert #") or "").strip()]
    recs = [build_record(r) for r in rows]
    pmap = build_photo_map(PHOTO_DIR)
    print(f"[attach] photo map from filenames in {PHOTO_DIR}: {len(pmap)} certs")

    # Identical-card fallback: key by (subject,set,number,grade) so a cert with
    # no photo of its own (e.g. an 8th identical Cubone) borrows a sibling's.
    def ident(r):
        return (r["name"].lower(), r["set"].lower(), r["number"].lower(), r["grade"].lower())
    ident_to_photos = {}
    for r in recs:
        if r["cert"] in pmap and pmap[r["cert"]]["front"]:
            ident_to_photos.setdefault(ident(r), pmap[r["cert"]])

    token = None
    if not dry:
        token = get_token()
        if not token:
            print("[attach] No SK_ADMIN_TOKEN."); return

    # Process all needed photos first (crop+deskew+blur, cached).
    print(f"[attach] processing photos for {len(recs)} cards ...")
    prepared = {}   # cert -> (front_bytes|None, back_bytes|None, source)
    for r in recs:
        cert = r["cert"]
        pm = pmap.get(cert)
        if not (pm and pm.get("front")):
            pm = ident_to_photos.get(ident(r))      # borrow sibling's photos
            src = "sibling" if pm else "none"
        else:
            src = "own"
        if not pm:
            prepared[cert] = (None, None, "none")
            continue
        fb = process_photo(pm["front"], PROC_DIR / f"{cert}-front.jpg") if pm.get("front") else None
        bb = process_photo(pm["back"], PROC_DIR / f"{cert}-back.jpg") if pm.get("back") else None
        prepared[cert] = (fb, bb, src)
        print(f"  {cert}  front={'Y' if fb else '-'} back={'Y' if bb else '-'} ({src})")

    withphoto = sum(1 for v in prepared.values() if v[0])
    withback = sum(1 for v in prepared.values() if v[1])
    nophoto = [c for c, v in prepared.items() if not v[0]]
    print(f"\n[attach] front photo: {withphoto}/{len(recs)} | back photo: {withback} | "
          f"imageless: {len(nophoto)} {nophoto}")

    if dry:
        print("[attach] DRY_RUN — nothing uploaded."); return

    print("[attach] deleting existing graded listings ...")
    print(f"[attach] deleted {delete_all_graded(token)}")

    ok = fail = 0
    for i, r in enumerate(recs, 1):
        fb, bb, _src = prepared[r["cert"]]
        f64 = base64.b64encode(fb).decode() if fb else None
        b64 = base64.b64encode(bb).decode() if bb else None
        res = upload(r, f64, b64, token)
        tag = "IMG" if f64 else "soon"
        if res.get("ok"):
            ok += 1
            print(f"[attach] {i:>2}/{len(recs)} OK[{tag}] {r['cert']} {res.get('item_id','')} {r['name'][:30]}")
        else:
            fail += 1
            print(f"[attach] {i:>2}/{len(recs)} ERR {r['cert']} {res}")
        time.sleep(0.35)
    print(f"\n[attach] done — {ok} listed, {fail} failed.")


if __name__ == "__main__":
    main()
