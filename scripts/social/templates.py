# -*- coding: utf-8 -*-
"""Event graphic templates.

Every word on these graphics is drawn by this file from structured event data.
No generative model renders text, and no generative model is asked what the
event is called — a show name, a date and a venue are facts, and a model that is
90% right about a venue is 100% wrong on the one post that matters.

Where generative imagery could reasonably appear (a background texture), it does
not appear either: the ground is built from the brand's own gradients, which is
cheaper, deterministic, and cannot hallucinate a sponsor logo into a corner.

## The templates

`banner` — the default. Type-led: eyebrow, show name, date, venue, then the
mascot bottom-right with the footer lockup under it. Reads at thumbnail size,
which is where most of these are actually seen.

`flyer` — used when the organizer has official artwork. Their flyer is the hero
and is never cropped into: it is fitted whole into a card, with our band below
it. Their design stays theirs; we add attribution of ourselves, not of them.

`photo` — a booth photo as the hero, for shows we have shot before.

All three exist at 4:5 (1080×1350, the feed default), 1:1 and 9:16.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

from PIL import Image, ImageDraw, ImageFilter

import sk_brand as B

MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
          "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

EYEBROWS = {
    "ANNOUNCEMENT": "WE'LL BE THERE",
    "UPCOMING": "ONE WEEK OUT",
    "THIS_WEEKEND": "THIS WEEKEND",
    "DAY_OF": "TODAY",
}


@dataclass
class EventCopy:
    """Exactly the strings that will be drawn. Built once, then rendered.

    Separating this from the drawing is what makes the graphics testable: a test
    can assert that a three-day show in two months renders "OCT 31 – NOV 1"
    without rasterising anything.
    """
    eyebrow: str
    title: str
    date_line: str
    place_line: str
    detail_line: str
    cta: str


def build_copy(ev: dict, kind: str, booth: str | None = None) -> EventCopy:
    d1 = date.fromisoformat(ev["event_date"])
    d2 = date.fromisoformat(ev["end_date"]) if ev.get("end_date") else None

    if d2 and d2 != d1:
        if d1.month == d2.month:
            date_line = f"{MONTHS[d1.month - 1][:3]} {d1.day}–{d2.day}"
        else:
            date_line = f"{MONTHS[d1.month - 1][:3]} {d1.day} – {MONTHS[d2.month - 1][:3]} {d2.day}"
    else:
        date_line = f"{DAYS[d1.weekday()][:3]} · {MONTHS[d1.month - 1]} {d1.day}"

    city = (ev.get("city") or "").strip()
    state = (ev.get("state") or "").strip()
    venue = (ev.get("venue") or "").strip()
    where = f"{city}, {state}" if city and state else (city or state)
    # The big line is the city — that is what tells someone whether to come.
    # The venue is the detail line under it.
    place = where or venue
    detail = venue if (venue and venue.lower() != place.lower()) else ""
    if ev.get("hours_text") and len(ev["hours_text"]) <= 34:
        detail = f"{detail} · {ev['hours_text']}" if detail else ev["hours_text"]

    booth = booth or ev.get("booth")
    cta = booth if booth else ("BUY · SELL · TRADE" if ev.get("kind") != "online" else "LIVE ON WHATNOT")

    return EventCopy(
        eyebrow=EYEBROWS.get(kind, "WE'LL BE THERE"),
        title=ev["title"].upper(),
        date_line=date_line.upper(),
        place_line=place.upper(),
        detail_line=detail,
        cta=cta,
    )


# ── Shared furniture ─────────────────────────────────────────────────────────
def _eyebrow(img, cv, copy, y):
    B.flat_text(img, copy.eyebrow, B.INTER_XB, int(cv.w * 0.028), cv.w // 2, y,
                colour=B.GOLD, alpha=225, tracking_em=0.20, anchor="c")
    return y + int(cv.w * 0.028 * B.CAP_INTER) + int(cv.h * 0.022)


def _title_block(img, cv, copy, y, max_width, start_px, min_px):
    """Fit the show name to at most two lines, centred, largest size that fits."""
    px = B.fit_display(copy.title, max_width, start_px, min_px)
    lines = [copy.title]
    if px <= min_px + 2:
        px = int(start_px * 0.78)
        lines = B.wrap_display(copy.title, max_width, px, max_lines=2)
        while lines and max(B.measure(l, B.BANGERS, px, 0.04)[0] for l in lines) > max_width and px > 40:
            px -= 3
            lines = B.wrap_display(copy.title, max_width, px, max_lines=2)

    for i, line in enumerate(lines):
        w, _ = B.measure(line, B.BANGERS, px, 0.04)
        h = B.display_text(img, line, px, (cv.w - w) // 2, y, stops=B.WARM,
                           tracking_em=0.04, glow=(255, 96, 30))[1]
        y += h + int(px * 0.10)
    return y + int(cv.h * 0.006)


def _fact_block(img, cv, copy, y):
    """Date, then place, then the quiet detail line. Three sizes, one rhythm."""
    date_px = int(cv.w * 0.052)
    B.flat_text(img, copy.date_line, B.INTER_XB, date_px, cv.w // 2, y,
                colour=B.WHITE, alpha=B.A_TEXT, tracking_em=0.05, anchor="c")
    y += int(date_px * B.CAP_INTER) + int(cv.h * 0.019)

    if copy.place_line:
        place_px = int(cv.w * 0.040)
        B.flat_text(img, copy.place_line, B.INTER_B, place_px, cv.w // 2, y,
                    colour=B.WHITE, alpha=B.A_MUTED, tracking_em=0.06, anchor="c")
        y += int(place_px * B.CAP_INTER) + int(cv.h * 0.013)

    if copy.detail_line:
        det_px = int(cv.w * 0.028)
        for line in B.wrap_flat(copy.detail_line, B.INTER, det_px,
                                int(cv.w - cv.safe_x * 2), max_lines=2):
            B.flat_text(img, line, B.INTER, det_px, cv.w // 2, y,
                        colour=B.WHITE, alpha=B.A_DIM, anchor="c")
            y += int(det_px * B.CAP_INTER) + int(cv.h * 0.009)
    return y


# ── Template: banner ─────────────────────────────────────────────────────────
def render_banner(ev: dict, kind: str, cv: B.Canvas = B.FEED_45,
                  booth: str | None = None) -> Image.Image:
    """Type-led. One centred column of information, mascot holding the corner.

    The layout is a single top-down column — eyebrow, name, rule, date, place,
    detail, CTA — and then the mascot occupies the lower right, bleeding a little
    past the safe margin so it reads as artwork rather than a pasted sticker. Its
    base sits behind the footer hairline, which is where the source artwork's
    straight bottom cut becomes invisible instead of becoming a problem.
    """
    copy = build_copy(ev, kind, booth)
    img = B.base_canvas(cv, warm_corner="tl")

    content_w = cv.w - cv.safe_x * 2
    top = cv.safe_top + int(cv.h * 0.072)
    footer_y = cv.h - cv.safe_bottom - int(cv.h * 0.012)
    rule_y = footer_y - int(cv.h * 0.062)

    # Mascot first: everything else is positioned to clear it. It bleeds past
    # both the right and bottom edges so the artwork's straight bottom cut ends
    # up off-canvas, and the scrim below covers whatever is left of it.
    mascot_h = int(cv.h * (0.50 if cv is B.FEED_45 else 0.46 if cv is B.FEED_11 else 0.38))
    B.place_mascot(img, mascot_h,
                   right=cv.w + int(cv.w * 0.17),
                   bottom=cv.h + int(cv.h * 0.045))
    B.bottom_scrim(img, int(cv.h * 0.185))

    y = _eyebrow(img, cv, copy, top)
    y = _title_block(img, cv, copy, y, content_w,
                     start_px=int(cv.w * 0.115), min_px=int(cv.w * 0.052))
    y += int(cv.h * 0.010)
    B.rule(img, cv.w // 2 - int(cv.w * 0.075), y, cv.w // 2 + int(cv.w * 0.075))
    y += int(cv.h * 0.026)
    y = _fact_block(img, cv, copy, y)

    # The CTA sits directly under the facts, not floating at the bottom — it is
    # the last line of the same sentence, not a separate banner.
    B.pill(img, copy.cta, int(cv.w * 0.026), cv.w // 2, y + int(cv.h * 0.016))

    B.sparks(img, seed=abs(hash(ev["event_date"])) % 9973, count=9,
             avoid=[(cv.safe_x - 24, top - 24, cv.w - cv.safe_x + 24, y + int(cv.h * 0.07)),
                    (int(cv.w * 0.42), rule_y - mascot_h, cv.w, rule_y)])

    B.rule(img, cv.safe_x, rule_y, cv.w - cv.safe_x, colour=B.WHITE, alpha=30, thickness=1)
    B.footer(img, cv, footer_y)
    return B.finish(img)


def _footer_band(img, cv, copy, band_top, footer_y):
    """CTA chip above the contact lockup, with a hairline separating them."""
    chip_px = int(cv.w * 0.026)
    B.pill(img, copy.cta, chip_px, cv.w // 2, band_top - int(cv.h * 0.052))
    B.rule(img, cv.safe_x, band_top + int(cv.h * 0.006), cv.w - cv.safe_x,
           colour=B.WHITE, alpha=26, thickness=1)
    B.footer(img, cv, footer_y)


# ── Template: flyer ──────────────────────────────────────────────────────────
def render_flyer(ev: dict, kind: str, flyer: Image.Image, cv: B.Canvas = B.FEED_45,
                 booth: str | None = None) -> Image.Image:
    """The organizer's artwork as the hero, whole and uncropped.

    Their flyer is usually portrait or square and almost never our aspect ratio.
    The temptation is to crop it to fill — which reliably cuts off the date or
    the venue, the two things the flyer exists to say. So it is fitted whole
    inside a card, and the gap around it is filled with a heavily blurred,
    darkened copy of the flyer itself: the frame picks up the artwork's own
    colours instead of introducing ours.
    """
    copy = build_copy(ev, kind, booth)
    img = B.base_canvas(cv, warm_corner="tl")

    card_x = cv.safe_x
    card_w = cv.w - cv.safe_x * 2
    card_top = cv.safe_top + int(cv.h * 0.075)
    band_h = int(cv.h * 0.30 if cv is B.FEED_45 else cv.h * 0.32)
    card_h = cv.h - card_top - band_h - cv.safe_bottom

    B.flat_text(img, copy.eyebrow, B.INTER_XB, int(cv.w * 0.026), cv.w // 2,
                cv.safe_top + int(cv.h * 0.022), colour=B.GOLD, alpha=225,
                tracking_em=0.20, anchor="c")

    card = _fit_into(flyer, card_w, card_h)
    radius = int(cv.w * 0.026)

    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(
        [card_x - 6, card_top - 6, card_x + card_w + 6, card_top + card_h + 6],
        radius + 6, fill=B.ORANGE + (110,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(int(cv.w * 0.024))))

    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius, fill=255)
    img.paste(card.convert("RGB"), (card_x, card_top), mask)

    ImageDraw.Draw(img, "RGBA").rounded_rectangle(
        [card_x, card_top, card_x + card_w - 1, card_top + card_h - 1],
        radius, outline=B.GOLD + (150), width=max(2, cv.w // 420))

    y = card_top + card_h + int(cv.h * 0.030)
    y = _title_block(img, cv, copy, y, card_w,
                     start_px=int(cv.w * 0.078), min_px=int(cv.w * 0.040))
    y += int(cv.h * 0.008)
    _fact_block(img, cv, copy, y)

    footer_y = cv.h - cv.safe_bottom - int(cv.h * 0.010)
    B.footer(img, cv, footer_y)
    return B.finish(img)


def _fit_into(src: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """Whole image inside the box; gaps filled from a blurred copy of itself."""
    src = src.convert("RGB")
    scale = min(box_w / src.width, box_h / src.height)
    fitted = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))),
                        Image.LANCZOS)

    cover = min(box_w / src.width, box_h / src.height)
    cover = max(box_w / src.width, box_h / src.height)
    bg = src.resize((max(1, int(src.width * cover)), max(1, int(src.height * cover))),
                    Image.LANCZOS)
    bx = (bg.width - box_w) // 2
    by = (bg.height - box_h) // 2
    bg = bg.crop((bx, by, bx + box_w, by + box_h)).filter(ImageFilter.GaussianBlur(box_w * 0.05))
    bg = Image.blend(bg, Image.new("RGB", bg.size, B.INK), 0.42)

    bg.paste(fitted, ((box_w - fitted.width) // 2, (box_h - fitted.height) // 2))
    return bg


# ── Template: photo ──────────────────────────────────────────────────────────
def render_photo(ev: dict, kind: str, photo: Image.Image, cv: B.Canvas = B.FEED_45,
                 booth: str | None = None) -> Image.Image:
    """A booth photo as the hero, with a scrim so the type stays readable."""
    copy = build_copy(ev, kind, booth)
    img = B.base_canvas(cv, warm_corner="tl")

    card_x, card_w = cv.safe_x, cv.w - cv.safe_x * 2
    card_top = cv.safe_top + int(cv.h * 0.070)
    card_h = int(cv.h * 0.46)
    radius = int(cv.w * 0.026)

    hero = _cover(photo, card_w, card_h)
    scrim = Image.new("L", (card_w, card_h), 0)
    sd = ImageDraw.Draw(scrim)
    fade = int(card_h * 0.42)
    for yy in range(card_h):
        a = 0 if yy < card_h - fade else int(232 * ((yy - (card_h - fade)) / fade) ** 1.4)
        sd.line([(0, yy), (card_w, yy)], fill=a)
    hero = Image.composite(Image.new("RGB", hero.size, B.INK), hero, scrim)

    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius, fill=255)
    img.paste(hero, (card_x, card_top), mask)
    ImageDraw.Draw(img, "RGBA").rounded_rectangle(
        [card_x, card_top, card_x + card_w - 1, card_top + card_h - 1],
        radius, outline=B.ORANGE + (200,), width=max(2, cv.w // 420))

    B.flat_text(img, copy.eyebrow, B.INTER_XB, int(cv.w * 0.026), cv.w // 2,
                cv.safe_top + int(cv.h * 0.020), colour=B.GOLD, alpha=225,
                tracking_em=0.20, anchor="c")

    y = card_top + card_h + int(cv.h * 0.034)
    y = _title_block(img, cv, copy, y, card_w,
                     start_px=int(cv.w * 0.086), min_px=int(cv.w * 0.044))
    y += int(cv.h * 0.010)
    _fact_block(img, cv, copy, y)

    footer_y = cv.h - cv.safe_bottom - int(cv.h * 0.010)
    B.pill(img, copy.cta, int(cv.w * 0.025), cv.w // 2, footer_y - int(cv.h * 0.098))
    B.footer(img, cv, footer_y)
    return B.finish(img)


def _cover(src: Image.Image, box_w: int, box_h: int) -> Image.Image:
    src = src.convert("RGB")
    scale = max(box_w / src.width, box_h / src.height)
    im = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))), Image.LANCZOS)
    # Bias the crop downward: booth photos put the table and the people in the
    # lower two-thirds, and a centre crop reliably frames the ceiling.
    x = (im.width - box_w) // 2
    y = int((im.height - box_h) * 0.42)
    return im.crop((x, y, x + box_w, y + box_h))


TEMPLATES = {"banner": render_banner, "flyer": render_flyer, "photo": render_photo}
