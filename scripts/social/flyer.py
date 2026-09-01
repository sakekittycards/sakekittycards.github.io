# -*- coding: utf-8 -*-
"""Flyer resolution — find the organizer's own event artwork, or don't.

A resolver chain, not a scraper. Each source is tried in order and the first one
that yields a usable image wins; every one of them requires a URL that came from
the event itself, so there is no path here that ends at an image search:

  1. a flyer already attached to the event record (`flyer_url`)
  2. an image already stored for this event in our own media library
  3. the event page's own OpenGraph / Twitter card image (`event_url`)
  4. the organizer site's OpenGraph image (`social_url`)

## What is deliberately absent

There is no Google Images step, no reverse-image search, no "first result for the
show name". Reposting an image found that way means reposting whatever a stranger
uploaded — including other dealers' photos and licensed art. The resolver
strongly prefers first-party artwork and returns None rather than guessing;
returning None is a good outcome, because it means we generate our own graphic,
which we know is ours.

Validation lives in the worker (`media.fetchCandidate`): https only, no
redirect off the host we were pointed at, a declared image content type, and a
size floor that rejects tracking pixels and social icons. Provenance — source
URL, domain, acquisition method, retrieval time, original filename, hash — is
stored on every stored asset.
"""
from __future__ import annotations

import io
import re
import urllib.request

from PIL import Image

UA = "sakekitty-social/1.0 (+https://sakekittycards.com)"

# Both spellings, both attribute orders. Written out rather than parsed with an
# HTML library so this stays dependency-free; it only ever reads two tags.
_META = re.compile(
    r"""<meta[^>]+(?:property|name)\s*=\s*["'](og:image(?::secure_url)?|twitter:image)["'][^>]*>""",
    re.I)
_CONTENT = re.compile(r"""content\s*=\s*["']([^"']+)["']""", re.I)


def og_image(page_url: str, timeout: int = 20) -> str | None:
    """The page's declared social preview image.

    This is the right thing to read: og:image is what the organizer chose to
    represent the event, which for a show page is almost always the flyer.
    """
    req = urllib.request.Request(page_url, headers={
        "user-agent": UA,
        "accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=timeout) as res:
        ctype = (res.headers.get("content-type") or "").lower()
        if "html" not in ctype:
            return None
        # Only the head is needed, and a 200KB cap stops a huge page from
        # becoming a memory problem.
        html = res.read(200_000).decode("utf-8", errors="replace")

    for m in _META.finditer(html):
        c = _CONTENT.search(m.group(0))
        if not c:
            continue
        url = c.group(1).strip()
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            from urllib.parse import urljoin
            url = urljoin(page_url, url)
        if url.startswith("https://"):
            return url
    return None


def resolve(client, ev: dict) -> dict | None:
    """Return a stored media row for this event's official flyer, or None.

    `client` is a scripts.social.client.Client; the actual fetch and validation
    happen worker-side so that provenance is recorded in one place.
    """
    event_id = ev.get("id")

    # 1 — already attached
    if ev.get("flyer_url"):
        got = _try_fetch(client, ev["flyer_url"], event_id, "attached-flyer")
        if got:
            return got

    # 2 — already in our library for this event
    #     (the worker dedupes by content hash, so a repeat fetch is free anyway;
    #      this is the offline path when the organizer's site is down.)
    if ev.get("flyer_media_id"):
        try:
            return client.get("/media", id=ev["flyer_media_id"])["media"]
        except Exception:
            pass

    # 3 — the event page's own preview image
    for field, method in (("event_url", "event-page-og"), ("social_url", "organizer-og")):
        page = ev.get(field)
        if not page:
            continue
        try:
            img_url = og_image(page)
        except Exception:
            continue
        if not img_url:
            continue
        got = _try_fetch(client, img_url, event_id, method, referer=page)
        if got:
            return got

    return None


def _try_fetch(client, url, event_id, acquisition, referer=None):
    try:
        res = client.post("/media/fetch-flyer", {
            "url": url, "event_id": event_id,
            "acquisition": acquisition, "referer": referer,
        })
        return res["media"] | {"source_url": res["source"]}
    except Exception:
        return None


def load(client, media: dict) -> Image.Image:
    """Pull the stored flyer back down so the template can composite it."""
    url = media.get("url")
    req = urllib.request.Request(url, headers={"user-agent": UA})
    with urllib.request.urlopen(req, timeout=40) as res:
        return Image.open(io.BytesIO(res.read())).convert("RGB")
