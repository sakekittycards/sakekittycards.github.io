"""
Prototype graded-card image pipeline.

Takes a photo of a graded slab (front or back), auto-crops it from the
background, and composites it onto a Sake Kitty branded backdrop
(dark navy + lava-lamp blobs in orange/pink/purple/cyan).

Pure Pillow + numpy — no rembg, no OpenCV. The crop relies on the
slab being on a roughly uniform light background. For phone photos
on a busy surface, swap the crop step for rembg.

Usage:
    python process_card.py <input> [<input2> ...] --out <dir>
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_PATH = Path(__file__).parent / "fonts" / "Bangers-Regular.ttf"
LOGO_PATH = Path(__file__).parent.parent.parent / "logo-transparent.png"

# Sake Kitty palette — pulled from main.js particle COLORS + hero blobs.
NAVY = (10, 10, 20)
ORANGE = (255, 106, 0)
PINK = (255, 0, 128)
PURPLE = (123, 47, 255)
CYAN = (0, 212, 255)
GOLD = (255, 204, 0)


# ---------- crop ---------------------------------------------------------- #

def find_slab_bbox(img: Image.Image, bg_threshold: int = 210, pad: int = 24):
    """
    Locate the slab's bounding box on a near-uniform light background.

    Strategy: convert to grayscale, classify each pixel as background
    if it's brighter than `bg_threshold`, find the bounding box of the
    non-background mask, then dilate by `pad` pixels.
    """
    gray = np.asarray(img.convert("L"))
    fg = gray < bg_threshold

    # Drop tiny speckles by requiring at least a few foreground pixels per row/col.
    col_has_fg = fg.sum(axis=0) > (fg.shape[0] * 0.02)
    row_has_fg = fg.sum(axis=1) > (fg.shape[1] * 0.02)

    if not col_has_fg.any() or not row_has_fg.any():
        return None

    xs = np.where(col_has_fg)[0]
    ys = np.where(row_has_fg)[0]
    x0, x1 = int(xs[0]), int(xs[-1])
    y0, y1 = int(ys[0]), int(ys[-1])

    h, w = gray.shape
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)
    return x0, y0, x1, y1


def crop_slab(img: Image.Image) -> Image.Image:
    bbox = find_slab_bbox(img)
    if bbox is None:
        return img
    return img.crop(bbox)


# ---------- backdrop ------------------------------------------------------ #

def radial_blob(size: tuple[int, int], center: tuple[float, float],
                radius: float, color: tuple[int, int, int],
                strength: float = 1.0) -> Image.Image:
    """
    A soft-edged colored blob for the lava-lamp feel.
    Returns an RGBA image we can composite onto the backdrop.
    """
    w, h = size
    cx, cy = center
    y, x = np.ogrid[0:h, 0:w]
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    # Smoothstep falloff — bright at center, fades to 0 at radius.
    t = np.clip(1.0 - dist / radius, 0.0, 1.0)
    alpha = (t ** 1.6) * 255 * strength

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = color[0]
    rgba[..., 1] = color[1]
    rgba[..., 2] = color[2]
    rgba[..., 3] = alpha.astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def aurora_band(size: tuple[int, int], y_frac: float, height_frac: float,
                color: tuple[int, int, int], strength: float = 0.6,
                angle: float = 0.0) -> Image.Image:
    """
    A wide, soft, diagonal band of color — aurora-style.

    Drawn as a horizontal blurred rectangle, then rotated by `angle` degrees
    around the canvas center. Returns RGBA matching `size`.
    """
    w, h = size
    # Oversized so rotation doesn't expose corners.
    big = max(w, h) * 2
    band = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    cy = big / 2 + (y_frac - 0.5) * h
    bh = h * height_frac
    bd.rectangle(
        (0, cy - bh / 2, big, cy + bh / 2),
        fill=(*color, int(255 * strength)),
    )
    band = band.filter(ImageFilter.GaussianBlur(radius=bh * 0.55))
    band = band.rotate(angle, resample=Image.BICUBIC)
    # Crop back to canvas size, centered.
    left = (big - w) // 2
    top = (big - h) // 2
    return band.crop((left, top, left + w, top + h))


def sparkle_field(size: tuple[int, int], count: int = 90,
                  seed: int = 7) -> Image.Image:
    """
    Scatter tiny colored dots (orange/pink/purple/cyan/white/gold) across
    the canvas — same palette as the home-page particle system. Adds
    texture without overpowering.
    """
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    rng = np.random.default_rng(seed)
    palette = [ORANGE, PINK, PURPLE, CYAN, GOLD, (255, 255, 255)]
    for _ in range(count):
        x = rng.integers(0, w)
        y = rng.integers(0, h)
        r = rng.integers(2, 6)
        color = palette[rng.integers(0, len(palette))]
        alpha = int(rng.integers(120, 230))
        ld.ellipse((x - r, y - r, x + r, y + r), fill=(*color, alpha))
    # Light blur so they read as glowing pinpricks, not crisp dots.
    return layer.filter(ImageFilter.GaussianBlur(radius=1.6))


def make_backdrop(size: tuple[int, int]) -> Image.Image:
    """
    Sake Kitty branded backdrop:
      navy base + diagonal aurora ribbons + sparkle field + vignette.
    Designed so a centered slab + slab-aura sit on top cleanly.
    """
    w, h = size
    bg = Image.new("RGB", size, NAVY)

    # A faint deep-purple wash to soften the pure navy.
    wash = radial_blob(size, (w / 2, h / 2), max(w, h) * 0.7,
                       (40, 20, 70), strength=0.55)
    bg.paste(wash, (0, 0), wash)

    # Diagonal aurora ribbons — wide, blurred, varying angles.
    ribbons = [
        # (y_frac,  height_frac, color,  strength, angle)
        (0.18,      0.30,        ORANGE, 0.55,     -22),
        (0.42,      0.22,        PINK,   0.45,     -18),
        (0.68,      0.30,        PURPLE, 0.60,     -25),
        (0.88,      0.22,        CYAN,   0.40,     -20),
    ]
    for y_frac, height_frac, color, strength, angle in ribbons:
        band = aurora_band(size, y_frac, height_frac, color, strength, angle)
        bg.paste(band, (0, 0), band)

    # Light blur to bind the ribbons into a smooth glow field.
    bg = bg.filter(ImageFilter.GaussianBlur(radius=max(w, h) * 0.018))

    # Vignette — darken the corners so the centered slab pops.
    vignette = Image.new("L", size, 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse(
        (-w * 0.15, -h * 0.15, w * 1.15, h * 1.15),
        fill=255,
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=max(w, h) * 0.10))
    dark = Image.new("RGB", size, NAVY)
    bg = Image.composite(bg, dark, vignette)

    # Sparkle field on top of the ribbons.
    sparkles = sparkle_field(size, count=110)
    bg.paste(sparkles, (0, 0), sparkles)

    # Light film grain — keeps the gradient from looking too plastic.
    rng = np.random.default_rng(42)
    grain = rng.normal(0, 4, (h, w, 3)).astype(np.int16)
    arr = np.asarray(bg, dtype=np.int16) + grain
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def _rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    """Vectorized RGB(0-255) -> HSV(H 0-360, S 0-1, V 0-1)."""
    rgb = rgb.astype(np.float32) / 255.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(axis=-1)
    mn = rgb.min(axis=-1)
    diff = mx - mn

    h = np.zeros_like(mx)
    mask = diff > 1e-6
    rmax = mask & (mx == r)
    gmax = mask & (mx == g) & ~rmax
    bmax = mask & (mx == b) & ~rmax & ~gmax
    h[rmax] = (60 * ((g[rmax] - b[rmax]) / diff[rmax]) + 360) % 360
    h[gmax] = 60 * ((b[gmax] - r[gmax]) / diff[gmax]) + 120
    h[bmax] = 60 * ((r[bmax] - g[bmax]) / diff[bmax]) + 240

    s = np.where(mx > 1e-6, diff / mx, 0)
    v = mx
    return np.stack([h, s, v], axis=-1)


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """HSV(H 0-360, S 0-1, V 0-1) -> RGB(0-255)."""
    c = v * s
    h_ = (h % 360) / 60
    x = c * (1 - abs(h_ % 2 - 1))
    if   h_ < 1: r, g, b = c, x, 0
    elif h_ < 2: r, g, b = x, c, 0
    elif h_ < 3: r, g, b = 0, c, x
    elif h_ < 4: r, g, b = 0, x, c
    elif h_ < 5: r, g, b = x, 0, c
    else:        r, g, b = c, 0, x
    m = v - c
    return tuple(int(round((ch + m) * 255)) for ch in (r, g, b))


def extract_palette(img: Image.Image, n: int = 3) -> list[tuple[int, int, int]]:
    """
    Pick the N most prominent vibrant colors from the slab image.

    Approach: downsample, convert to HSV, drop low-saturation pixels
    (gray plastic, white labels, black borders), bucket by hue (24 bins),
    pick the top buckets by weighted count, then bump saturation/value
    so the glow stays vivid on a dark backdrop. Returns colors ordered
    inner -> outer (most vivid first).
    """
    small = img.convert("RGB").resize((160, 200), Image.BILINEAR)
    arr = np.asarray(small)
    hsv = _rgb_to_hsv(arr)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    # Keep saturated, mid-bright pixels — that's where the card art lives,
    # not the slab plastic, label, or barcode.
    keep = (s > 0.30) & (v > 0.25) & (v < 0.95)
    if keep.sum() < 50:
        # Fallback: brand palette (the card is mostly neutral).
        return [ORANGE, PINK, PURPLE]

    h_keep = h[keep]
    s_keep = s[keep]
    v_keep = v[keep]
    weight = s_keep * v_keep  # vivid pixels count more

    # 24 hue buckets (15 deg each).
    bins = (h_keep / 15).astype(np.int32) % 24
    totals = np.bincount(bins, weights=weight, minlength=24)

    # Pick top N buckets that aren't too close to each other (>=45 deg apart).
    order = np.argsort(totals)[::-1]
    chosen: list[int] = []
    for idx in order:
        if totals[idx] <= 0:
            break
        if all(min(abs(idx - c), 24 - abs(idx - c)) >= 3 for c in chosen):
            chosen.append(int(idx))
        if len(chosen) >= n:
            break
    while len(chosen) < n and len(chosen) > 0:
        chosen.append(chosen[-1])
    if not chosen:
        return [ORANGE, PINK, PURPLE]

    palette: list[tuple[int, int, int]] = []
    for idx in chosen:
        in_bin = bins == idx
        avg_h = float(np.average(h_keep[in_bin], weights=weight[in_bin]))
        avg_s = float(np.average(s_keep[in_bin], weights=weight[in_bin]))
        avg_v = float(np.average(v_keep[in_bin], weights=weight[in_bin]))
        # Push saturation + value up so the glow reads on the dark bg.
        s_out = min(1.0, max(avg_s * 1.25, 0.85))
        v_out = min(1.0, max(avg_v * 1.20, 0.85))
        palette.append(_hsv_to_rgb(avg_h, s_out, v_out))

    return palette


def slab_aura(slab_size: tuple[int, int],
              colors: list[tuple[int, int, int]] | None = None) -> Image.Image:
    """
    Multi-layer glow radiating outward from the slab silhouette.

    `colors` is ordered inner -> outer (3 colors). When None, falls back to
    the brand orange/pink/purple ramp.
    """
    if colors is None or len(colors) < 3:
        colors = [ORANGE, PINK, PURPLE]

    inner, mid, outer = colors[0], colors[1], colors[2]

    sw, sh = slab_size
    pad = int(max(sw, sh) * 0.45)
    canvas = (sw + pad * 2, sh + pad * 2)
    aura = Image.new("RGBA", canvas, (0, 0, 0, 0))

    # (expand_px, blur_px, color, alpha) — outermost to innermost.
    layers = [
        (int(pad * 0.95), int(pad * 0.55), outer, 110),
        (int(pad * 0.65), int(pad * 0.40), mid,   140),
        (int(pad * 0.40), int(pad * 0.25), inner, 170),
        (int(pad * 0.18), int(pad * 0.10), (255, 240, 220), 100),
    ]
    for expand, blur, color, alpha in layers:
        layer = Image.new("RGBA", canvas, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.rounded_rectangle(
            (pad - expand, pad - expand,
             pad + sw + expand, pad + sh + expand),
            radius=expand + 24,
            fill=(*color, alpha),
        )
        layer = layer.filter(ImageFilter.GaussianBlur(radius=blur))
        aura = Image.alpha_composite(aura, layer)

    return aura


# ---------- composite ----------------------------------------------------- #

def drop_shadow(slab: Image.Image, blur: int = 24,
                offset: tuple[int, int] = (0, 16),
                opacity: float = 0.55) -> Image.Image:
    """
    Build a soft drop shadow for the slab. Returns RGBA the same size as
    slab (plus padding for the blur) so it can be composited just behind.
    """
    w, h = slab.size
    pad = blur * 2
    shadow = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rectangle(
        (pad, pad, pad + w, pad + h),
        fill=(0, 0, 0, int(255 * opacity)),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur))
    return shadow


def compose(slab: Image.Image, canvas_size: tuple[int, int] = (1500, 1500),
            scale: float = 0.90
            ) -> tuple[Image.Image, tuple[int, int, int, int],
                       list[tuple[int, int, int]]]:
    """
    Place the slab centered on the Sake Kitty backdrop, with shadow.
    `scale` is the slab's height as a fraction of the canvas height.
    """
    cw, ch = canvas_size
    bg = make_backdrop(canvas_size)

    # Resize slab to target height while preserving aspect ratio.
    sw, sh = slab.size
    target_h = int(ch * scale)
    target_w = int(sw * (target_h / sh))
    if target_w > cw * 0.9:
        target_w = int(cw * 0.9)
        target_h = int(sh * (target_w / sw))

    slab_resized = slab.resize((target_w, target_h), Image.LANCZOS)

    # Aura: multi-layer glow tinted to harmonize with this card's art.
    palette = extract_palette(slab_resized, n=3)
    print(f"    palette: {palette}")
    aura = slab_aura((target_w, target_h), palette)
    ax = (cw - aura.width) // 2
    ay = (ch - aura.height) // 2
    # Convert bg to RGBA for proper alpha compositing of the soft aura.
    bg_rgba = bg.convert("RGBA")
    aura_canvas = Image.new("RGBA", bg_rgba.size, (0, 0, 0, 0))
    aura_canvas.paste(aura, (ax, ay), aura)
    bg = Image.alpha_composite(bg_rgba, aura_canvas).convert("RGB")

    # Drop shadow — sits between aura and slab so the slab still has weight.
    shadow = drop_shadow(slab_resized, blur=28, offset=(0, 18), opacity=0.45)
    sx = (cw - shadow.width) // 2
    sy = (ch - shadow.height) // 2 + 18
    bg.paste(shadow, (sx, sy), shadow)

    # Slab itself.
    slab_rgba = slab_resized.convert("RGBA")
    px = (cw - target_w) // 2
    py = (ch - target_h) // 2
    bg.paste(slab_rgba, (px, py), slab_rgba)

    return bg, (px, py, target_w, target_h), palette


def _gradient_strip(width: int, height: int,
                    stops: list[tuple[float, tuple[int, int, int]]]
                    ) -> Image.Image:
    """
    Build a horizontal RGB gradient strip across `stops`.

    Each stop is (position 0..1, color). Linear interpolation between stops.
    """
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    xs = np.linspace(0, 1, width)
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        mask = (xs >= p0) & (xs <= p1)
        if not mask.any():
            continue
        t = (xs[mask] - p0) / max(p1 - p0, 1e-6)
        for ch in range(3):
            arr[:, mask, ch] = (c0[ch] + (c1[ch] - c0[ch]) * t).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def _brighten(color: tuple[int, int, int], min_v: float = 1.0,
              min_s: float = 0.85) -> tuple[int, int, int]:
    """Push a color toward max value/saturation so it reads on the dark bg."""
    arr = np.array([[color]], dtype=np.uint8)
    hsv = _rgb_to_hsv(arr)
    h = float(hsv[0, 0, 0])
    s = max(float(hsv[0, 0, 1]), min_s)
    v = max(float(hsv[0, 0, 2]), min_v)
    return _hsv_to_rgb(h, s, v)


def add_wordmark(canvas: Image.Image, text: str = "SAKE KITTY CARDS",
                 colors: list[tuple[int, int, int]] | None = None,
                 alpha: int = 220, tracking: int = 6) -> Image.Image:
    """
    Stamp the brand wordmark at the bottom-center, gradient-filled with
    the per-card palette so the text harmonizes with the slab's glow.

    Falls back to the site's orange→pink→purple if no palette is given.
    Tracked-out manually — PIL has no native letter-spacing.
    """
    if colors and len(colors) >= 3:
        # Brighten so the gradient stays readable against the dark backdrop.
        c0 = _brighten(colors[0])
        c1 = _brighten(colors[1])
        c2 = _brighten(colors[2])
        gradient_stops = [(0.0, c0), (0.5, c1), (1.0, c2)]
    else:
        gradient_stops = [(0.0, ORANGE), (0.55, PINK), (1.0, PURPLE)]

    cw, ch = canvas.size
    font_size = int(ch * 0.030)
    try:
        font = ImageFont.truetype(str(FONT_PATH), font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    # Pre-measure glyph widths so the tracked block can be centered.
    widths = [font.getbbox(c)[2] - font.getbbox(c)[0] for c in text]
    total_w = sum(widths) + tracking * (len(text) - 1)
    ascent, _ = font.getmetrics()

    margin_bottom = int(ch * 0.045)
    x = (cw - total_w) // 2
    y = ch - margin_bottom - ascent

    # 1) Render text as a white-on-transparent mask.
    text_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    cur = x
    for ch_, w in zip(text, widths):
        td.text((cur, y), ch_, font=font, fill=(255, 255, 255, 255))
        cur += w + tracking

    # 2) Build the brand gradient and clip it to the text alpha so the
    #    wordmark fills with the palette horizontally.
    gradient = _gradient_strip(cw, ch, gradient_stops).convert("RGBA")
    text_alpha = text_layer.split()[3]
    gradient.putalpha(text_alpha)

    # Knock overall opacity down so it reads as a wordmark, not a banner.
    arr = np.asarray(gradient).copy()
    arr[..., 3] = (arr[..., 3].astype(np.float32) * (alpha / 255.0)).astype(np.uint8)
    gradient = Image.fromarray(arr, "RGBA")

    # 3) Soft glow underneath so it reads on any backdrop tone.
    glow = gradient.filter(ImageFilter.GaussianBlur(radius=5))
    glow_arr = np.asarray(glow).copy()
    glow_arr[..., 3] = (glow_arr[..., 3].astype(np.float32) * 0.6).astype(np.uint8)
    glow = Image.fromarray(glow_arr, "RGBA")

    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba = Image.alpha_composite(canvas_rgba, glow)
    canvas_rgba = Image.alpha_composite(canvas_rgba, gradient)
    return canvas_rgba.convert("RGB")


# ---------- entry --------------------------------------------------------- #

def process_one(src: Path, out_dir: Path,
                out_name: str | None = None) -> Path:
    img = Image.open(src).convert("RGB")
    cropped = crop_slab(img)
    finished, _slab_rect, palette = compose(cropped)
    finished = add_wordmark(finished, colors=palette)
    name = out_name or f"{src.stem}_processed.jpg"
    out_path = out_dir / name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    finished.save(out_path, "JPEG", quality=92)
    print(f"  {src.name} -> {out_path.name}  "
          f"(crop {cropped.size}, out {finished.size})")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out"))
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {args.out.resolve()}")

    for src in args.inputs:
        if not src.exists():
            print(f"  SKIP missing: {src}", file=sys.stderr)
            continue
        process_one(src, args.out)


if __name__ == "__main__":
    main()
