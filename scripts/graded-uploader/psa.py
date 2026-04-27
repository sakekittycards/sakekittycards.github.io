"""
Shared PSA-label parsing + pokemontcg.io enrichment.

Imported by both test_ocr.py (sanity test) and process_inbox.py (production).
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Optional

from PIL import Image


def isolate_label(slab: Image.Image) -> Image.Image:
    """Crop to the top ~16% of a slab where the PSA label sits."""
    w, h = slab.size
    return slab.crop((0, 0, w, int(h * 0.16)))


def _split_camelish(s: str) -> str:
    """Insert spaces at digit/letter boundaries (OCR collapses '2023POKEMONSVPEN')."""
    s = re.sub(r"(?<=\d)(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=\d)", " ", s)
    return s


def _fix_common_ocr(s: str) -> str:
    """Common OCR mistakes on stylized PSA labels."""
    return s.replace("PIKACHUI", "PIKACHU/").replace("GREYFELT", "GREY FELT")


def parse_psa(lines: list[str]) -> dict:
    """
    Turn raw OCR'd lines from the PSA label into structured metadata.
    """
    parsed = {
        "year": None,
        "set": None,
        "card_title": None,
        "card_number": None,
        "grade": None,
        "cert_number": None,
    }
    expanded = [_fix_common_ocr(_split_camelish(ln)) for ln in lines]
    blob = " | ".join(expanded)

    m = re.search(r"\b(\d{8,10})\b", blob)
    if m:
        parsed["cert_number"] = m.group(1)

    m = re.search(r"#\s*([A-Z0-9\-/]+)", blob)
    if m:
        parsed["card_number"] = m.group(1).rstrip()

    m = re.search(
        r"\b(GEM\s*MT|GEM\s*MINT|MINT|NM[\-\s]?MT|EX[\-\s]?MT|VG[\-\s]?EX|GOOD|PR)\s*(\d{1,2})\b",
        blob, re.IGNORECASE,
    )
    if m:
        parsed["grade"] = f"{m.group(1).upper()} {m.group(2)}"
    else:
        m = re.search(r"\b(GEM\s*MT|GEM\s*MINT|MINT|NM[\-\s]?MT)\b", blob, re.IGNORECASE)
        if m:
            for ln in expanded:
                if re.fullmatch(r"\s*(\d{1,2})\s*", ln):
                    parsed["grade"] = f"{m.group(1).upper()} {ln.strip()}"
                    break

    m = re.search(r"\b(19\d{2}|20[0-3]\d)\b", blob)
    if m:
        parsed["year"] = m.group(1)

    text_lines = []
    for ln in expanded:
        if re.fullmatch(r"[\d\s\-]+", ln):
            continue
        if re.fullmatch(r"\s*PSA\s*", ln, re.IGNORECASE):
            continue
        if re.fullmatch(r"\s*(GEM\s*MT|GEM\s*MINT|MINT)\s*", ln, re.IGNORECASE):
            continue
        ln = re.sub(r"#\s*[A-Z0-9\-/]+", "", ln).strip()
        if ln:
            text_lines.append(ln)

    if text_lines:
        head = re.sub(r"^\s*(19\d{2}|20[0-3]\d)\s*", "", text_lines[0]).strip()
        parsed["set"] = head or text_lines[0]
        if len(text_lines) > 1:
            parsed["card_title"] = " ".join(text_lines[1:]).strip()

    return parsed


def _best_market_price(prices: dict | None) -> Optional[float]:
    """
    pokemontcg.io returns a dict like
      {'normal': {'market': 12.34, ...},
       'holofoil': {'market': 25.00, ...},
       ...}
    Pick the highest 'market' value across all variants — that's our
    suggested price column. Returns None if no market data.
    """
    if not prices:
        return None
    best = None
    for variant, fields in prices.items():
        if not isinstance(fields, dict):
            continue
        m = fields.get("market") or fields.get("mid")
        if m is None:
            continue
        try:
            m = float(m)
        except (TypeError, ValueError):
            continue
        if best is None or m > best:
            best = m
    return best


def lookup_pokemontcg(card_number: str, set_hint: str | None = None,
                      title_hint: str | None = None) -> dict | None:
    """
    Identify a card via pokemontcg.io. Returns canonical metadata + a
    suggested TCGplayer market price. None on miss.
    """
    if not card_number:
        return None

    norm_num = card_number.lstrip("0") or "0"

    # Map common PSA-label set fragments to pokemontcg.io set ids.
    SET_ALIASES = {
        "SVP": "svp",
        "SVE": "sve",
        "SWSH": "swshp",
        "XY": "xyp",
        "SM": "smp",
        "BLACK STAR": "swshp",
    }
    set_ids: list[str] = []
    if set_hint:
        upper = set_hint.upper()
        for frag, sid in SET_ALIASES.items():
            if frag in upper:
                set_ids.append(sid)

    queries: list[str] = []
    for sid in set_ids:
        queries.append(f"set.id:{sid} number:{norm_num}")
    if title_hint:
        first = re.split(r"\s|/", title_hint)[0].strip()
        if first and len(first) > 2:
            queries.append(f"name:{first} number:{norm_num}")
    queries.append(f"number:{norm_num}")

    headers = {
        "User-Agent": "SakeKittyCards-GradingPrep/1.0 (sakekittycards@gmail.com)",
        "Accept": "application/json",
    }
    for q in queries:
        url = f"https://api.pokemontcg.io/v2/cards?q={urllib.parse.quote(q)}&pageSize=5"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
        except Exception:
            continue
        cards = data.get("data") or []
        if not cards:
            continue

        c = cards[0]
        prices = (c.get("tcgplayer") or {}).get("prices")
        return {
            "name": c.get("name"),
            "set_name": (c.get("set") or {}).get("name"),
            "set_id": (c.get("set") or {}).get("id"),
            "number": c.get("number"),
            "rarity": c.get("rarity"),
            "image_small": ((c.get("images") or {}).get("small")),
            "image_large": ((c.get("images") or {}).get("large")),
            "tcgplayer_url": (c.get("tcgplayer") or {}).get("url"),
            "tcgplayer_market": _best_market_price(prices),
            "tcgplayer_updated": (c.get("tcgplayer") or {}).get("updatedAt"),
            "match_query": q,
        }
    return None
