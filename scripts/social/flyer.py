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


# Filename markers that mean "this is the site's branding", not a show flyer.
# Observed on the real organizer sites for shows on this calendar: Collect-A-Con's
# homepage advertises `cropped-cropped-CAC-Logo-2024-1.png` and Dezerland's
# advertises `dezer-Facebook.jpg`. Both are perfectly good og:images and neither
# is event artwork; posting them as "the official flyer" would put a venue's
# Facebook banner out as if it were the show's poster.
_BRAND_MARKERS = (
    "logo", "favicon", "icon", "cropped", "default", "share", "facebook",
    "og-", "og_", "header", "avatar", "profile", "placeholder", "thumb",
)


def looks_like_event_artwork(url: str, page_url: str) -> tuple[bool, str]:
    """Would a person call this the show's flyer? Reasons, not just a verdict.

    Deliberately strict. A false negative costs us nothing — we generate our own
    graphic, which we know is ours and which is on-brand. A false positive posts
    somebody else's logo to our feed captioned as their event.
    """
    name = url.rsplit("/", 1)[-1].split("?")[0].lower()
    for marker in _BRAND_MARKERS:
        if marker in name:
            return False, f"filename contains {marker!r} — site branding, not event artwork"

    # A homepage's og:image is, by definition, the brand's picture of itself.
    # Event artwork lives on an event page.
    path = page_url.split("://", 1)[-1].split("/", 1)
    if len(path) < 2 or not path[1].strip("/"):
        return False, "taken from a site homepage — that og:image is the brand's, not a show's"

    return True, "from an event-specific page and not named as site branding"


def resolve(client, ev: dict) -> dict | None:
    """Return a stored media row for this event's official flyer, or None.

    Returning None is a perfectly good outcome — it means we render our own
    branded graphic instead of republishing something that only looked official.
    """
    event_id = ev.get("id")
    trace = []

    # 1 — a flyer explicitly attached to the event record. Someone chose this
    #     deliberately, so it skips the heuristics.
    if ev.get("flyer_url"):
        got = _try_fetch(client, ev["flyer_url"], event_id, "attached-flyer")
        trace.append((ev["flyer_url"], "accepted" if got else "fetch/validation failed",
                      "explicitly attached to the event"))
        if got:
            got["trace"] = trace
            return got

    # 2 — already in our library for this event.
    if ev.get("flyer_media_id"):
        try:
            m = client.get("/media", id=ev["flyer_media_id"])["media"]
            m["trace"] = trace + [(m.get("source_url"), "accepted", "already stored")]
            return m
        except Exception:
            pass

    # 3 — the event page's own preview image, then the organizer's.
    for field, method in (("event_url", "event-page-og"), ("social_url", "organizer-og")):
        page = ev.get(field)
        if not page:
            continue
        try:
            img_url = og_image(page)
        except Exception as e:
            trace.append((page, "rejected", f"could not read the page ({type(e).__name__})"))
            continue
        if not img_url:
            trace.append((page, "rejected", "page declares no og:image"))
            continue

        okay, why = looks_like_event_artwork(img_url, page)
        if not okay:
            trace.append((img_url, "rejected", why))
            continue

        got = _try_fetch(client, img_url, event_id, method, referer=page)
        trace.append((img_url, "accepted" if got else "rejected",
                      why if got else "failed the worker's validation (size/type/redirect)"))
        if got:
            got["trace"] = trace
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
