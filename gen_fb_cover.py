"""
Generate a Facebook page cover image for Sake Kitty Cards.

Facebook displays the cover at:
  - Desktop:  820 x 312 px (full width visible)
  - Mobile:   640 x 360 px (centered crop — sides clipped)

We render at 1702 x 630 (2x retina) and keep critical content inside the
centered 1280 x 624 mobile-safe zone.

Output: ~/OneDrive/Desktop/sake-kitty-fb-cover.png
"""
import os
import random
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1702, 630
HERE      = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(HERE, 'logo.png')
FONT_PATH = os.path.join(HERE, 'Bangers-Regular.ttf')   # bundled with the script
OUT_PATH  = os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop', 'sake-kitty-fb-cover.png')

BRAND_GRADIENT = ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff']

# ─── Helpers ───────────────────────────────────────────────────────────────
def load_font(path, size, fallback='C:/Windows/Fonts/impact.ttf'):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:    return ImageFont.truetype(fallback, size)
        except Exception: return ImageFont.load_default()

def radial_blob(size, color_inner, color_outer, alpha_max=180):
    blob = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob)
    steps = 80
    ri = tuple(int(color_inner[i:i+2], 16) for i in (1, 3, 5))
    ro = tuple(int(color_outer[i:i+2], 16) for i in (1, 3, 5))
    for i in range(steps, 0, -1):
        t = i / steps
        r = tuple(int(ri[j] * t + ro[j] * (1 - t)) for j in range(3))
        a = int(alpha_max * t)
        radius = int(size / 2 * t)
        cx, cy = size // 2, size // 2
        bd.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(*r, a))
    return blob.filter(ImageFilter.GaussianBlur(size // 6))

def gradient_text_image(text, font, gradient_hex):
    """Return RGBA image of `text` filled with a horizontal gradient through gradient_hex colors."""
    pad = 8
    tmp = Image.new('L', (1, 1))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0] + 2 * pad
    h = bbox[3] - bbox[1] + 2 * pad

    # Text as alpha mask
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=255)

    # Horizontal gradient
    cols = [tuple(int(c[i:i+2], 16) for i in (1, 3, 5)) for c in gradient_hex]
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

# ─── Background + brand glow blobs ─────────────────────────────────────────
img = Image.new('RGB', (W, H), '#060608')

img.paste(radial_blob(900, '#ff4e00', '#ff0080'),                  (-300, -350), radial_blob(900, '#ff4e00', '#ff0080'))
img.paste(radial_blob(800, '#3a00ff', '#00d4ff'),                  (W - 500, H - 450), radial_blob(800, '#3a00ff', '#00d4ff'))
img.paste(radial_blob(600, '#7b2fff', '#ff0080', alpha_max=140),   (W // 2 - 300, H // 2 - 300), radial_blob(600, '#7b2fff', '#ff0080', alpha_max=140))

# ─── Sparkle particles ─────────────────────────────────────────────────────
random.seed(7)
SPARKLE_COLORS = ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff', '#ffffff', '#ffcc00']
sparkle = Image.new('RGBA', (W, H), (0, 0, 0, 0))
sd = ImageDraw.Draw(sparkle)
for _ in range(60):
    x = random.uniform(0, W)
    y = random.uniform(0, H)
    r = random.uniform(1.5, 4.0)
    color = random.choice(SPARKLE_COLORS)
    rgb = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
    glow_r = r * 4
    sd.ellipse((x - glow_r, y - glow_r, x + glow_r, y + glow_r), fill=(*rgb, 70))
    sd.ellipse((x - r, y - r, x + r, y + r),                       fill=(*rgb, 235))
sparkle = sparkle.filter(ImageFilter.GaussianBlur(0.6))
img.paste(sparkle, (0, 0), sparkle)

# ─── Layout note ───────────────────────────────────────────────────────────
# No logo on the banner — Facebook overlays the profile picture in the
# bottom-left corner (a ~170px circle). The text block is centered so it
# reads cleanly on both desktop and mobile, and stays clear of that overlap.

# ─── Text block (centered, atmospheric) ────────────────────────────────────
font_brand = load_font(FONT_PATH, 200)
font_sub   = load_font(FONT_PATH, 64)
font_tag   = load_font('C:/Windows/Fonts/arialbd.ttf', 30)
font_url   = load_font('C:/Windows/Fonts/arial.ttf',   26)

draw = ImageDraw.Draw(img)
center_x = W // 2

def measure(text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

# Big brand title (single line)
title = 'SAKE KITTY CARDS'
gtxt  = gradient_text_image(title, font_brand, BRAND_GRADIENT)
gw, gh = gtxt.size
title_y = 110

# Soft drop shadow
shadow_alpha = gtxt.split()[-1].point(lambda p: int(p * 0.55))
shadow = Image.new('RGBA', gtxt.size, (0, 0, 0, 0))
shadow.putalpha(shadow_alpha)
shadow = shadow.filter(ImageFilter.GaussianBlur(12))
img.paste(shadow, (center_x - gw // 2 + 8, title_y + 12), shadow)
img.paste(gtxt,   (center_x - gw // 2,     title_y),      gtxt)

# Subtitle
sub_text = 'Collecting, Done Right.'
sw, sh = measure(sub_text, font_sub)
sub_y = title_y + gh + 4
draw.text((center_x - sw // 2, sub_y), sub_text, font=font_sub, fill=(255, 255, 255, 255))

# Divider
div_w = 220
div_y = sub_y + sh + 28
draw.rectangle([center_x - div_w // 2, div_y, center_x + div_w // 2, div_y + 4], fill='#7b2fff')

# Offerings
tag_text = 'Singles  ·  Sealed  ·  Trade-Ins  ·  Live Events'
tw, th = measure(tag_text, font_tag)
tag_y = div_y + 26
draw.text((center_x - tw // 2, tag_y), tag_text, font=font_tag, fill=(255, 255, 255, 230))

# URL + IG handle row
url_text = 'sakekittycards.com   ·   @sakekittycards'
uw, uh = measure(url_text, font_url)
url_y = tag_y + th + 18
draw.text((center_x - uw // 2, url_y), url_text, font=font_url, fill=(255, 255, 255, 175))

# ─── Save ──────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
img.save(OUT_PATH, 'PNG', optimize=True)
print(f'Saved: {OUT_PATH}')
print(f'Dimensions: {W} x {H} (Facebook will resize for display)')
