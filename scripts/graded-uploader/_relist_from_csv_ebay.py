"""Re-list the entire graded catalog from a Card Ladder CSV using eBay STOCK
images (cert censored), not Nick's own scans.

Per Nick (2026-06-09): wiped all graded listings, replacing with the cards in
`Collection - Card Ladder (44).csv`. No displayed price (the shop shows graded
as Make Offer only and hides the sticker), so we set the Square price to the CL
Current Value purely as an internal record — it never renders.

Pipeline per CSV row:
  1. Build a search query from the CL identity + grade.
  2. Scrape eBay (real Chrome via Playwright, behind the configured proxy — same
     launch pattern + proxy rule as _ebay_chrome) for a representative slab photo.
  3. OCR the image (RapidOCR) and black-box any cert-number run so the stock
     photo's cert (someone else's slab) isn't shown as if it were ours.
  4. Upload to Square via /admin/upload-graded with grader-aware metadata.

The image is a STOCK photo — it is not guaranteed to be the exact copy; the cert
is censored precisely because it belongs to another listing. Cards where no
image was found, or where no cert run was detected to censor, are FLAGGED at the
end for manual review (Nick chose "push live, fix flagged ones").

Env:
  SK_ADMIN_TOKEN   required to upload (User-scope on Windows; auto-read).
  DRY_RUN=1        scrape + censor + save images, upload NOTHING.
  LIMIT=N          only process the first N rows (testing).
  ONLY=cert1,cert2 only process these certs.
  EBAY_HEADLESS=1  run Chrome headless (default headful, most reliable).
  USE_CACHE=1      reuse images already saved under _relist_images/ (skip scrape).
Proxy is REQUIRED (same rule as _ebay_chrome) unless ALLOW_NO_PROXY=1.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from _ebay_chrome import PROFILE_DIR, UA, _proxy_config, _warmup, PROXY_FILE
from _price_and_list_new import clean_set_for_title, clean_name_for_title, live_square_certs
from _multisource_reprice import _short_number, normalize_grade, get_token, WORKER_BASE

HERE = Path(__file__).resolve().parent
CSV_PATH = Path(os.environ.get("RELIST_CSV",
                r"C:\Users\lunar\Downloads\Collection - Card Ladder (44).csv"))
IMG_DIR = HERE / "_relist_images"          # censored, upload-ready JPEGs
RAW_DIR = HERE / "_relist_images_raw"       # original eBay grab (for audit)
PROGRESS = HERE / "_relist_progress.json"   # {cert: {status, title, ...}}
UPLOAD_URL = f"{WORKER_BASE}/admin/upload-graded"
# Logo placeholder for cards with no clean white-bg scan available (the same
# "photo coming soon" image _price_and_list_new uses).
PLACEHOLDER = HERE / "_placeholder-logo.jpg"
try:
    PLACEHOLDER_BYTES = PLACEHOLDER.read_bytes()
except Exception:
    PLACEHOLDER_BYTES = b""

NAV_DELAY_SEC = 2.5
PAGE_TIMEOUT_MS = 45_000

_OCR = None
def ocr():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


# ── identity / grade ────────────────────────────────────────────────────────
def split_grader_grade(condition: str) -> tuple[str, str]:
    """'CGC 10  Pristine' -> ('CGC','10 Pristine'); 'PSA 10' -> ('PSA','10')."""
    c = normalize_grade(condition or "")
    m = re.match(r"^(PSA|BGS|CGC|SGC|HGA|AGS|TAG|GMA|ISA|CSG)\s+(.*)$", c, re.I)
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return "PSA", c.strip()


def grade_number(grade: str) -> str:
    m = re.search(r"\d+(?:\.\d)?", grade or "")
    return m.group(0) if m else ""


# Variant tokens that change a card into a different-VALUE card. The chosen
# photo's slab must agree with our card on each of these (both have it, or
# neither does) — otherwise we'd show e.g. a 1st-Edition slab for an Unlimited
# card. Watched in both directions.
VARIANT_GUARDS = [
    ("1st edition", ("1st edition", "1st ed.", "1st ed ", "first edition", "1st-edition")),
    ("shadowless",  ("shadowless",)),
    ("reverse",     ("reverse holo", "reverse foil", "reverse-holo", "rev holo")),
]


def build_record(row: dict) -> dict:
    cert = (row.get("Graded Cert #") or "").strip()
    grader, grade = split_grader_grade(row.get("Condition") or "")
    name = clean_name_for_title(row.get("Subject") or "")
    setn = clean_set_for_title(row.get("Set") or "")
    variation = (row.get("Variation") or "").strip()
    num = _short_number(row.get("Number") or "")
    year = (row.get("Year") or "").strip()
    try:
        cv = float((row.get("Current Value") or "0").replace(",", ""))
    except ValueError:
        cv = 0.0
    # Lowercased identity for variant detection — include the raw CL Card string
    # (it spells out "1st Edition", "Reverse Foil", etc.).
    identity = " ".join([row.get("Card") or "", name, setn, variation]).lower()
    # Number tokens to look for in a listing title (handle "040" vs "40").
    num_tokens = set()
    if num:
        num_tokens.add(num.upper())
        num_tokens.add(num.upper().lstrip("0") or num.upper())
    return {
        "cert": cert, "grader": grader, "grade": grade,
        "grade_num": grade_number(grade),
        "name": name, "set": setn, "number": num, "variation": variation,
        "year": year, "identity": identity, "num_tokens": num_tokens,
        "price_cents": max(100, int(round(cv * 100))),
        "cv": cv,
    }


def search_query(rec: dict) -> str:
    bits = [rec["year"], rec["name"], rec["set"]]
    if rec["number"]:
        bits.append("#" + rec["number"])
    # Variant keywords steer eBay to the right printing (1st ed / reverse / etc.).
    if rec["variation"]:
        bits.append(rec["variation"])
    bits.append(rec["grader"])
    if rec["grade_num"]:
        bits.append(rec["grade_num"])
    return " ".join(b for b in bits if b).strip()


def search_url(q: str) -> str:
    # Best-match sort: surfaces the most relevant listings, which also tend to
    # be the cleanest white-bg auction-house scans (better, more consistent
    # photos than newest-listed phone shots). Correct-card matching — not the
    # sort — is what keeps a modern cert off an old-era slab.
    return (f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(q)}"
            f"&_ipg=60")


# ── eBay image scrape ───────────────────────────────────────────────────────
_IMG_JS = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('li.s-item, li.s-card')) {
    const img = el.querySelector('img');
    let src = img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '';
    const a = el.querySelector('a.s-item__link, a.su-link, a[href*="/itm/"]');
    const href = a ? a.href.split('?')[0] : '';
    let title = (el.querySelector('.s-item__title, [role="heading"], .su-styled-text.primary')?.textContent || '').trim();
    title = title.replace(/^New Listing/i, '').trim();
    if (!src || !title || /Shop on eBay/i.test(title)) continue;
    out.push({ title, src, href });
  }
  return out;
}"""

