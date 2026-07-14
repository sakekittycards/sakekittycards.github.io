"""Turn a seller's MEDIA attachments into priceable item dicts for make_offer().

A collection-buy message can arrive with more than text — Messenger/IG deliver
attachments as URLs, and the Dropbox watcher drops files on disk. This module reads
four media kinds and returns items in the same shape the free-text path produces
(so _offer_bot.handle_message can merge them straight into make_offer):

    {"name","set","number","grade","is_sealed"?,"qty"?}

Routing:
  image  -> Claude vision, ONE prompt that pulls every card it can see. Works for BOTH
            a screenshot of a list/collection (eBay / TCGplayer / Collectr / Notes /
            a spreadsheet) AND a photo of physical cards laid out.
  video  -> sample frames (ffmpeg) -> vision each -> dedupe by name+number+grade.
  file   -> csv / xlsx parsed by columns ; pdf via PyMuPDF text (falls back to rendering
            pages to images + vision when the PDF is scanned/image-only).

Everything degrades gracefully: a missing key, unreachable URL, or unsupported file
returns [] with a printed note rather than raising — a bad attachment must never take
down an offer. Vision cost is bounded (video frames capped) so a long clip can't run away.
"""
from __future__ import annotations

import base64
import csv as _csv
import io
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

_MODEL = "claude-opus-4-8"
_MAX_VIDEO_FRAMES = 24          # hard cap on vision calls per video (cost guard)
_VIDEO_FPS = 0.5               # sample ~1 frame / 2s, then cap to _MAX_VIDEO_FRAMES


# ── Claude client (mirrors _offer_bot._anthropic) ─────────────────────────────
def _anthropic():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:
        return None


# ── fetch: URL (Meta CDN) or local path -> (bytes, content_type, suffix) ──────
def _fetch(src):
    s = str(src or "")
    if re.match(r"^https?://", s, re.I):
        req = urllib.request.Request(s, headers={"User-Agent": "SakeKittyBot/1.0"})
        with urllib.request.urlopen(req, timeout=45) as r:
            data = r.read()
            ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        suffix = Path(s.split("?")[0]).suffix.lower()
        return data, ct, suffix
    p = Path(s)
    data = p.read_bytes()
    return data, "", p.suffix.lower()


def _b64(data):
    return base64.standard_b64encode(data).decode("ascii")


