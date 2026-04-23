"""
Generate a 36x18 desk mat / XL mousepad design for Printful.

Render at 5400x2700 (150 DPI) — Printful's recommended minimum for this product.
Bump to 300 DPI (10800x5400) by changing DPI_MULT if you want maximum quality.

Composition strategy: 36" wide desk mat gets covered by keyboard on the left
and mouse on the right during normal use. The center ~40% is the "safe visible"
zone — that's where the logo + tagline live. Edges + corners get atmospheric
glows + sparkles that can be partially covered without losing the vibe.

Output: ~/OneDrive/Desktop/sake-kitty-mousepad.png
"""
import math, os, random
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

# ─── Config ────────────────────────────────────────────────────────────────
DPI_MULT = 1.0                           # set to 2.0 for 300 DPI / 10800x5400
W, H = int(5400 * DPI_MULT), int(2700 * DPI_MULT)

HERE      = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(HERE, 'logo-transparent-print.png')
FONT_PATH = os.path.join(HERE, 'Bangers-Regular.ttf')
OUT_PATH  = os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop', 'sake-kitty-mousepad.png')

BRAND_GRADIENT = ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff']
SPARKLE_COLORS = ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff', '#ffffff', '#ffcc00']

# ─── Helpers ───────────────────────────────────────────────────────────────
def hex_rgb(h): return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))

def radial_blob(size, c_in, c_out, alpha_max=200):
    blob = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(blob)
    ri, ro = hex_rgb(c_in), hex_rgb(c_out)
    steps = 100
    for i in range(steps, 0, -1):
        t = i / steps
        rgb = tuple(int(ri[j]*t + ro[j]*(1-t)) for j in range(3))
        a = int(alpha_max * t)
        r = int(size/2 * t)
        cx, cy = size//2, size//2
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*rgb, a))
    return blob.filter(ImageFilter.GaussianBlur(size // 5))

def gradient_text(text, font, gradient_hex, pad=20):
    tmp = Image.new('L', (1, 1))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0] + 2*pad
    h = bbox[3] - bbox[1] + 2*pad
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=255)
    cols = [hex_rgb(c) for c in gradient_hex]
    n = len(cols) - 1
    grad = Image.new('RGB', (w, h), cols[0])
    gd = ImageDraw.Draw(grad)
    for x in range(w):
        t = x / max(1, w - 1) * n
        i = min(int(t), n - 1); f = t - i
        c1, c2 = cols[i], cols[i+1]
        col = tuple(int(c1[j]*(1-f) + c2[j]*f) for j in range(3))
        gd.line([(x, 0), (x, h)], fill=col)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    out.paste(grad, (0, 0))
    out.putalpha(mask)
    return out

# ─── Background (black + atmospheric glows) ────────────────────────────────
img = Image.new('RGB', (W, H), '#000000')

# Big glows in the 4 corners so coverage by keyboard/mouse doesn't kill the vibe.
glows = [
    (radial_blob(int(2600*DPI_MULT), '#ff4e00', '#ff0080'),                    (-700, -900)),
    (radial_blob(int(2400*DPI_MULT), '#3a00ff', '#00d4ff'),                    (W - 1700, H - 1500)),
    (radial_blob(int(1800*DPI_MULT), '#7b2fff', '#ff0080', alpha_max=140),     (W//2 - 900, H//2 - 900)),
    (radial_blob(int(1900*DPI_MULT), '#ff6a00', '#7b2fff', alpha_max=160),     (W - 2400, -800)),
    (radial_blob(int(1700*DPI_MULT), '#ff0080', '#3a00ff', alpha_max=130),     (-500, H - 1400)),
]
for g, pos in glows:
    img.paste(g, pos, g)

# ─── Sparkle particle field (dense — lots of real estate) ──────────────────
random.seed(42)
sparkles = Image.new('RGBA', (W, H), (0, 0, 0, 0))
sd = ImageDraw.Draw(sparkles)
for _ in range(220):
    x = random.uniform(0, W)
    y = random.uniform(0, H)
    r = random.uniform(4, 11) * DPI_MULT
    rgb = hex_rgb(random.choice(SPARKLE_COLORS))
    glow_r = r * 4
    sd.ellipse((x-glow_r, y-glow_r, x+glow_r, y+glow_r), fill=(*rgb, 80))
    sd.ellipse((x-r, y-r, x+r, y+r), fill=(*rgb, 240))
sparkles = sparkles.filter(ImageFilter.GaussianBlur(1.2))
img.paste(sparkles, (0, 0), sparkles)

# ─── Diagonal holofoil ribbons across the full width ────────────────────────
shine = Image.new('RGBA', (W, H), (0, 0, 0, 0))
sd = ImageDraw.Draw(shine)
ribbon_cols = [hex_rgb(c) for c in BRAND_GRADIENT]
for i, color in enumerate(ribbon_cols):
    x_off = int((600 + i * 180) * DPI_MULT)
    band_w = int(200 * DPI_MULT)
    sd.polygon([
        (W, 0), (W, band_w),
        (x_off + band_w, H), (x_off, H),
    ], fill=(*color, 26))
shine = shine.filter(ImageFilter.GaussianBlur(int(14 * DPI_MULT)))
img.paste(shine, (0, 0), shine)

# ─── Logo (centered, big enough to be the hero) ────────────────────────────
logo = Image.open(LOGO_PATH).convert('RGBA')
logo_target = int(1600 * DPI_MULT)
scale = logo_target / logo.width
logo = logo.resize((logo_target, int(logo.height * scale)), Image.LANCZOS)

# Glow ring behind the logo to lift it off the bg
ring = Image.new('RGBA', (logo.width + 240, logo.height + 240), (0, 0, 0, 0))
ImageDraw.Draw(ring).ellipse([0, 0, logo.width + 240, logo.height + 240], fill=(255, 106, 0, 110))
ring = ring.filter(ImageFilter.GaussianBlur(90))

lx = (W - logo.width) // 2
ly = (H - logo.height) // 2 - int(60 * DPI_MULT)
img.paste(ring, (lx - 120, ly - 120), ring)
img.paste(logo, (lx, ly), logo)

# ─── Tagline (gradient Bangers, under the logo) ────────────────────────────
font_tag = ImageFont.truetype(FONT_PATH, int(180 * DPI_MULT))
tag_img = gradient_text('COLLECTING, DONE RIGHT.', font_tag, BRAND_GRADIENT, pad=int(24 * DPI_MULT))

# Soft drop shadow for legibility
sh_alpha = tag_img.split()[-1].point(lambda p: int(p * 0.55))
shadow = Image.new('RGBA', tag_img.size, (0, 0, 0, 0))
shadow.putalpha(sh_alpha)
shadow = shadow.filter(ImageFilter.GaussianBlur(int(16 * DPI_MULT)))

tx = (W - tag_img.width) // 2
ty = ly + logo.height - int(20 * DPI_MULT)
img.paste(shadow,  (tx + int(10*DPI_MULT), ty + int(14*DPI_MULT)), shadow)
img.paste(tag_img, (tx, ty), tag_img)

# ─── Save ──────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
img.save(OUT_PATH, 'PNG', optimize=True)
print(f'Saved: {OUT_PATH}')
print(f'Dimensions: {W} x {H}')
print(f'File size: {os.path.getsize(OUT_PATH):,} bytes')