# Listing-page image extractor: the search-result <img> is only a thumbnail,
# so we open the actual listing and read the gallery's FULL-RES sources. eBay's
# `data-zoom-src` is the zoom-level (typically s-l1600) original.
_LISTING_IMG_JS = r"""() => {
  const urls = new Set();
  const sels = ['.ux-image-carousel img', '.ux-image-carousel-item img',
                '.ux-image-magnify img', 'img[data-zoom-src]', '#icImg',
                '.img.img300 img', '.vi-image-gallery img'];
  for (const s of sels) for (const im of document.querySelectorAll(s)) {
    for (const a of ['data-zoom-src', 'data-srcset', 'data-src', 'src']) {
      const v = im.getAttribute(a);
      if (v && /ebayimg\.com/.test(v)) v.split(',').forEach(p => urls.add(p.trim().split(' ')[0]));
    }
  }
  const og = document.querySelector('meta[property="og:image"]');
  if (og && og.content) urls.add(og.content);
  return [...urls];
}"""


def _res_of(url: str) -> int:
    m = re.search(r"/s-l(\d+)\.", url)
    return int(m.group(1)) if m else 0


def _img_hash(url: str) -> str:
    """eBay image identity: the /g/<HASH>/ (or /<HASH>/s-l...) segment. The
    search thumbnail and the listing's full-res primary photo share this hash;
    a promo banner in the same gallery has a DIFFERENT hash."""
    m = re.search(r"/g/([^/]+)/", url) or re.search(r"ebayimg\.com/[^ ]*?/([A-Za-z0-9~_-]{6,})/s-l", url)
    return m.group(1) if m else ""


