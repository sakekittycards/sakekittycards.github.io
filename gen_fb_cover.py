"""
Generate a Facebook page cover image for Sake Kitty Cards.

FB business pages overlap the profile picture in the BOTTOM-LEFT of the
cover (~170px circle on desktop). Layout strategy:
  - Bottom-left ~280x280 region: kept atmospheric (glow + sparkles only)
  - Title + tagline + offerings: weighted to the right side
  - Right edge: handle / IG tag for visual balance
  - Diagonal holofoil-style shine cutting across to add motion/depth

Output: ~/OneDrive/Desktop/sake-kitty-fb-cover.png
"""
import math
import os
import random
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1702, 630
HERE      = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(HERE, 'logo.png')
FONT_PATH = os.path.join(HERE, 'Bangers-Regular.ttf')
OUT_PATH  = os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop', 'sake-kitty-fb-cover.png')

BRAND_GRADIENT = ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff']

# ─── Helpers ───────────────────────────────────────────────────────────────
def hex_rgb(h):  return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))

def load_font(path, size, fallback='C:/Windows/Fonts/impact.ttf'):
    try:    return ImageFont.truetype(path, size)
    except Exception:
        try:    return ImageFont.truetype(fallback, size)
        except Exception: return ImageFont.load_default()

def radial_blob(size, color_inner, color_outer, alpha_max=180):
    blob = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob)
    steps = 80
    ri, ro = hex_rgb(color_inner), hex_rgb(color_outer)
    for i in range(steps, 0, -1):
        t = i / steps
        r = tuple(int(ri[j] * t + ro[j] * (1 - t)) for j in range(3))
        a = int(alpha_max * t)
        radius = int(size / 2 * t)
        cx, cy = size // 2, size // 2
        bd.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(*r, a))
    return blob.filter(ImageFilter.GaussianBlur(size // 6))

def gradient_text_image(text, font, gradient_hex):
    pad = 8
    tmp = Image.new('L', (1, 1))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0] + 2 * pad
    h = bbox[3] - bbox[1] + 2 * pad
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=255)
    cols = [hex_rgb(c) for c in gradient_hex]
    n = len(cols) - 1
    grad = Image.new('RGB', (w, h), cols[0])
    gd = ImageDraw.Draw(grad)
    for x in range(w):
        t = x / max(1, w - 1) * n
        i = min(int(t), n - 1)
        f = t - i
        c1, c2 = cols[i], cols[i + 1]
        color = tuple(int(c1[j] * (1 - f) + c2[j] * f) for j in range(3))
        gd.line([(x, 0), (x, h)], fill=color)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    out.paste(grad, (0, 0))
    out.putalpha(mask)
    return out

def card_silhouette(w, h, color_hex, alpha=110):
    """A blurred, tilted Pokémon-card-shaped rectangle as background depth."""
    pad = 30
    img_ = Image.new('RGBA', (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img_)
    rgb = hex_rgb(color_hex)
    d.rounded_rectangle((pad, pad, pad + w, pad + h), radius=14, fill=(*rgb, alpha))
    return img_.filter(ImageFilter.GaussianBlur(4))

# ─── Pure black background ─────────────────────────────────────────────────
img = Image.new('RGB', (W, H), '#000000')

# ─── Sparkle particles (subtle, scattered) ─────────────────────────────────
random.seed(7)
SPARKLE_COLORS = ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff', '#ffffff', '#ffcc00']
sparkle = Image.new('RGBA', (W, H), (0, 0, 0, 0))
spd = ImageDraw.Draw(sparkle)
for _ in range(55):
    x = random.uniform(0, W)
    y = random.uniform(0, H)
    r = random.uniform(1.4, 3.6)
    rgb = hex_rgb(random.choice(SPARKLE_COLORS))
    glow_r = r * 4
    spd.ellipse((x - glow_r, y - glow_r, x + glow_r, y + glow_r), fill=(*rgb, 70))
    spd.ellipse((x - r, y - r, x + r, y + r),                       fill=(*rgb, 235))
sparkle = sparkle.filter(ImageFilter.GaussianBlur(0.6))
img.paste(sparkle, (0, 0), sparkle)

# ─── Text block (centered, larger secondary text) ──────────────────────────
font_brand  = load_font(FONT_PATH, 180)
font_sub    = load_font(FONT_PATH, 80)
font_tag    = load_font('C:/Windows/Fonts/arialbd.ttf', 38)
font_handle = load_font('C:/Windows/Fonts/arial.ttf',   32)

draw = ImageDraw.Draw(img)
center_x = W // 2

def measure(text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

# Pre-measure everything so we can vertically center the whole stack
title       = 'SAKE KITTY CARDS'
sub_text    = 'Collecting, Done Right.'
tag_text    = 'Singles  ·  Sealed  ·  Trade-Ins  ·  Live Events'
handle_text = 'sakekittycards.com   ·   @sakekittycards'

gtxt   = gradient_text_image(title, font_brand, BRAND_GRADIENT)
gw, gh = gtxt.size
sw, sh = measure(sub_text,    font_sub)
tw, th = measure(tag_text,    font_tag)
hw, hh = measure(handle_text, font_handle)

# Spacing between blocks (must match the offsets used below)
GAP_TITLE_SUB   = -8
GAP_SUB_DIV     = 26
DIV_HEIGHT      = 5
GAP_DIV_TAG     = 28
GAP_TAG_HANDLE  = 18

stack_h = (gh + GAP_TITLE_SUB + sh + GAP_SUB_DIV + DIV_HEIGHT
           + GAP_DIV_TAG + th + GAP_TAG_HANDLE + hh)
title_y = (H - stack_h) // 2

# Soft drop shadow
shadow_alpha = gtxt.split()[-1].point(lambda p: int(p * 0.55))
shadow = Image.new('RGBA', gtxt.size, (0, 0, 0, 0))
shadow.putalpha(shadow_alpha)
shadow = shadow.filter(ImageFilter.GaussianBlur(12))
title_x = center_x - gw // 2
img.paste(shadow, (title_x + 8, title_y + 12), shadow)
img.paste(gtxt,   (title_x,     title_y),      gtxt)

# Subtitle (centered, larger)
sub_y = title_y + gh + GAP_TITLE_SUB
draw.text((center_x - sw // 2, sub_y), sub_text, font=font_sub, fill=(255, 255, 255, 255))

# Divider (centered)
div_w = 280
div_y = sub_y + sh + GAP_SUB_DIV
draw.rectangle([center_x - div_w // 2, div_y, center_x + div_w // 2, div_y + DIV_HEIGHT], fill='#7b2fff')

# Offerings (centered, larger)
tag_y = div_y + GAP_DIV_TAG
draw.text((center_x - tw // 2, tag_y), tag_text, font=font_tag, fill=(255, 255, 255, 235))

# Handle row (centered, larger)
handle_y = tag_y + th + GAP_TAG_HANDLE
draw.text((center_x - hw // 2, handle_y), handle_text, font=font_handle, fill=(255, 255, 255, 190))

# ─── Save ──────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
img.save(OUT_PATH, 'PNG', optimize=True)
print(f'Saved: {OUT_PATH}')
print(f'Dimensions: {W} x {H}')
