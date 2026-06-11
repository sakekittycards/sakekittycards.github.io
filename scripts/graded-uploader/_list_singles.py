"""List owned raw singles worth > $100 (from a TCGplayer MyPricing export) on the
website as raw-single Square listings, with the EXACT card image pulled from
pokemontcg.io (which covers even the newest 2026 sets and whose image URLs the
worker can fetch server-side — TCGplayer's CDN is bot-walled).

Singles show Make Offer (price hidden) per site policy, but we still set a price
= market x1.20 (raw-card policy) as the internal value.

Env: SK_ADMIN_TOKEN. DRY_RUN=1 = resolve images + print table, upload nothing.
THRESHOLD env overrides the $100 floor.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from _multisource_reprice import WORKER_BASE, get_token

CSV_PATH = Path(os.environ.get("SINGLES_CSV",
                r"C:\Users\lunar\Downloads\TCGplayer__MyPricing_20260610_062151.csv"))
UPLOAD_URL = f"{WORKER_BASE}/admin/upload-single"
PKMN_API = "https://api.pokemontcg.io/v2/cards"
THRESHOLD = float(os.environ.get("THRESHOLD", "100"))
LIMIT = int(os.environ.get("LIMIT", "0"))   # >0 = cap to the top-N most valuable
MARKUP = 1.20

# Verified stock-image overrides (by TCGplayer Id) for cards pokemontcg.io lacks
# — JP cards + Pokemon Together promos pulled from tcgsearch's public bucket
# (clean re-hosted TCGplayer product scans), and the 2026 N's Zekrom promo from
# pokemon.com's official card DB. Each was downloaded and visually confirmed to
# be the exact card + correct variant (clean scans, not marketplace photos).
IMAGE_OVERRIDE = {
    "8219378": "https://kwuqqoyuksvlnbgzaaim.supabase.co/storage/v1/object/public/product-images/f3af607e-a0c1-445a-b702-5c567bc5b07a/c05e86fa-f411-4871-bbef-cadb602de806.webp",  # Latias ex 087/064 (JP)
    "8532141": "https://kwuqqoyuksvlnbgzaaim.supabase.co/storage/v1/object/public/product-images/33c1babf-1320-411e-8851-1f28139cce13/e9fd0daf-646e-407c-9542-b9c2993fc6bc.webp",  # Lillie's Clefairy ex 126/100 (JP)
    "8045543": "https://kwuqqoyuksvlnbgzaaim.supabase.co/storage/v1/object/public/product-images/f855b5d2-42f6-47cd-b7d3-79228ba731ac/38fb90f0-a1cc-4c73-ada7-e2e4a4cf5b34.webp",  # Eevee 133/165 (Pokemon Together)
    "8045548": "https://kwuqqoyuksvlnbgzaaim.supabase.co/storage/v1/object/public/product-images/f855b5d2-42f6-47cd-b7d3-79228ba731ac/d7921b6a-54ba-4866-a100-104f20886795.webp",  # Pikachu 025/165 (Pokemon Together)
    "9168435": "https://assets.pokemon.com/static-assets/content-assets/cms2/img/cards/web/MEP/MEP_EN_31.png",  # N's Zekrom 031 (Mega Evolution Promo)
}

# Temporary STOCK-PHOTO placeholders — NOT the actual card in inventory. Used
# only where no clean correct-variant scan exists (e.g. Shadowless Base Set,
# which databases only carry as Unlimited or 1st-Ed). The worker tags these
# "(stock image — not actual card)" on the listing so customers aren't misled;
# Nick replaces them with his own photos. Nick-approved per card.
STOCK_IMAGE = {
    "2998618": "https://i.ebayimg.com/images/g/YBYAAeSwVKVqE6Wn/s-l1600.webp",  # Base Set (Shadowless) Blastoise 002/102 — eBay listing photo
}

# Year fallback for the few cards pokemontcg.io can't resolve (newest promos +
# Japanese). Lets them list imageless but still bucket as Make-Offer singles.
YEAR_FALLBACK = {
    "7221034": "2024",  # SVP Pikachu #027 (Pokemon Center)
    "8045543": "2025",  # Eevee #133 (Pokemon Together)
    "8045548": "2025",  # Pikachu #025 (Pokemon Together)
    "8219378": "2025",  # Latias ex (JP SV7a Paradise Dragona)
    "8532141": "2025",  # Lillie's Clefairy ex (JP Battle Partners)
    "9168435": "2026",  # N's Zekrom (Mega Evolution Promo)
}

_COND = [("near mint", "NM"), ("lightly played", "LP"), ("moderately played", "MP"),
         ("heavily played", "HP"), ("damaged", "DMG")]


def num(x):
    try:
        return float((x or "0").replace(",", ""))
    except ValueError:
        return 0.0


def clean_cond(s: str) -> str:
    s = (s or "").lower()
    for k, v in _COND:
        if k in s:
            return v
    return "NM"


def is_reverse(s: str) -> bool:
    return "reverse" in (s or "").lower()


def variant_tag(set_name: str, condition: str) -> str | None:
    """Detect a print variant that pokemontcg.io can't represent. Its vintage
    images are the *Unlimited* print only — there's no 1st-Edition / Shadowless
    artwork — so showing one for those variants is the wrong card. Returns a
    short display tag ('1st Ed' / 'Shadowless') so the listing stays honest, and
    callers drop the stock image when this is set."""
    s = ((set_name or "") + " " + (condition or "")).lower()
    if "1st edition" in s:
        return "1st Ed"
    if "shadowless" in s:
        return "Shadowless"
    return None


def clean_name(product_name: str) -> str:
    """'Pikachu ex - 276/217' -> 'Pikachu ex'; 'Gengar (5)' -> 'Gengar';
    'Eevee - 133/165 (Pokemon Together)' -> 'Eevee'."""
    n = product_name.split(" - ")[0]
    n = re.sub(r"\s*\([^)]*\)\s*$", "", n).strip()      # trailing (pos)/(promo)
    return n


def short_number(number: str) -> str:
    if not number:
        return ""
    return number.split("/")[0].strip()


def clean_set(tcg_set: str) -> str:
    """Strip TCGplayer set-code prefixes for matching/display."""
    s = re.sub(r"^[A-Za-z]+\d*:\s*", "", tcg_set or "")   # "ME02: ", "SV08: ", "SWSH07: "
    s = re.sub(r"\s*\(Shadowless\)|\s*\(.*?\)$", "", s).strip()
    return s


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# TCGplayer (cleaned) set name -> pokemontcg.io set name, for the ones that
# differ. Modern SV-era sets match directly and aren't listed.
SET_MAP = {
    "base set": ["Base"], "base": ["Base"],
    "base set 2": ["Base Set 2"],
    "expedition": ["Expedition Base Set"],
    "scarlet & violet 151": ["151"], "151": ["151"],
    "xy - evolutions": ["Evolutions"], "xy evolutions": ["Evolutions"],
    "scarlet & violet promo": ["Scarlet & Violet Black Star Promos", "Scarlet & Violet Promos"],
    "scarlet & violet promos": ["Scarlet & Violet Black Star Promos", "Scarlet & Violet Promos"],
    "scarlet & violet promo cards": ["Scarlet & Violet Black Star Promos", "Scarlet & Violet Promos"],
    "sm promos": ["SM Black Star Promos"],
    "sm - unbroken bonds": ["Unbroken Bonds"],
    "xy promos": ["XY Black Star Promos"],
    "wotc promo": ["Wizards Black Star Promos"],
    "nintendo promos": ["Nintendo Black Star Promos"],
    "radiant collection": ["Generations", "Legendary Treasures"],
}


def target_sets(tcg_set: str) -> list[str]:
    c = clean_set(tcg_set)
    return SET_MAP.get(c.lower(), [c])


def name_variants(name: str) -> list[str]:
    """pokemontcg.io hyphenates suffixes: 'Magikarp & Wailord GX' -> '...-GX'."""
    out = [name]
    m = re.search(r"\s+(GX|EX|V|VMAX|VSTAR)$", name, re.I)
    if m:
        out.append(re.sub(r"\s+(GX|EX|V|VMAX|VSTAR)$", lambda x: "-" + x.group(1), name, flags=re.I))
    return out


def resolve(name: str, number: str, tcg_set: str) -> dict | None:
    """pokemontcg.io exact card: query by name (+number), pick the result whose
    set best matches the TCGplayer set. Returns {image, year, set} or None."""
    wants = {_norm(t) for t in target_sets(tcg_set)}

    def fetch(qname, qnum):
        q = f'name:"{qname}"' + (f" number:{qnum}" if qnum else "")
        url = f"{PKMN_API}?q={urllib.parse.quote(q)}&pageSize=50"
        try:
            d = json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=25).read())
            return d.get("data", [])
        except Exception:
            return []

    # Number variants (vintage drops leading zeros "002"->"2"; promos may carry
    # a set prefix like "SM166" already in the number).
    numvars = [""]
    if number:
        numvars = []
        for v in (number.lstrip("0") or number, number):
            if v not in numvars:
                numvars.append(v)
    for qname in name_variants(name):
        for v in numvars:
            cards = fetch(qname, v)
            # Accept ONLY an exact set correspondence — a wrong-set image is
            # worse than none (guards JP/promo/Base-Set-2 mismatches).
            exact = [c for c in cards if _norm(c["set"]["name"]) in wants]
            if exact:
                best = exact[0]
                img = best.get("images", {}).get("large") or best.get("images", {}).get("small")
                return {"image": img, "year": (best["set"].get("releaseDate", "") or "")[:4],
                        "set": best["set"]["name"]}
    return None


def fetch_image_b64(url: str) -> str | None:
    """Fetch the card image (scrydex/pokemontcg.io CDN needs a browser UA) and
    return base64 — the worker bot-block-proofs by taking bytes, not a URL."""
    import base64
    if not url:
        return None
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"}),
            timeout=30)
        b = r.read()
        if b and len(b) > 2000:
            # Square accepts JPEG/PNG/GIF, not WebP — normalize the tcgsearch
            # bucket's .webp scans to PNG before base64.
            if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
                import io
                from PIL import Image
                buf = io.BytesIO()
                Image.open(io.BytesIO(b)).convert("RGB").save(buf, "PNG")
                b = buf.getvalue()
            return base64.b64encode(b).decode("ascii")
    except Exception:
        return None
    return None


def delete_all_singles(token: str) -> int:
    """Delete every existing raw-single listing (description has 'Card ID:').
    Graded use 'Cert #', sealed/merch have neither — so they're untouched."""
    import urllib.parse
    base = WORKER_BASE
    ids = []
    cursor = ""
    for _ in range(60):
        u = f"{base}/admin/inspect?types=ITEM" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        req = urllib.request.Request(u, headers={"X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read())
        for o in d.get("objects", []):
            if o.get("type") != "ITEM":
                continue
            desc = (o.get("item_data") or {}).get("description", "") or ""
            if re.search(r"Card ID:", desc, re.I):
                ids.append(o["id"])
        cursor = d.get("cursor") or ""
        if not cursor:
            break
    for iid in ids:
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{base}/admin/delete-item", method="POST",
                data=json.dumps({"item_id": iid}).encode(),
                headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0"}),
                timeout=30)
        except Exception:
            pass
        time.sleep(0.25)
    return len(ids)


def upload(card: dict, token: str) -> dict:
    req = urllib.request.Request(
        UPLOAD_URL, method="POST", data=json.dumps(card).encode(),
        headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token,
                 "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:
        return {"error": str(e)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    dry = os.environ.get("DRY_RUN") == "1"

    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    over = [r for r in rows if num(r["Total Quantity"]) > 0 and num(r["TCG Market Price"]) > THRESHOLD]
    over.sort(key=lambda r: -num(r["TCG Market Price"]))
    if LIMIT > 0:
        over = over[:LIMIT]
    label = f"top {len(over)}" if LIMIT > 0 else f"{len(over)} owned cards over ${THRESHOLD:.0f}"
    print(f"[singles] {label}  DRY_RUN={dry}")

    recs = []
    for r in over:
        name = clean_name(r["Product Name"])
        number = short_number(r["Number"])
        setn = clean_set(r["Set Name"])
        cond = clean_cond(r["Condition"])
        rev = is_reverse(r["Condition"])
        mkt = num(r["TCG Market Price"])
        vtag = variant_tag(r["Set Name"], r["Condition"])
        res = resolve(name, number, r["Set Name"])
        # pokemontcg.io only carries the Unlimited print — never show its image
        # for a 1st-Edition / Shadowless listing (wrong variant). Better imageless.
        image = (res["image"] if res else None)
        if image and vtag:
            image = None
        if r["TCGplayer Id"] in IMAGE_OVERRIDE:   # verified correct-variant scan
            image = IMAGE_OVERRIDE[r["TCGplayer Id"]]
        stock = r["TCGplayer Id"] in STOCK_IMAGE
        if stock:                                  # approved placeholder (not the real card)
            image = STOCK_IMAGE[r["TCGplayer Id"]]
        recs.append({
            "card_id": r["TCGplayer Id"], "name": name, "number": number,
            "set_name": setn, "cond": cond, "rev": rev, "vtag": vtag, "stock": stock, "market": mkt,
            "price_cents": int(round(mkt * MARKUP * 100)),
            "image": image,
            "year": (res["year"] if res and res.get("year") else YEAR_FALLBACK.get(r["TCGplayer Id"], "")),
            "matched_set": res["set"] if res else None,
        })
        time.sleep(0.15)   # be polite to pokemontcg.io

    noimg = [x for x in recs if not x["image"]]
    noyear = [x for x in recs if not x["year"]]
    print(f"\n{'$mkt':>8} {'cond':<4} {'img':<3} {'yr':<5} set / name #num  -> matched set")
    for x in recs:
        flag = "Y" if x["image"] else "—"
        print(f"{x['market']:>8.0f} {x['cond']:<4} {flag:<3} {x['year']:<5} "
              f"{x['set_name'][:20]:20} {x['name'][:24]:24} #{x['number']:<8} -> {x['matched_set']}")
    print(f"\n[singles] no image: {len(noimg)} {[x['card_id'] for x in noimg]}")
    print(f"[singles] no year (can't categorize as single): {len(noyear)} {[x['card_id'] for x in noyear]}")

    if dry:
        print("\n[singles] DRY_RUN — nothing uploaded.")
        return

    token = get_token()
    if not token:
        print("[singles] No SK_ADMIN_TOKEN."); return
    if os.environ.get("REBUILD") == "1":
        print("[singles] FULL REBUILD — deleting existing singles ...")
        print(f"[singles] deleted {delete_all_singles(token)} existing singles")
    ok = fail = skip = 0
    for i, x in enumerate(recs, 1):
        if not x["year"]:
            skip += 1
            print(f"[singles] {i:>2}/{len(recs)} SKIP (no year) {x['card_id']} {x['name']}")
            continue
        cond_disp = x["cond"] + (" RH" if x["rev"] else "") + (f" {x['vtag']}" if x.get("vtag") else "")
        payload = {
            "card_id": x["card_id"], "name": x["name"], "set_name": x["set_name"],
            "number": x["number"], "year": x["year"], "condition": cond_disp,
            "price_cents": x["price_cents"],
        }
        if x.get("stock"):
            payload["stock_image"] = True
        b64 = fetch_image_b64(x["image"]) if x["image"] else None
        if b64:
            payload["image_base64"] = b64
        res = upload(payload, token)
        if res.get("ok"):
            ok += 1
            img = "img" if res.get("image_id") else "NOIMG"
            print(f"[singles] {i:>2}/{len(recs)} OK[{img}] {x['card_id']} {res.get('item_id','')} {x['name'][:28]}")
        else:
            fail += 1
            print(f"[singles] {i:>2}/{len(recs)} ERR {x['card_id']} {res}")
        time.sleep(0.35)
    print(f"\n[singles] done — {ok} listed, {skip} skipped, {fail} failed.")


if __name__ == "__main__":
    main()
