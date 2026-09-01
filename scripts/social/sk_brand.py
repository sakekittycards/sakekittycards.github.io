# -*- coding: utf-8 -*-
"""Sake Kitty Cards design system — the single source of brand truth for every
generated social asset.

Before this module the brand lived in four places that disagreed: `style.css`
(:root tokens), `gen_og.py` / `gen_cover.py` (hardcoded `#7b2fff` violet),
`scripts/_make_ig_*.py` (a third set of literals), and the booth-banner build
scripts (the only ones that were actually measured). This file is the merge, and
the banner's numbers win, because they were derived rather than invented.

## The palette is sampled from the mascot, never chosen

`logo-transparent-print.png` was quantised over its opaque, saturated pixels:

    gold    #f2b905   8% of all pixels — the OUTLINE colour of the illustration
    orange  #f04800   the dominant mass, a burnt vermillion
    magenta #d81860
    cobalt  #0060c0   a true blue
    azure   #0090d8

Cyan (`#22c8ff`) and violet (`#7b2fff`) occur NOWHERE in the artwork. Both were
in the old generators, and they are what made that output read as a generic neon
rainbow bolted onto the cat. They are deliberately absent here. Gold is the
under-used accent — reach for it before inventing a hue.

## Rules encoded here, not left to the caller

- Glows are built at FULL CANVAS SIZE. A blur inside a layer sized to its own
  content clips at the layer bounds and prints a hard rectangle — that bug shipped
  once and was blamed on the asset.
- No text stroke on display type. On black a grey keyline reads as a Photoshop
  default and cheapens the type; the gradient carries its own edge.
- The mascot is a LOCKED asset: composited as supplied, cropped and resized only,
  never redrawn. Its artwork ends in a straight horizontal cut (the wordmark used
  to cover the lower body) — position it so the cut lands behind another element
  rather than "fixing" it.
- PIL has no letter-spacing. `text_mask()` draws glyph by glyph with a manual
  advance; every tracking value in this file is in em units of the font size.

Cap-height ratios (Bangers 0.721, Inter 0.727) were measured off the rendered
glyphs, and are what let two different faces sit on one optical baseline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
FONT_DIR = os.path.join(HERE, "fonts")

# ── Fonts ────────────────────────────────────────────────────────────────────
# Vendored into the repo rather than resolved from C:/Windows/Fonts or a sibling
# project, so a render is reproducible on any machine and in CI. Segoe UI (which
# the old _make_ig_* scripts used) is a Windows system font and is NOT the site's
# body face — the site is Bangers + Inter, so the graphics are too.
BANGERS = os.path.join(FONT_DIR, "Bangers-Regular.ttf")
INTER = os.path.join(FONT_DIR, "Inter-Regular.ttf")
INTER_SB = os.path.join(FONT_DIR, "Inter-SemiBold.ttf")
INTER_B = os.path.join(FONT_DIR, "Inter-Bold.ttf")
INTER_XB = os.path.join(FONT_DIR, "Inter-ExtraBold.ttf")

CAP_BANGERS = 0.721   # cap height as a fraction of nominal size, measured
CAP_INTER = 0.727

# ── Brand assets ─────────────────────────────────────────────────────────────
MASCOT = os.path.join(REPO, "logo-transparent-print.png")   # 3072x3072 RGBA, THE asset
LOGO_SQUARE = os.path.join(REPO, "logo.png")                # 1024x1024 RGB, opaque

# The mascot art sits above the wordmark in the source lockup; 0.67 is the
# measured minimum-coverage gap row between the two.
MASCOT_ART_FRACTION = 0.67

# ── Palette ──────────────────────────────────────────────────────────────────
GOLD = (242, 185, 5)
ORANGE = (240, 72, 0)
MAGENTA = (216, 24, 96)
COBALT = (0, 96, 192)
AZURE = (0, 144, 216)
INK = (6, 6, 10)          # the site's --bg, near-black
WHITE = (255, 255, 255)

# Gradient ramps. WARM is the primary (name, headlines); COOL is the secondary
# (the second line of a lockup, so a two-line title reads as one system).
WARM: Sequence[tuple[float, tuple[int, int, int]]] = (
    (0.00, (255, 207, 58)),
    (0.38, (255, 90, 16)),
    (1.00, (224, 36, 110)),
)
COOL: Sequence[tuple[float, tuple[int, int, int]]] = (
    (0.00, (127, 228, 255)),
    (0.45, (31, 178, 240)),
    (1.00, (42, 99, 224)),
)

# Body-copy alphas, carried over from the site's locked contrast baseline
# (--muted .85 / --dim .65). Nick reads this on a phone in direct sunlight at
# outdoor shows; do not lower them.
A_TEXT = 255
A_MUTED = 217   # .85
A_DIM = 166     # .65


# ── Canvas sizes ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Canvas:
    """A target surface. `safe_*` are the margins Instagram's own chrome eats.

    Feed posts lose almost nothing. Stories/Reels lose the top status area and a
    large bottom band to the caption, handle, audio strip and action rail — about
    250px top / 420px bottom on a 1920-tall frame. Nothing that must be read goes
    there.
    """
    key: str
    w: int
    h: int
    safe_top: int
    safe_bottom: int
    safe_x: int


FEED_45 = Canvas("feed_4x5", 1080, 1350, 48, 48, 64)
FEED_11 = Canvas("feed_1x1", 1080, 1080, 48, 48, 64)
STORY_916 = Canvas("story_9x16", 1080, 1920, 250, 420, 72)

CANVASES = {c.key: c for c in (FEED_45, FEED_11, STORY_916)}


# ── Primitives ───────────────────────────────────────────────────────────────
@lru_cache(maxsize=64)
def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def ramp(height: int, stops: Sequence[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    """A vertical colour ramp as an (h, 3) float array."""
    ys = np.arange(height) / max(height - 1, 1)
    out = np.zeros((height, 3), np.float32)
    for c in range(3):
        out[:, c] = np.interp(ys, [s[0] for s in stops], [s[1][c] for s in stops])
    return out


def text_mask(txt: str, fnt: ImageFont.FreeTypeFont, tracking: float = 0.0) -> Image.Image:
    """Render `txt` to an L mask, drawing glyph by glyph so tracking works.

    Pillow has no letter-spacing, and `ImageDraw.text` on the whole string gives
    you the font's own advances. Returns the mask cropped to its ink bbox, so the
    caller positions ink, not a line box — which is what makes optical alignment
    across two typefaces possible.
    """
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    advances = [probe.textlength(ch, font=fnt) for ch in txt]
    total = sum(advances) + tracking * max(len(txt) - 1, 0)
    ascent, descent = fnt.getmetrics()
    pad = int(max(fnt.size * 0.4, 8))
    m = Image.new("L", (int(total) + pad * 2, ascent + descent + pad * 2), 0)
    d = ImageDraw.Draw(m)
    x = float(pad)
    for ch, adv in zip(txt, advances):
        d.text((x, pad), ch, font=fnt, fill=255)
        x += adv + tracking
    box = m.getbbox()
    return m.crop(box) if box else m


def measure(txt: str, font_path: str, px: int, tracking_em: float = 0.0) -> tuple[int, int]:
    """Ink size of a string without drawing it. Used by the fitters."""
    m = text_mask(txt, font(font_path, px), tracking_em * px)
    return m.size


def display_text(
    canvas: Image.Image,
    txt: str,
    px: int,
    left: int,
    ink_top: int,
    stops: Sequence[tuple[float, tuple[int, int, int]]] = WARM,
    tracking_em: float = 0.06,
    glow: tuple[int, int, int] | None = (255, 78, 40),
    glow_strength: float = 0.38,
) -> tuple[int, int]:
    """Bangers display type with a gradient fill and one soft colour glow.

    No outline, by policy. The glow layer is built at the mask's size plus a full
    `px` of bleed on every side so the blur has room to fall off instead of
    clipping to a rectangle.
    """
    f = font(BANGERS, px)
    m = text_mask(txt, f, tracking_em * px)
    w, h = m.size

    if glow is not None:
        pad = px
        g = Image.new("L", (w + pad, h + pad), 0)
        g.paste(m, (pad // 2, pad // 2))
        layer = Image.new("RGBA", g.size, glow + (0,))
        layer.putalpha(
            g.filter(ImageFilter.GaussianBlur(px * 0.055)).point(lambda v: int(v * glow_strength))
        )
        canvas.alpha_composite(layer, (left - pad // 2, ink_top - pad // 2))

    col = ramp(h, stops)
    fill = Image.fromarray(
        np.repeat(col[:, None, :], w, axis=1).astype(np.uint8), "RGB"
    ).convert("RGBA")
    fill.putalpha(m)
    canvas.alpha_composite(fill, (left, ink_top))
    return w, h


def flat_text(
    canvas: Image.Image,
    txt: str,
    font_path: str,
    px: int,
    left: int,
    ink_top: int,
    colour: tuple[int, int, int] = WHITE,
    alpha: int = A_TEXT,
    tracking_em: float = 0.0,
    anchor: str = "l",
) -> tuple[int, int]:
    """Single-colour Inter type. `anchor` is 'l', 'r' or 'c' on the x axis."""
    f = font(font_path, px)
    m = text_mask(txt, f, tracking_em * px)
    w, h = m.size
    x = {"l": left, "r": left - w, "c": left - w // 2}[anchor]
    layer = Image.new("RGBA", (w, h), colour + (0,))
    layer.putalpha(m.point(lambda v: int(v * alpha / 255)))
    canvas.alpha_composite(layer, (x, ink_top))
    return w, h


def fit_display(
    txt: str,
    max_width: int,
    start_px: int,
    min_px: int,
    tracking_em: float = 0.06,
) -> int:
    """Largest Bangers size at or below `start_px` whose ink fits `max_width`.

    Event names run from "Pokekon" to "Collect-A-Con — San Francisco"; a fixed
    size either wastes the short ones or overflows the long ones.
    """
    px = start_px
    while px > min_px:
        if measure(txt, BANGERS, px, tracking_em)[0] <= max_width:
            return px
        px -= 2
    return min_px


def wrap_display(txt: str, max_width: int, px: int, tracking_em: float = 0.06,
                 max_lines: int = 2) -> list[str]:
    """Greedy word wrap for Bangers at a known size."""
    words = txt.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and measure(trial, BANGERS, px, tracking_em)[0] > max_width:
            lines.append(cur)
            cur = word
            if len(lines) == max_lines - 1 and words.index(word) < len(words) - 1:
                pass
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def wrap_flat(txt: str, font_path: str, px: int, max_width: int,
              tracking_em: float = 0.0, max_lines: int = 3) -> list[str]:
    words = txt.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and measure(trial, font_path, px, tracking_em)[0] > max_width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines[:max_lines]


# ── Backgrounds ──────────────────────────────────────────────────────────────
def glow(canvas: Image.Image, cx: int, cy: int, radius: int,
         colour: tuple[int, int, int], alpha: int) -> None:
    """A soft radial wash, built at canvas size.

    The size matters: blurring a layer that is only as big as the ellipse clips
    the falloff at the layer edge and paints a visible box. Always full canvas.
    """
    w, h = canvas.size
    g = Image.new("L", (w, h), 0)
    ImageDraw.Draw(g).ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=alpha)
    g = g.filter(ImageFilter.GaussianBlur(radius * 0.5))
    layer = Image.new("RGBA", (w, h), colour + (0,))
    layer.putalpha(g)
    canvas.alpha_composite(layer)


def base_canvas(cv: Canvas, warm_corner: str = "tl") -> Image.Image:
    """The Sake Kitty ground: near-black, two brand washes, a gold breath, vignette.

    Two washes, not four. The old generators stacked orange + pink + violet +
    cyan and the result was mud with no focal point. A warm mass anchors one
    corner, cobalt answers on the diagonal, a small gold breath at centre ties
    both to the mascot's outline colour, and a vignette pulls the corners down so
    the type column is the brightest thing on the canvas.
    """
    img = Image.new("RGBA", (cv.w, cv.h), INK + (255,))
    if warm_corner == "tl":
        wx, wy = int(cv.w * 0.10), int(cv.h * 0.06)
        cx2, cy2 = int(cv.w * 0.90), int(cv.h * 0.94)
    else:
        wx, wy = int(cv.w * 0.90), int(cv.h * 0.94)
        cx2, cy2 = int(cv.w * 0.10), int(cv.h * 0.06)
    r = int(max(cv.w, cv.h) * 0.46)
    glow(img, wx, wy, r, ORANGE, 130)
    glow(img, int(wx + r * 0.30), int(wy + r * 0.55), int(r * 0.66), MAGENTA, 92)
    glow(img, cx2, cy2, int(r * 1.02), COBALT, 104)
    glow(img, int(cx2 * 0.86), int(cy2 * 0.92), int(r * 0.52), AZURE, 54)
    glow(img, cv.w // 2, int(cv.h * 0.30), int(r * 0.80), GOLD, 22)
    _vignette(img, 0.55)
    return img


def _vignette(img: Image.Image, strength: float = 0.5) -> None:
    """Darken the corners. Cheap, and it is what stops a two-wash ground reading
    as a flat brown wash at thumbnail size."""
    w, h = img.size
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse(
        [-int(w * 0.22), -int(h * 0.18), int(w * 1.22), int(h * 1.18)], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(min(w, h) * 0.16))
    dark = Image.new("RGBA", (w, h), INK + (0,))
    dark.putalpha(m.point(lambda v: int((255 - v) * strength)))
    img.alpha_composite(dark)


def sparks(img: Image.Image, seed: int = 7, count: int = 14,
           avoid: Iterable[tuple[int, int, int, int]] = ()) -> None:
    """A handful of out-of-focus brand dots in the dark margins.

    Deterministic per `seed` so the same event always renders identically — a
    re-render must be byte-comparable, otherwise "did the graphic change?" is
    unanswerable. `avoid` rectangles keep them out of the content column.
    """
    import random

    rng = random.Random(seed)
    w, h = img.size
    boxes = list(avoid)
    placed = 0
    tries = 0
    while placed < count and tries < count * 40:
        tries += 1
        x = rng.randint(24, w - 24)
        y = rng.randint(24, h - 24)
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in boxes):
            continue
        rad = rng.choice([3, 4, 4, 5, 6])
        colour = rng.choice([GOLD, ORANGE, MAGENTA, AZURE])
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse([x - rad, y - rad, x + rad, y + rad],
                                      fill=colour + (rng.randint(150, 235),))
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(rad * 0.55)))
        placed += 1


# ── Mascot ───────────────────────────────────────────────────────────────────
@lru_cache(maxsize=4)
def mascot_art() -> Image.Image:
    """The cat, cropped out of the lockup and trimmed to its own ink.

    Composited as supplied — cropped and resized only. Never redrawn, recoloured
    or regenerated.
    """
    src = Image.open(MASCOT).convert("RGBA")
    w, h = src.size
    art = src.crop((0, 0, w, int(h * MASCOT_ART_FRACTION)))
    box = art.getbbox()
    return art.crop(box) if box else art


def place_mascot(canvas: Image.Image, height: int, right: int, bottom: int,
                 halo: bool = True) -> tuple[int, int]:
    """Drop the mascot with its right edge at `right` and base at `bottom`.

    Bottom-anchored on purpose: the source artwork ends in a straight horizontal
    cut, so the base must sit behind another element or off the safe area rather
    than floating in open space.
    """
    art = mascot_art()
    scale = height / art.height
    art = art.resize((max(1, int(art.width * scale)), height), Image.LANCZOS)
    x, y = right - art.width, bottom - art.height
    if halo:
        # Built at canvas size — see the note on glow().
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.paste(art, (x, y), art)
        a = layer.getchannel("A").filter(ImageFilter.GaussianBlur(height * 0.07))
        h_layer = Image.new("RGBA", canvas.size, ORANGE + (0,))
        h_layer.putalpha(a.point(lambda v: int(v * 0.34)))
        canvas.alpha_composite(h_layer)
    canvas.alpha_composite(art, (x, y))
    return art.size


def bottom_scrim(canvas: Image.Image, height: int, strength: int = 255) -> None:
    """Fade the bottom of the canvas to ink.

    This is what lets the mascot bleed off the bottom edge. The source artwork
    ends in a straight horizontal cut where the wordmark used to cover the cat's
    lower body; the fix is never to paint the cut out, it is to put something in
    front of it. Bleeding the art past the edge and fading into the ground does
    that, and leaves a clean field for the footer lockup.
    """
    w, h = canvas.size
    grad = Image.new("L", (1, height))
    px = grad.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        px[0, y] = int(strength * (t ** 1.55))
    layer = Image.new("RGBA", (w, height), INK + (0,))
    layer.putalpha(grad.resize((w, height)))
    canvas.alpha_composite(layer, (0, h - height))


# ── Chrome ───────────────────────────────────────────────────────────────────
def instagram_glyph(size: int, colour: tuple[int, int, int] = WHITE,
                    alpha: int = A_MUTED) -> Image.Image:
    """The IG mark, drawn rather than shipped as an asset file."""
    ic = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(ic)
    stroke = max(2, size // 13)
    o = int(size * 0.06)
    fill = colour + (alpha,)
    d.rounded_rectangle([o, o, size - o, size - o], int(size * 0.26), outline=fill, width=stroke)
    c, r = size / 2, size * 0.21
    d.ellipse([c - r, c - r, c + r, c + r], outline=fill, width=stroke)
    dr = size * 0.05
    d.ellipse([size * 0.74 - dr, size * 0.26 - dr, size * 0.74 + dr, size * 0.26 + dr], fill=fill)
    return ic


def footer(canvas: Image.Image, cv: Canvas, baseline: int) -> None:
    """The contact lockup: one information system, url then handle.

    The handle keeps the url's baseline and steps down one weight, not into a
    different treatment — that was the fix that made the banner's footer read as
    a unit instead of two decisions.
    """
    url_px = int(cv.w * 0.045)
    handle_px = int(cv.w * 0.037)
    cap_u = int(url_px * CAP_INTER)
    cap_h = int(handle_px * CAP_INTER)

    url_w, _ = measure("sakekittycards.com", INTER_XB, url_px)
    gap = int(cv.w * 0.045)
    glyph = int(cv.w * 0.035)
    handle_w, _ = measure("@sakekittycards", INTER_B, handle_px)
    total = url_w + gap + glyph + int(cv.w * 0.014) + handle_w
    x = (cv.w - total) // 2

    flat_text(canvas, "sakekittycards.com", INTER_XB, url_px, x, baseline - cap_u)
    x += url_w + gap
    ic = instagram_glyph(glyph)
    canvas.alpha_composite(ic, (x, baseline - cap_h - (glyph - cap_h) // 2))
    x += glyph + int(cv.w * 0.014)
    flat_text(canvas, "@sakekittycards", INTER_B, handle_px, x, baseline - cap_h,
              alpha=A_MUTED)


def rule(canvas: Image.Image, x0: int, y: int, x1: int,
         colour: tuple[int, int, int] = GOLD, alpha: int = 120, thickness: int = 2) -> None:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle([x0, y, x1, y + thickness - 1], fill=colour + (alpha,))
    canvas.alpha_composite(layer)


def pill(canvas: Image.Image, txt: str, px: int, cx: int, top: int,
         colour: tuple[int, int, int] = GOLD) -> tuple[int, int]:
    """A small outlined chip — used for the eyebrow / booth number."""
    f_w, f_h = measure(txt, INTER_XB, px, 0.12)
    pad_x, pad_y = int(px * 0.9), int(px * 0.62)
    w, h = f_w + pad_x * 2, f_h + pad_y * 2
    x = cx - w // 2
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [x, top, x + w, top + h], h // 2, fill=colour + (30,), outline=colour + (170,), width=2
    )
    canvas.alpha_composite(layer)
    flat_text(canvas, txt, INTER_XB, px, x + pad_x, top + pad_y, colour=colour,
              alpha=235, tracking_em=0.12)
    return w, h


def finish(canvas: Image.Image) -> Image.Image:
    """Flatten to RGB on the brand ink. JPEG/IG has no alpha; be explicit."""
    out = Image.new("RGB", canvas.size, INK)
    out.paste(canvas, (0, 0), canvas)
    return out