def _img_media_type(content_type, suffix, data=b""):
    """Pick a Claude-accepted image media_type. Magic bytes WIN — extensions and even
    Content-Type headers lie (e.g. a .jpg that is really a PNG), and Claude rejects a
    mismatch. Fall back to header, then extension, then jpeg."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if content_type in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        return content_type
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".gif": "image/gif", ".webp": "image/webp"}.get(suffix, "image/jpeg")


# ── item normalisation ────────────────────────────────────────────────────────
_GRADE_RE = re.compile(r"\b(PSA|CGC|BGS|SGC|TAG|ACE)\b\s*\d", re.I)


def _norm_items(raw):
    """Coerce a vision/file row list into make_offer item dicts (drop empties)."""
    out = []
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        grade = str(it.get("grade") or "").strip()
        kind = str(it.get("kind") or "").strip().lower()
        item = {"name": name,
                "set": str(it.get("set") or "").strip(),
                "number": str(it.get("number") or "").strip(),
                "grade": grade if _GRADE_RE.search(grade) else ""}
        if kind == "sealed" or it.get("is_sealed"):
            item["is_sealed"] = True
        try:
            q = int(it.get("qty") or 1)
            if q > 1:
                item["qty"] = q
        except (TypeError, ValueError):
            pass
        out.append(item)
    return out


def _parse_items_json(text):
    """Extract a JSON {"items":[...]} (or a bare [...]) from a model reply."""
    t = text or ""
    try:
        s = t.find("{")
        e = t.rfind("}")
        if s >= 0 and e > s:
            d = json.loads(t[s:e + 1])
            return _norm_items(d.get("items", []))
    except Exception:
        pass
    try:
        s = t.find("[")
        e = t.rfind("]")
        if s >= 0 and e > s:
            return _norm_items(json.loads(t[s:e + 1]))
    except Exception:
        pass
    return []


# ── image (screenshots + card photos) ────────────────────────────────────────
_IMG_PROMPT = (
    "This image is from someone SELLING Pokemon cards to a card shop. It is EITHER a "
    "screenshot of a card list/collection (from eBay, TCGplayer, Collectr, a notes app, or "
    "a spreadsheet) OR a photo of physical cards laid out. Extract EVERY distinct card/product "
    "you can identify. Return ONLY this JSON:\n"
    '{"items":[{"name":str,"set":str,"number":str,"grade":str,"kind":"graded|raw|sealed","qty":int}]}\n'
    "Rules: name = the card or sealed-product name (expand abbreviations: 'CP ETB' -> "
    "'Champions Path Elite Trainer Box'). number = the collector number as printed ('58', "
    "'199/165', 'SV107') or '' if none. grade = 'PSA 10' / 'CGC 9.5' etc, or '' if raw/ungraded. "
    "kind = 'graded' if it shows a grading company + grade, 'sealed' for boxes/ETBs/tins/packs/"
    "collections, else 'raw'. qty = how many of that exact line (default 1). If a screenshot shows "
    "a per-row quantity or price, use the quantity but IGNORE the price. Only include cards you can "
    "actually read — do NOT invent. Output ONLY the JSON object."
)


_TXT_PROMPT = (
    "The following TEXT was extracted from a document/list a person sent while SELLING Pokemon "
    "cards to a card shop (e.g. a Collectr/TCGplayer export, a PDF, or a typed list). Extract EVERY "
    "distinct card/product. Return ONLY this JSON:\n"
    '{"items":[{"name":str,"set":str,"number":str,"grade":str,"kind":"graded|raw|sealed","qty":int}]}\n'
    "Rules: name = card or sealed-product name (expand abbreviations). number = collector number as "
    "printed ('58','199/165','SV107') or ''. grade = 'PSA 10'/'CGC 9.5' or '' if raw. kind = 'graded' "
    "with a company+grade, 'sealed' for boxes/ETBs/tins/packs, else 'raw'. qty = per-row quantity "
    "(default 1); IGNORE any prices. Only real cards you can read — do NOT invent. Output ONLY the JSON.\n\n"
    "TEXT:\n")


def extract_from_text(text, label="text"):
    """LLM-parse a block of extracted text (PDF text layer, etc.) into items. Layout-agnostic —
    handles tables/lists a regex would choke on."""
    client = _anthropic()
    if not client or not (text or "").strip():
        return []
    try:
        m = client.messages.create(
            model=_MODEL, max_tokens=4000,
            messages=[{"role": "user", "content": _TXT_PROMPT + (text or "")[:20000]}])
        return _parse_items_json(m.content[0].text)
    except Exception as e:
        print(f"[media] {label}: text extract failed: {e}")
        return []


def extract_from_image(data, content_type="", suffix="", label="image"):
    client = _anthropic()
    if not client:
        print(f"[media] {label}: no ANTHROPIC_API_KEY — skipped")
        return []
    mt = _img_media_type(content_type, suffix, data)
    try:
        m = client.messages.create(
            model=_MODEL, max_tokens=4000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mt, "data": _b64(data)}},
                {"type": "text", "text": _IMG_PROMPT}]}])
        return _parse_items_json(m.content[0].text)
    except Exception as e:
        print(f"[media] {label}: vision failed: {e}")
        return []


# ── video (fan-through clips) ─────────────────────────────────────────────────
def _sample_frames(video_bytes, max_frames=_MAX_VIDEO_FRAMES, fps=_VIDEO_FPS):
    """ffmpeg-sample a clip to JPEG frames (bytes). Interval sampling, then hard-cap
    to max_frames evenly across the clip so a long video can't blow up vision cost."""
    with tempfile.TemporaryDirectory() as td:
        vp = Path(td) / "clip.bin"
        vp.write_bytes(video_bytes)
        out = Path(td) / "f_%04d.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(vp),
                 "-vf", f"fps={fps},scale=1024:-1:flags=lanczos", "-q:v", "4", str(out)],
                check=True, timeout=180)
        except Exception as e:
            print(f"[media] video: ffmpeg failed: {e}")
            return []
        frames = sorted(Path(td).glob("f_*.jpg"))
        if len(frames) > max_frames:                     # keep an even spread
            step = len(frames) / max_frames
            frames = [frames[int(i * step)] for i in range(max_frames)]
        return [f.read_bytes() for f in frames]