def hires(url: str) -> str:
    url = url.replace("/thumbs/", "/")
    url = re.sub(r"/s-l\d+\.(jpe?g|png|webp)", "/s-l1600.jpg", url, flags=re.I)
    return url


# Only the MAJOR companies are safe to reject on — obscure grader codes (TAG,
# GMA, ISA, ...) collide with card words ("Tag Team", etc.).
_MAJOR_GRADERS = ("psa", "bgs", "cgc", "sgc")


def grader_ok(title: str, rec: dict) -> bool:
    """The slab in the photo must be from the SAME grading company as our card.
    Require the card's grader in the title and reject any listing naming a
    different MAJOR company — so a PSA card never gets a CGC/BGS slab photo, and
    we skip "PSA vs CGC"-style comparison listings."""
    t = title.lower()
    want = rec["grader"].lower()
    # want present as a token start ("psa", "psa 10", "psa10" all match).
    if not re.search(r"\b" + re.escape(want), t):
        return False
    for g in _MAJOR_GRADERS:
        if g != want and re.search(r"\b" + g, t):
            return False
    return True


def variant_ok(title: str, rec: dict) -> bool:
    """Reject a candidate whose slab is a different VALUE-variant than our card
    (1st Edition / Shadowless / Reverse). Must agree in both directions."""
    t = title.lower()
    for _name, toks in VARIANT_GUARDS:
        card_has = any(x in rec["identity"] for x in toks)
        title_has = any(x in t for x in toks)
        if card_has != title_has:
            return False
    return True


def number_in_title(title: str, rec: dict) -> bool:
    if not rec["num_tokens"]:
        return True
    t = title.upper().replace("#", "")
    for n in rec["num_tokens"]:
        if re.search(r"[A-Z]", n):              # GG70 / SM211 / TG17 / XY79
            if n in t.replace(" ", ""):
                return True
        elif re.search(r"(?<!\d)" + re.escape(n) + r"(?!\d)", t):  # pure digits
            return True
    return False


def title_match(c: dict, rec: dict) -> bool:
    """Strong match: subject + grader + grade + the card NUMBER all present."""
    subj_tok = (rec["name"].split() or [""])[0].lower()
    t = c["title"].lower()
    return bool(subj_tok and subj_tok in t and rec["grader"].lower() in t
                and (not rec["grade_num"] or rec["grade_num"] in t)
                and number_in_title(c["title"], rec))


def matching_pool(cands: list[dict], rec: dict) -> list[dict]:
    """Ranked candidate pool. Variant guards are a HARD filter (never show a
    wrong-printing slab); within what survives, strong matches (number present)
    rank above weak (subject only). Each tagged with `strong`."""
    subj_tok = (rec["name"].split() or [""])[0].lower()
    # Hard filters: same grading company AND same value-variant as our card.
    pool = [c for c in cands
            if grader_ok(c["title"], rec) and variant_ok(c["title"], rec)]
    strong, weak = [], []
    for c in pool:
        c = dict(c)
        if title_match(c, rec):
            c["strong"] = True
            strong.append(c)
        elif subj_tok and subj_tok in c["title"].lower():
            c["strong"] = False
            weak.append(c)
    ranked = strong + weak
    if not ranked and pool:
        c = dict(pool[0]); c["strong"] = False
        ranked = [c]
    return ranked


