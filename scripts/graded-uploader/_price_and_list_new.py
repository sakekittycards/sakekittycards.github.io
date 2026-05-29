"""Price + list graded cards that are in the Card Ladder collection but not yet
on the site. Uses the LOGO as a placeholder image and stamps "Photo coming soon
— new item" into the Square description (worker `card.listing_note`).

Pricing reuses the proven multi-source max logic from _multisource_reprice:
  base = max(Card Ladder CV, PriceCharting, fresh eBay best-recent-avg)
  sticker = snap_clean(markup(base))
Fresh eBay scrape every run (force_fresh) — same "brand new comps" rule as the
reprice. eBay comps pass the strict title filter + clean-comp guards (Best Offer
dropped, per-cert VARIANT_EXCLUDE). If eBay diverges wildly from CL/PC (likely
wrong-variant pollution, e.g. a too-generic card number), eBay is dropped and the
price falls back to max(CL, PC) so a new listing never goes live mispriced.

Unlike the reprice, CL is ALWAYS a valid base here (a new listing must get a
price — we can't "hold at current" when there is no current).

DRY_RUN=1  -> price + print the table, upload NOTHING.
(default)   -> price, then create each listing on Square and append it to
              pricing.csv marked [uploaded].
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from _ebay_chrome import fetch_or_cache as ebay_fetch
from _apply_max_price_formula import fuzzy_resolve_pid
from _multisource_reprice import (
    CL_CSV, PRICING_CSV, PC_GRADED, ALL_CARDS, WORKER_BASE,
    PC_COL, VARIANT_EXCLUDE,
    build_ebay_keyword_from_cl, normalize_grade, _clean_subject, _clean_set,
    _short_number, best_recent_avg, title_passes, markup, snap_clean,
    get_token, ebay_sold_url,
)

HERE = Path(__file__).resolve().parent
UPLOAD_URL = f"{WORKER_BASE}/admin/upload-graded"
PLACEHOLDER = HERE / "_placeholder-logo.jpg"
LISTING_NOTE = "Photo coming soon — new item"
# If eBay's recent avg is more than this multiple of the best of CL/PC, treat it
# as wrong-variant/wrong-card pollution and drop it (same spirit as the reprice
# 2x sanity cap, applied at list time so a new card never goes live mispriced).
EBAY_DIVERGENCE = 2.0


# ── display-name cleanup (CL identity -> customer-facing title pieces) ──────
_ERA_PREFIX = re.compile(
    r"^\s*(?:Sword\s*(?:&|and)\s*Shield|Sun\s*&\s*Moon|Scarlet\s*&\s*Violet|"
    r"X\s*&\s*Y|XY|Sm|Sw\s*Sh)\s+", re.I)


def clean_set_for_title(raw: str) -> str:
    """CL Set -> a clean, customer-facing set name, matching the existing
    catalog's convention (era prefix stripped, '(Japanese)' suffix kept)."""
    s = raw or ""
    is_jp = bool(re.search(r"\bJapanese\b", s, re.I))
    # _clean_set already drops the leading 'Pokemon ' and CL's "<code> En-" tags.
    s = _clean_set(s)
    s = re.sub(r"\bJapanese\b", "", s, flags=re.I)
    # Drop a leftover generic "<code> En-/Jp-/Sc-" the known-prefix list missed.
    s = re.sub(r"^\s*[A-Za-z0-9]+\s+(?:En|Jp|Sc)\s*-\s*", "", s)
    # Strip a leading bare set-code that no real set name starts with:
    #   "Sv5a-Crimson Haze" -> "Crimson Haze";  "Sv Black Star Promo" -> "Black Star Promo"
    s = re.sub(r"^\s*Sv\d+[a-z]*\s*-\s*", "", s, flags=re.I)
    s = re.sub(r"^\s*Sv\s+(?=[A-Z])", "", s)
    prev = None
    while prev != s:                      # strip a stacked era prefix once
        prev = s
        s = _ERA_PREFIX.sub("", s)
    s = " ".join(s.split())
    if is_jp and "(Japanese)" not in s:
        s = f"{s} (Japanese)".strip()
    return s or raw


def clean_name_for_title(raw: str) -> str:
    return " ".join(_clean_subject(raw).split())


def load_placeholder_b64() -> tuple[str, str]:
    import base64
    return base64.b64encode(PLACEHOLDER.read_bytes()).decode("ascii"), PLACEHOLDER.name