def extract_from_video(data, label="video"):
    frames = _sample_frames(data)
    if not frames:
        return []
    print(f"[media] {label}: {len(frames)} frames sampled")
    seen, items = set(), []
    for i, fb in enumerate(frames):
        for it in extract_from_image(fb, content_type="image/jpeg", label=f"{label} f{i}"):
            key = (it["name"].lower(), it.get("number", ""), it.get("grade", ""))
            if key not in seen:
                seen.add(key)
                items.append(it)
    return items


# ── files (csv / xlsx / pdf) ──────────────────────────────────────────────────
_COL = {
    "name": ("name", "product", "product name", "card", "card name", "title", "description", "player"),
    "set": ("set", "set name", "edition", "series", "expansion"),
    "number": ("number", "card number", "collector number", "no", "no.", "#", "card #"),
    "grade": ("grade", "grading", "condition") ,
    "qty": ("qty", "quantity", "count", "amount"),
}


def _match_col(header):
    h = re.sub(r"\s+", " ", str(header or "").strip().lower())
    for field, keys in _COL.items():
        if h in keys:
            return field
    return None


def _rows_to_items(header, rows):
    idx = {}
    for i, h in enumerate(header):
        f = _match_col(h)
        if f and f not in idx:
            idx[f] = i
    if "name" not in idx:                                # no recognisable name column
        return []
    items = []
    for r in rows:
        def get(f):
            i = idx.get(f)
            return str(r[i]).strip() if i is not None and i < len(r) and r[i] is not None else ""
        nm = get("name")
        if not nm:
            continue
        items.append({"name": nm, "set": get("set"), "number": get("number"),
                      "grade": get("grade"), "qty": get("qty") or 1})
    return _norm_items(items)


def extract_from_csv(data, label="csv"):
    try:
        text = data.decode("utf-8-sig", errors="replace")
        rows = list(_csv.reader(io.StringIO(text)))
    except Exception as e:
        print(f"[media] {label}: csv parse failed: {e}")
        return []
    if not rows:
        return []
    return _rows_to_items(rows[0], rows[1:])


def extract_from_xlsx(data, label="xlsx"):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = [[c for c in row] for row in ws.iter_rows(values_only=True)]
    except Exception as e:
        print(f"[media] {label}: xlsx parse failed: {e}")
        return []
    if not rows:
        return []
    return _rows_to_items(rows[0], rows[1:])