def scan_score(body: bytes) -> float:
    """0..1 how "scan-like" the photo is: a clean straight-on shot on a PLAIN
    WHITE background (flatbed scan / auction-house studio style). Measured from
    the four CORNER patches — on a centered slab those are always background, so
    this reads the bg color regardless of how tightly the slab is cropped
    (a border-ring metric false-flags tight scans). White corners => scan;
    table/hand/colored/dark corners (phone photo) => low."""
    try:
        im = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception:
        return -1.0
    a = np.asarray(im).astype(np.float32)
    h, w, _ = a.shape
    if h < 40 or w < 40:
        return -1.0
    s = max(6, int(min(h, w) * 0.12))
    corners = [a[:s, :s], a[:s, -s:], a[-s:, :s], a[-s:, -s:]]
    fracs = []
    for c in corners:
        px = c.reshape(-1, 3)
        mn = px.min(axis=1)
        mx = px.max(axis=1)
        near_white = (mn > 205) & ((mx - mn) < 26)
        fracs.append(float(near_white.mean()))
    fracs.sort()
    # Return the SECOND-WORST corner: a true white-seamless scan has all four
    # corners white, so this stays high; a phone shot against a wall with a desk
    # at the bottom (two dark corners) scores ~0. Tolerates exactly one corner
    # clipped by a rotated slab/sticker, but demands the other three be white.
    return fracs[1]


WHITE_BG_MIN = 0.55          # 2nd-worst corner must be this white (>=3 corners)
# Grading-company tokens to detect in the slab LABEL via OCR. Only acronyms that
# don't collide with Pokémon card text — e.g. "TAG"/"ACE"/"GEM" are excluded
# because "Tag Team", "Ace Trainer", "GEM MT" appear on legit PSA labels.
_LABEL_GRADERS = ("psa", "cgc", "bgs", "sgc", "cga", "bccg", "hga", "ksa", "rcg", "isa")
_GRADER_ALIASES = {"bgs": ("bgs", "beckett"), "cgc": ("cgc",)}


def _download_hires(ctx, cand: dict) -> bytes | None:
    """Hi-res bytes for a candidate's PRIMARY image. The search thumbnail's
    eBay hash IS the primary photo; requesting big sizes of that hash returns
    the full-res original (min(requested, original)) — no listing-page nav."""
    base = cand["src"]
    def at(size):
        return re.sub(r"/s-l\d+\.(jpe?g|png|webp)", f"/s-l{size}.jpg", base, flags=re.I)
    best = None
    best_res = -1
    for url in dict.fromkeys([at(1600), at(1200), base]):
        try:
            resp = ctx.request.get(url, timeout=30_000)
            if not resp.ok:
                continue
            body = resp.body()
            if not body or len(body) <= 8000:
                continue
            try:
                w, h = Image.open(io.BytesIO(body)).size
            except Exception:
                continue
            if max(w, h) > best_res:
                best_res, best = max(w, h), body
            if max(w, h) >= 1200:
                break
        except Exception:
            continue
    return best


def label_grader_ok(body: bytes, rec: dict) -> tuple[bool, dict]:
    """OCR the slab's LABEL band (top third) and confirm it's the SAME grading
    company as our card — catches a listing whose title says PSA but whose photo
    is actually a CGA/CGC/etc. slab. Returns (ok, info)."""
    try:
        im = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception:
        return False, {"err": "decode"}
    w, h = im.size
    band = np.asarray(im.crop((0, 0, w, max(40, int(h * 0.38)))))
    try:
        result, _ = ocr()(band)
    except Exception:
        return True, {"err": "ocr"}          # don't block on OCR failure
    text = " ".join((t or "").lower() for _b, t, _c in (result or []))
    want = rec["grader"].lower()
    # Reject ONLY if a DIFFERENT company is clearly on the label (catches a
    # PSA-titled listing whose photo is a CGA/CGC slab). Do NOT require our own
    # grader to be OCR-readable — small/downscaled labels often don't OCR even
    # on a genuine PSA slab, and the title filter already confirmed the company.
    others = [g for g in _LABEL_GRADERS
              if g != want and re.search(r"\b" + g, text)]
    return (not others), {"others": others}


