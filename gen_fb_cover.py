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

# ─── Background + brand glow blobs ─────────────────────────────────────────
img = Image.new('RGB', (W, H), '#060608')

img.paste(radial_blob(900, '#ff4e00', '#ff0080'),                (-300, -350), radial_blob(900, '#ff4e00', '#ff0080'))
img.paste(radial_blob(800, '#3a00ff', '#00d4ff'),                (W - 500, H - 450), radial_blob(800, '#3a00ff', '#00d4ff'))
img.paste(radial_blob(550, '#7b2fff', '#ff0080', alpha_max=120), (W // 2 - 200, H // 2 - 200), radial_blob(550, '#7b2fff', '#ff0080', alpha_max=120))

# Extra glow under the title area (right side) to lift the text
img.paste(radial_blob(700, '#ff6a00', '#7b2fff', alpha_max=110), (W - 850, -250), radial_blob(700, '#ff6a00', '#7b2fff', alpha_max=110))

# ─── Floating card silhouettes (background depth) ──────────────────────────
random.seed(13)
card_layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
# Manually placed so they don't crowd the title or the profile-pic zone
card_specs = [
    # (x, y, w, h, rotation_deg, color, alpha)
    (W - 280, 50,   180, 250, -16, '#ff6a00',  85),
    (W - 130, 200,  170, 240,  12, '#ff0080',  75),
    (W - 420, 280,  150, 210,  -6, '#7b2fff',  65),
    (W - 590, 80,   140, 200,  18, '#00d4ff',  55),
]
for x, y, cw, ch, rot, color, a in card_specs:
    card = card_silhouette(cw, ch, color, alpha=a)
    card = card.rotate(rot, resample=Image.BICUBIC, expand=True)
    card_layer.paste(card, (x, y), card)
img.paste(card_layer, (0, 0), card_layer)

# ─── Diagonal holofoil shine across the upper-right area ───────────────────
shine = Image.new('RGBA', (W, H), (0, 0, 0, 0))
sd = ImageDraw.Draw(shine)
shine_cols = [hex_rgb(c) for c in ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff']]
for i, color in enumerate(shine_cols):
    # Each band is a thin diagonal ribbon
    offset_x = 350 + i * 70
    sd.polygon([
        (W,             0),
        (W,             40),
        (offset_x + 60, H),
        (offset_x,      H),
    ], fill=(*color, 22))
shine = shine.filter(ImageFilter.GaussianBlur(8))
img.paste(shine, (0, 0), shine)

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

# ─── Text block (right-weighted) ───────────────────────────────────────────
font_brand = load_font(FONT_PATH, 170)
font_sub   = load_font(FONT_PATH, 56)
font_tag   = load_font('C:/Windows/Fonts/arialbd.ttf', 28)
font_handle= load_font('C:/Windows/Fonts/arial.ttf',   24)

draw = ImageDraw.Draw(img)

def measure(text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

# Right-anchor horizontally, vertically centered
text_right = W - 90
text_anchor_x = text_right       # right edge of text

# Big brand title (single line, gradient, right-aligned)
title  = 'SAKE KITTY CARDS'
gtxt   = gradient_text_image(title, font_brand, BRAND_GRADIENT)
gw, gh = gtxt.size
title_y = 80

# Soft drop shadow
shadow_alpha = gtxt.split()[-1].point(lambda p: int(p * 0.55))
shadow = Image.new('RGBA', gtxt.size, (0, 0, 0, 0))
shadow.putalpha(shadow_alpha)
shadow = shadow.filter(ImageFilter.GaussianBlur(12))
title_x = text_anchor_x - gw
img.paste(shadow, (title_x + 8, title_y + 12), shadow)
img.paste(gtxt,   (title_x,     title_y),      gtxt)

# Subtitle (right-aligned)
sub_text = 'Collecting, Done Right.'
sw, sh   = measure(sub_text, font_sub)
sub_y    = title_y + gh - 6
draw.text((text_anchor_x - sw, sub_y), sub_text, font=font_sub, fill=(255, 255, 255, 255))

# Divider (right-aligned)
div_w = 220
div_y = sub_y + sh + 22
draw.rectangle([text_anchor_x - div_w, div_y, text_anchor_x, div_y + 4], fill='#7b2fff')

# Offerings (right-aligned)
tag_text = 'Singles  ·  Sealed  ·  Trade-Ins  ·  Live Events'
tw, th   = measure(tag_text, font_tag)
tag_y    = div_y + 22
draw.text((text_anchor_x - tw, tag_y), tag_text, font=font_tag, fill=(255, 255, 255, 230))

# Handle row (right-aligned)
handle_text = 'sakekittycards.com   ·   @sakekittycards'
hw, hh = measure(handle_text, font_handle)
handle_y = tag_y + th + 14
draw.text((text_anchor_x - hw, handle_y), handle_text, font=font_handle, fill=(255, 255, 255, 175))

# ─── Save ──────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
img.save(OUT_PATH, 'PNG', optimize=True)
print(f'Saved: {OUT_PATH}')
print(f'Dimensions: {W} x {H}')