def extract_from_pdf(data, label="pdf"):
    """Handle every PDF shape:
      • text layer   -> LLM-parse it (layout-agnostic, cheap, exact)
      • image-only pages (scans / photo pages with little/no text) -> vision-render them
      • MIXED (text-listed cards AND separate image-only cards) -> do BOTH and dedupe
    so image-only cards inside an otherwise-text PDF are never dropped."""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        print(f"[media] {label}: pdf open failed: {e}")
        return []

    items, seen = [], set()

    def _add(new):
        for it in new:
            key = (it["name"].lower(), it.get("number", ""), it.get("grade", ""))
            if key not in seen:
                seen.add(key)
                items.append(it)

    # 1) text layer (whole doc) → LLM extract
    text = "\n".join((page.get_text() or "") for page in doc).strip()
    if len(text) >= 40:
        _add(extract_from_text(text, label=label))

    # 2) vision any page that is essentially an image with no text of its own (cap 8)
    img_pages = [p for p in doc if len((p.get_text() or "").strip()) < 20 and p.get_images()]
    for page in img_pages[:8]:
        pix = page.get_pixmap(dpi=150)
        _add(extract_from_image(pix.tobytes("png"), content_type="image/png", label=f"{label} p{page.number}"))

    # 3) safety net: nothing yet (e.g. a scan with no detectable embedded image) → render all pages
    if not items:
        for i, page in enumerate(doc):
            if i >= 8:
                break
            pix = page.get_pixmap(dpi=150)
            _add(extract_from_image(pix.tobytes("png"), content_type="image/png", label=f"{label} p{i}"))

    return items


def extract_from_file(data, suffix, label="file"):
    sfx = (suffix or "").lower()
    if sfx == ".csv" or (data[:1] and b"," in data[:200] and b"\n" in data[:2000] and sfx not in (".xlsx", ".pdf")):
        return extract_from_csv(data, label)
    if sfx in (".xlsx", ".xlsm"):
        return extract_from_xlsx(data, label)
    if sfx == ".pdf" or data[:5] == b"%PDF-":
        return extract_from_pdf(data, label)
    print(f"[media] {label}: unsupported file type '{sfx}'")
    return []


# ── dispatch ──────────────────────────────────────────────────────────────────
_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}


def _kind(att, ct, suffix):
    """image | video | file, from Meta's declared type then content-type/extension."""
    t = str(att.get("type") or "").lower()
    if t in ("image", "video", "file"):
        if t == "file":                                  # Meta lumps some media under 'file'
            if ct.startswith("video") or suffix in _VIDEO_EXT:
                return "video"
            if ct.startswith("image") or suffix in _IMAGE_EXT:
                return "image"
        return t
    if ct.startswith("video") or suffix in _VIDEO_EXT:
        return "video"
    if ct.startswith("image") or suffix in _IMAGE_EXT:
        return "image"
    return "file"


def gather_media(attachments):
    """attachments: list of {"type":"image|video|file", "url"|"path": str, "name"?: str}.
    Returns (items, source_str). Each attachment is fetched + routed; failures are skipped."""
    items, parts = [], []
    for a in (attachments or []):
        src = a.get("url") or a.get("path")
        if not src:
            continue
        name = a.get("name") or "attachment"
        try:
            data, ct, suffix = _fetch(src)
        except Exception as e:
            print(f"[media] fetch failed ({name}): {e}")
            parts.append(f"1 unreadable {name}")
            continue
        kind = _kind(a, ct, suffix)
        if kind == "image":
            got = extract_from_image(data, ct, suffix, label=name)
            parts.append(f"{len(got)} from screenshot/photo")
        elif kind == "video":
            got = extract_from_video(data, label=name)
            parts.append(f"{len(got)} from video")
        else:
            got = extract_from_file(data, suffix, label=name)
            parts.append(f"{len(got)} from file")
        items += got
    # dedupe across all attachments (same card seen in a photo AND a screenshot)
    seen, deduped = set(), []
    for it in items:
        key = (it["name"].lower(), it.get("number", ""), it.get("grade", ""), bool(it.get("is_sealed")))
        if key not in seen:
            seen.add(key)
            deduped.append(it)
    return deduped, ("; ".join(parts) if parts else "no media")


if __name__ == "__main__":
    import sys
    atts = [{"type": "file", "path": p} if Path(p).suffix.lower() not in (_IMAGE_EXT | _VIDEO_EXT)
            else {"type": ("video" if Path(p).suffix.lower() in _VIDEO_EXT else "image"), "path": p}
            for p in sys.argv[1:]]
    got, src = gather_media(atts)
    print(f"SOURCE: {src}")
    print(json.dumps(got, indent=2))