def scrape_image(page, ctx, rec: dict) -> tuple[bytes | None, dict]:
    """Search eBay, then DOWNLOAD-THEN-VERIFY candidates in rank order. Returns
    the first image that is (a) a clean plain-white-bg scan AND (b) confirmed by
    label OCR to be the right grading company. Falls back to the best available
    (marked not-consistent → placeholder) if none verify."""
    meta = {"query": search_query(rec)}
    try:
        page.goto(search_url(meta["query"]), wait_until="domcontentloaded",
                  timeout=PAGE_TIMEOUT_MS)
        try:
            page.wait_for_selector("li.s-item, li.s-card, .srp-save-null-search",
                                   timeout=15_000)
        except Exception:
            pass
        page.wait_for_timeout(900)
        cands = page.evaluate(_IMG_JS) or []
    except Exception as e:
        meta["error"] = f"nav: {e}"
        return None, meta
    if not cands:
        meta["error"] = "no_results"
        return None, meta

    # Title-filtered pool (right company + right variant), pre-ranked by thumb
    # white-bg score so the most scan-like correct-card candidates are tried first.
    pool = matching_pool(cands, rec)[:14]
    for c in pool:
        try:
            r = ctx.request.get(c["src"], timeout=20_000)
            c["scan_thumb"] = scan_score(r.body()) if r.ok else -1.0
        except Exception:
            c["scan_thumb"] = -1.0
    if not pool:
        meta["error"] = "no_candidate"
        return None, meta
    ranked = sorted(pool, key=lambda c: (c["strong"], c["scan_thumb"]), reverse=True)

    fallback = None     # (body, cand, wscore, ginfo) — highest-wscore tried
    for cand in ranked[:8]:
        body = _download_hires(ctx, cand)
        if not body:
            continue
        wscore = scan_score(body)
        gok, ginfo = label_grader_ok(body, rec)
        if fallback is None or wscore > fallback[2]:
            fallback = (body, cand, wscore, ginfo)
        if wscore >= WHITE_BG_MIN and gok:
            meta.update(strong_match=cand["strong"], match_title=cand["title"],
                        scan_score=round(wscore, 3), grader_info=ginfo,
                        consistent_style=True, verified=True)
            return body, meta

    # Nothing fully verified — return the best-effort one but mark it so the
    # caller uses a placeholder + "needs photo" flag instead of shipping it.
    if fallback:
        body, cand, wscore, ginfo = fallback
        meta.update(strong_match=cand["strong"], match_title=cand["title"],
                    scan_score=round(wscore, 3), grader_info=ginfo,
                    consistent_style=False, verified=False)
        return body, meta
    meta["error"] = "download_failed"
    return None, meta


# ── cert censoring ──────────────────────────────────────────────────────────
def _expand_box(pts, pad: int):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx, cy = sum(xs) / 4, sum(ys) / 4
    out = []
    for x, y in pts:
        out.append((x + (pad if x >= cx else -pad), y + (pad if y >= cy else -pad)))
    return out