def live_square_certs() -> set[str]:
    """Every cert currently live on Square (paginated). Source of truth for
    'already listed' — prevents re-listing a card pricing.csv doesn't know about."""
    import urllib.parse
    cert_re = re.compile(r"Cert\s*#?:?\s*([A-Za-z0-9]+)", re.I)
    token = get_token()
    if not token:
        print("[list] WARNING: no token — cannot check live Square certs; "
              "relying on pricing.csv only (dup risk).")
        return set()
    out: set[str] = set()
    cursor = ""
    for _ in range(50):
        u = f"{WORKER_BASE}/admin/inspect?types=ITEM" + (
            f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        req = urllib.request.Request(u, headers={
            "X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        for o in d.get("objects", []):
            if o.get("type") != "ITEM":
                continue
            m = cert_re.search(o.get("item_data", {}).get("description", "") or "")
            if m:
                out.add(m.group(1))
        cursor = d.get("cursor") or ""
        if not cursor:
            break
    return out


def upload_one(card: dict, price_cents: int, img_b64: str, img_name: str,
               token: str) -> dict:
    payload = {
        "card": {
            "cert_number": card["cert"], "card_number": card["number"],
            "name": card["name"], "set_name": card["set"], "year": card["year"],
            "grade": card["grade"], "listing_note": LISTING_NOTE,
        },
        "price_cents": price_cents,
        "image_base64": img_b64, "image_filename": img_name,
    }
    req = urllib.request.Request(
        UPLOAD_URL, method="POST", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Sake-Admin-Token": token,
                 "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:
        return {"error": str(e)}


def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    dry = os.environ.get("DRY_RUN") == "1"

    cl_map: dict[str, dict] = {}
    with CL_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            c = (row.get("Graded Cert #") or "").strip()
            if c: cl_map[c] = row

    with PRICING_CSV.open("r", encoding="utf-8", newline="") as f:
        pricing_rows = list(csv.DictReader(f))
        pricing_fields = list(pricing_rows[0].keys())
    listed = {(r.get("cert") or "").strip() for r in pricing_rows}

    # CRITICAL: also exclude certs ALREADY LIVE on Square. pricing.csv can lag
    # the live catalog (some certs were listed via other flows and never tracked
    # locally) — keying "to list" off pricing.csv alone re-lists those as
    # DUPLICATES (happened 2026-05-29: 3 dupes created — Boa Hancock et al.).
    # The live catalog is the source of truth for "already listed".
    listed |= live_square_certs()

    pc_index = json.loads(PC_GRADED.read_text(encoding="utf-8"))
    fallback = json.loads(ALL_CARDS.read_text(encoding="utf-8"))

    to_list = [c for c in cl_map if c not in listed]
    print(f"[list] CL {len(cl_map)} | already in pricing.csv {len(listed)} | "
          f"to list {len(to_list)}  (DRY_RUN={dry})")

    # Build records + eBay keywords
    recs: list[dict] = []
    cert_to_kw: dict[str, str] = {}
    for cert in to_list:
        clr = cl_map[cert]
        grade = normalize_grade(clr.get("Condition") or "")
        try: cl_cv = float((clr.get("Current Value") or "0").replace(",", ""))
        except ValueError: cl_cv = 0.0
        pid = fuzzy_resolve_pid(_clean_subject(clr.get("Subject") or ""),
                                _clean_set(clr.get("Set") or ""),
                                _short_number(clr.get("Number") or ""), fallback)
        pc_val = None
        if pid and str(pid) in pc_index:
            col = PC_COL.get(grade)
            vals = pc_index[str(pid)]
            if col is not None and col < len(vals):
                v = vals[col]
                if isinstance(v, (int, float)) and v > 0: pc_val = float(v)
        kw = build_ebay_keyword_from_cl(clr, grade)
        cert_to_kw[cert] = kw
        recs.append({
            "cert": cert, "clr": clr, "grade": grade, "cl_cv": cl_cv,
            "pc_val": pc_val, "kw": kw,
            "name": clean_name_for_title(clr.get("Subject") or ""),
            "set":  clean_set_for_title(clr.get("Set") or ""),
            "number": _short_number(clr.get("Number") or ""),
            "year": (clr.get("Year") or "").strip(),
        })

    # Fresh scrape by default; USE_CACHE=1 reuses the just-scraped comps for a
    # same-session re-run (e.g. flipping dry-run -> live minutes later).
    fresh = os.environ.get("USE_CACHE") != "1"
    print(f"[list] eBay comps for {len(cert_to_kw)} cards "
          f"({'FRESH scrape' if fresh else 'cache OK'}) ...")
    ebay_by_cert = ebay_fetch(cert_to_kw, force_fresh=fresh) if cert_to_kw else {}

    # Price each
    for r in recs:
        items = ebay_by_cert.get(r["cert"], [])
        excl = VARIANT_EXCLUDE.get(r["cert"], ())
        priced: list[tuple[float, str]] = []
        for it in items:
            t = it.get("title", "")
            if not title_passes(t, r["clr"].get("Subject", ""), r["number"], r["grade"]):
                continue
            if it.get("bestOffer"): continue
            if excl and any(x in t.upper() for x in excl): continue
            try: p = float(it.get("totalPrice") or 0)
            except (TypeError, ValueError): continue
            if 1 < p < 100000: priced.append((p, it.get("endedAt", "")))
        ebay_avg = best_recent_avg(priced) if len(priced) >= 3 else None
        r["ebay_avg"] = ebay_avg
        r["ebay_count"] = len(priced)

        # Drop eBay if it diverges wildly from CL/PC (wrong-variant pollution).
        anchor = max([v for v in (r["cl_cv"], r["pc_val"]) if v] or [0])
        dropped = False
        if ebay_avg and anchor and ebay_avg > EBAY_DIVERGENCE * anchor:
            dropped = True
            ebay_avg = None
        r["ebay_dropped"] = dropped

        sources = []
        if r["cl_cv"]: sources.append(("CL", r["cl_cv"]))
        if r["pc_val"]: sources.append(("PC", r["pc_val"]))
        if ebay_avg: sources.append(("EBAY", ebay_avg))
        if sources:
            r["winner"], r["base"] = max(sources, key=lambda x: x[1])
            r["price"] = snap_clean(markup(r["base"]))
        else:
            r["winner"], r["base"], r["price"] = "NONE", 0.0, 0

    # Report table
    print(f"\n{'cert':<12}{'grade':<7}{'CL':>7}{'PC':>7}{'eBay':>8}{'n':>4}  "
          f"{'win':<5}{'$':>6}  set / name")
    for r in sorted(recs, key=lambda x: -x["price"]):
        flag = " [eBay dropped]" if r.get("ebay_dropped") else ""
        print(f"{r['cert']:<12}{r['grade']:<7}{r['cl_cv']:>7.0f}"
              f"{(r['pc_val'] or 0):>7.0f}{(r['ebay_avg'] or 0):>8.0f}{r['ebay_count']:>4}  "
              f"{r['winner']:<5}{r['price']:>6}  {r['set']} | {r['name']} #{r['number']}{flag}")

    bad = [r for r in recs if r["price"] <= 0]
    if bad:
        print(f"\n[list] WARNING: {len(bad)} card(s) priced $0 — will be skipped: "
              f"{[r['cert'] for r in bad]}")

    if dry:
        print("\n[list] DRY_RUN=1 — nothing uploaded.")
        return

    token = get_token()
    if not token:
        print("[list] No SK_ADMIN_TOKEN — cannot upload."); return
    img_b64, img_name = load_placeholder_b64()

    ok = fail = 0
    for r in recs:
        if r["price"] <= 0:
            print(f"  SKIP cert {r['cert']} (no price)"); continue
        res = upload_one(r, int(round(r["price"] * 100)), img_b64, img_name, token)
        if res.get("ok"):
            ok += 1
            print(f"  OK  cert {r['cert']}  ${r['price']}  {res.get('item_id','')}")
            pricing_rows.append({
                **{k: "" for k in pricing_fields},
                "cert": r["cert"], "year": r["year"], "set": r["set"],
                "name": r["name"], "number": r["number"], "grade": r["grade"],
                "your_price": f"[uploaded]{r['price']}",
                "condition_note": LISTING_NOTE,
                "front_image": str(PLACEHOLDER),
            })
        else:
            fail += 1
            print(f"  ERR cert {r['cert']}  {res}")
        time.sleep(0.4)

    with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pricing_fields)
        w.writeheader(); w.writerows(pricing_rows)
    print(f"\n[list] done. {ok} listed, {fail} failed. pricing.csv updated.")


if __name__ == "__main__":
    main()