def _blur_box(img: Image.Image, pts, pad: int):
    """Heavily blur the rectangular region covering a polygon box — a frosted
    smear over the cert rather than a hard black bar. Pixelate-then-blur so the
    digits are genuinely unreadable while still reading as a blur."""
    from PIL import ImageFilter
    ex = _expand_box(pts, pad)
    xs = [p[0] for p in ex]
    ys = [p[1] for p in ex]
    x0, y0 = max(0, int(min(xs))), max(0, int(min(ys)))
    x1, y1 = min(img.width, int(max(xs))), min(img.height, int(max(ys)))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return
    region = img.crop((x0, y0, x1, y1))
    w, h = region.size
    # Mosaic: shrink to a few px then back up — destroys the glyphs.
    small = region.resize((max(1, w // 18), max(1, h // 8)), Image.BILINEAR)
    region = small.resize((w, h), Image.NEAREST)
    # Soften the mosaic into a smooth blur.
    region = region.filter(ImageFilter.GaussianBlur(radius=max(4, h * 0.6)))
    img.paste(region, (x0, y0))


def censor_cert(img_bytes: bytes) -> tuple[Image.Image, int]:
    """Blur out any cert-number run on the slab. Returns (PIL image, n_regions).

    A PSA cert is 8 digits, CGC 10. Pass 1 blurs any single OCR box that's a
    >=7-digit run. Pass 2 (only if pass 1 found nothing) stitches pure-digit
    fragments sharing a text line — OCR sometimes splits the cert — and blurs
    them when the line concatenates to >=7 digits.
    """
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    arr = np.array(img)
    result, _ = ocr()(arr)
    boxes = result or []
    n = 0

    # Pass 1: long digit run in a single box.
    leftover = []
    for box, text, _conf in boxes:
        compact = re.sub(r"\s", "", text or "")
        digits = re.sub(r"\D", "", text or "")
        if len(digits) >= 7 and len(digits) >= 0.6 * max(1, len(compact)):
            _blur_box(img, box, 6)
            n += 1
        else:
            leftover.append((box, text))

    # Pass 2: stitch pure-digit fragments on the same line.
    if n == 0:
        frags = []
        for box, text in leftover:
            compact = re.sub(r"\s", "", text or "")
            digits = re.sub(r"\D", "", text or "")
            if compact and digits == compact and len(digits) >= 3:
                ys = [p[1] for p in box]
                xs = [p[0] for p in box]
                frags.append({"box": box, "len": len(digits),
                              "yc": sum(ys) / 4, "h": max(ys) - min(ys)})
        used = [False] * len(frags)
        for i, f in enumerate(frags):
            if used[i]:
                continue
            line = [f]
            used[i] = True
            for j, g in enumerate(frags):
                if not used[j] and abs(g["yc"] - f["yc"]) <= max(8, f["h"] * 0.6):
                    line.append(g)
                    used[j] = True
            if sum(x["len"] for x in line) >= 7:
                for x in line:
                    _blur_box(img, x["box"], 6)
                    n += 1
    return img, n


def normalize_frame(img: Image.Image) -> Image.Image:
    """Standardize zoom/framing so every slab fills the canvas the same amount.
    Detects the slab against its (near-white) background, crops to it with a
    uniform margin, and pads to a fixed portrait aspect ratio. If the slab can't
    be detected (off-style photo, non-white bg), returns the image unchanged."""
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w, _ = a.shape
    mn = a.min(2)
    mx = a.max(2)
    content = ~((mn > 205) & ((mx - mn) < 30))     # non-near-white = slab/content
    col = content.mean(0)
    row = content.mean(1)
    xs = np.where(col > 0.04)[0]
    ys = np.where(row > 0.04)[0]
    if len(xs) < 5 or len(ys) < 5:
        return img
    x0, x1, y0, y1 = int(xs[0]), int(xs[-1]), int(ys[0]), int(ys[-1])
    bw, bh = x1 - x0, y1 - y0
    if bw < w * 0.2 or bh < h * 0.2:               # detection too small — bail
        return img
    px, py = int(bw * 0.07), int(bh * 0.07)
    x0, x1 = max(0, x0 - px), min(w, x1 + px)
    y0, y1 = max(0, y0 - py), min(h, y1 + py)
    crop = img.crop((x0, y0, x1, y1))
    cw, ch = crop.size
    TARGET_AR = 0.72                                # slab-ish portrait
    if cw / ch < TARGET_AR:                         # pad width
        nw = int(round(ch * TARGET_AR))
        canvas = Image.new("RGB", (nw, ch), (255, 255, 255))
        canvas.paste(crop, ((nw - cw) // 2, 0))
    else:                                           # pad height
        nh = int(round(cw / TARGET_AR))
        canvas = Image.new("RGB", (cw, nh), (255, 255, 255))
        canvas.paste(crop, (0, (nh - ch) // 2))
    return canvas.resize((1000, 1389), Image.LANCZOS)


def finalize_image(img_bytes: bytes) -> tuple[bytes, int]:
    """Censor the cert (blur) then normalize framing. Returns (jpeg, n_blurred)."""
    censored, n = censor_cert(img_bytes)
    framed = normalize_frame(censored)
    out = io.BytesIO()
    framed.save(out, format="JPEG", quality=92)
    return out.getvalue(), n


# ── upload ──────────────────────────────────────────────────────────────────
# Certs that are reserved / sale-pending — listed but marked CLAIMED on the
# graded shop (badge + non-purchasable). Add a cert here to flag it claimed.
CLAIMED_CERTS = {
    "120436530",   # 2023 151 Zapdos ex SIR #202 PSA 10 — claimed (Nick 2026-06-09)
}


def upload_one(rec: dict, jpeg: bytes, token: str) -> dict:
    card = {
        "cert_number": rec["cert"], "card_number": rec["number"],
        "name": rec["name"], "set_name": rec["set"], "year": rec["year"],
        "grader": rec["grader"], "grade": rec["grade"],
    }
    if rec["cert"] in CLAIMED_CERTS:
        card["listing_note"] = "CLAIMED — sale pending"
    elif rec.get("needs_photo"):
        card["listing_note"] = "Photo coming soon"
    payload = {
        "card": card,
        "price_cents": rec["price_cents"],
        "image_base64": base64.b64encode(jpeg).decode("ascii"),
        "image_filename": f"graded-{rec['cert']}-front.jpg",
    }
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


def load_progress() -> dict:
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_progress(p: dict) -> None:
    PROGRESS.write_text(json.dumps(p, indent=2), encoding="utf-8")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    dry = os.environ.get("DRY_RUN") == "1"
    use_cache = os.environ.get("USE_CACHE") == "1"
    limit = int(os.environ.get("LIMIT", "0") or "0")
    only = {c.strip() for c in (os.environ.get("ONLY") or "").split(",") if c.strip()}

    IMG_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)

    rows = []
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("Graded Cert #") or "").strip():
                rows.append(row)
    recs = [build_record(r) for r in rows]
    if only:
        recs = [r for r in recs if r["cert"] in only]
    if limit:
        recs = recs[:limit]

    progress = load_progress()

    # Skip certs already live on Square (resume-safe) unless re-forcing.
    live = set()
    if not dry:
        try:
            live = live_square_certs()
        except Exception as e:
            print(f"[relist] WARN could not read live certs: {e}")
    todo = [r for r in recs
            if r["cert"] not in live
            and progress.get(r["cert"], {}).get("status") != "uploaded"]

    print(f"[relist] CSV rows {len(recs)} | already live {len(recs) - len(todo)} | "
          f"to process {len(todo)} | DRY_RUN={dry} USE_CACHE={use_cache}")

    token = None
    if not dry:
        token = get_token()
        if not token:
            print("[relist] No SK_ADMIN_TOKEN — cannot upload."); return

    # Proxy guard (same policy as _ebay_chrome).
    proxy = _proxy_config()
    need_scrape = any(not (IMG_DIR / f"{r['cert']}.jpg").exists() for r in todo) or not use_cache
    if need_scrape and proxy is None and os.environ.get("ALLOW_NO_PROXY") != "1":
        raise SystemExit(
            "[relist] No proxy configured — refusing to scrape from the bare IP.\n"
            f"  Set EBAY_PROXY=... or write it to {PROXY_FILE}, or ALLOW_NO_PROXY=1.")

    flags = {"no_image": [], "needs_photo": [], "no_cert_censored": [],
             "weak_match": [], "upload_err": []}
    ok = 0

    from playwright.sync_api import sync_playwright
    headless = os.environ.get("EBAY_HEADLESS") == "1"

    pw = ctx = page = None
    if need_scrape:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        pw = sync_playwright().start()
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=headless, proxy=proxy,
            args=["--disable-blink-features=AutomationControlled", "--disable-infobars"],
            user_agent=UA, viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _warmup(page)

    try:
        for i, rec in enumerate(todo, 1):
            cert = rec["cert"]
            cached_img = IMG_DIR / f"{cert}.jpg"
            title_preview = (f"{rec['grader']} {rec['grade']} {rec['year']} "
                             f"{rec['set']} {rec['name']} #{rec['number']}")
            jpeg = None
            meta = {}

            if use_cache and cached_img.exists():
                jpeg = cached_img.read_bytes()
                meta = {"cached": True}
                ncert = -1  # unknown; trust prior censor
            else:
                raw, meta = scrape_image(page, ctx, rec)
                if raw is None:
                    flags["no_image"].append((cert, title_preview, meta.get("error", "")))
                    progress[cert] = {"status": "no_image", "meta": meta,
                                      "title": title_preview}
                    save_progress(progress)
                    print(f"[relist] {i:>2}/{len(todo)} NO IMG  {cert}  ({meta.get('error')})  {title_preview[:60]}")
                    if i < len(todo):
                        time.sleep(NAV_DELAY_SEC)
                    continue
                (RAW_DIR / f"{cert}.jpg").write_bytes(raw[:5_000_000])
                jpeg, ncert = finalize_image(raw)
                # No clean white-bg scan exists for this card on eBay — Nick
                # doesn't want a non-white-bg phone photo, so list it with the
                # logo placeholder + "photo coming soon" and flag it for a
                # manual scan rather than showing an off-style shot.
                rec["needs_photo"] = not meta.get("consistent_style")
                if rec["needs_photo"]:
                    jpeg = PLACEHOLDER_BYTES
                    flags["needs_photo"].append((cert, title_preview,
                                                 f"best scan={meta.get('scan_score')}"))
                cached_img.write_bytes(jpeg)
                if not meta.get("strong_match") and not rec["needs_photo"]:
                    flags["weak_match"].append((cert, title_preview, meta.get("match_title", "")))
                if ncert == 0 and not rec["needs_photo"]:
                    flags["no_cert_censored"].append((cert, title_preview, meta.get("match_title", "")))

            if dry:
                tag = "DRY"
                if not (use_cache and cached_img.exists()):
                    tag += f" cert_boxes={ncert} strong={meta.get('strong_match')}"
                print(f"[relist] {i:>2}/{len(todo)} {tag}  {cert}  {title_preview[:60]}")
                if i < len(todo) and not (use_cache and cached_img.exists()):
                    time.sleep(NAV_DELAY_SEC)
                continue

            res = upload_one(rec, jpeg, token)
            if res.get("ok"):
                ok += 1
                progress[cert] = {"status": "uploaded", "item_id": res.get("item_id"),
                                  "title": res.get("title", title_preview), "meta": meta}
                print(f"[relist] {i:>2}/{len(todo)} OK  {cert}  {res.get('item_id','')}  {title_preview[:55]}")
            else:
                flags["upload_err"].append((cert, title_preview, str(res)[:160]))
                progress[cert] = {"status": "upload_err", "error": res, "title": title_preview}
                print(f"[relist] {i:>2}/{len(todo)} ERR {cert}  {res}")
            save_progress(progress)
            if i < len(todo):
                time.sleep(NAV_DELAY_SEC if not (use_cache and cached_img.exists()) else 0.4)
    finally:
        if ctx is not None:
            ctx.close()
        if pw is not None:
            pw.stop()

    # ── flag report ─────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"[relist] DONE — {ok} uploaded.")
    for key, label in [("no_image", "NO IMAGE FOUND"),
                       ("needs_photo", "NO WHITE-BG SCAN — listed with placeholder, needs manual photo"),
                       ("no_cert_censored", "NO CERT RUN DETECTED TO CENSOR (check photo)"),
                       ("weak_match", "WEAK TITLE MATCH (image may be wrong variant)"),
                       ("upload_err", "UPLOAD ERROR")]:
        items = flags[key]
        if items:
            print(f"\n  ⚠ {label} — {len(items)}:")
            for cert, title, extra in items:
                print(f"      {cert}  {title[:58]}")
                if extra:
                    print(f"           ↳ {extra[:90]}")
    if not any(flags.values()):
        print("  No flags — all clean.")
    save_progress(progress)


if __name__ == "__main__":
    main()
