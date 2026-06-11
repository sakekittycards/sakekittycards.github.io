"""Generate the 'shop is live' Instagram graphic (1080x1350)."""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANGERS = os.path.join(ROOT, 'Bangers-Regular.ttf')
ARIAL = 'C:/Windows/Fonts/arial.ttf'
ARIALBD = 'C:/Windows/Fonts/arialbd.ttf'
W, H = 1080, 1350
ORANGE = (255, 106, 0); PINK = (255, 0, 128); CYAN = (0, 212, 255); PURPLE = (123, 47, 255)

img = Image.new('RGB', (W, H), (7, 7, 13))

# --- background glows ---
glow = Image.new('RGB', (W, H), (7, 7, 13))
gd = ImageDraw.Draw(glow)
def radial(cx, cy, r, col, a):
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col + (a,))
    return layer.filter(ImageFilter.GaussianBlur(r // 2))
base = Image.new('RGBA', (W, H), (7, 7, 13, 255))
for cx, cy, r, col, a in [(300, 180, 520, ORANGE, 90), (820, 250, 460, PINK, 70),
                          (540, 1180, 620, PURPLE, 95), (900, 950, 360, CYAN, 55)]:
    base = Image.alpha_composite(base, radial(cx, cy, r, col, a))
img = base.convert('RGB')
draw = ImageDraw.Draw(img)

def F(path, size):
    return ImageFont.truetype(path, size)

def center_text(y, text, font, fill, ls=0):
    if ls:
        # letter-spaced
        widths = [draw.textlength(c, font=font) for c in text]
        total = sum(widths) + ls * (len(text) - 1)
        x = (W - total) / 2
        for c, wc in zip(text, widths):
            draw.text((x, y), c, font=font, fill=fill); x += wc + ls
        return
    w = draw.textlength(text, font=font)
    draw.text(((W - w) / 2, y), text, font=font, fill=fill)

def gradient_text(y, text, font, c1, c2):
    tw = int(draw.textlength(text, font=font)); asc, desc = font.getmetrics(); th = asc + desc
    grad = Image.new('RGB', (tw, th))
    gp = grad.load()
    for x in range(tw):
        t = x / max(1, tw - 1)
        gp_col = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
        for yy in range(th):
            gp[x, yy] = gp_col
    mask = Image.new('L', (tw, th), 0)
    ImageDraw.Draw(mask).text((0, 0), text, font=font, fill=255)
    img.paste(grad, (int((W - tw) / 2), int(y)), mask)

# --- logo ---
try:
    logo = Image.open(os.path.join(ROOT, 'logo.png')).convert('RGBA')
    lw = 300; lh = int(logo.height * lw / logo.width)
    logo = logo.resize((lw, lh))
    img.paste(logo, (int((W - lw) / 2), 95), logo)
    top = 95 + lh + 20
except Exception:
    top = 200

# --- eyebrow ---
center_text(top, 'SAKE KITTY CARDS', F(ARIALBD, 30), (255, 255, 255), ls=10)
# --- headline ---
gradient_text(top + 52, 'NOW LIVE', F(BANGERS, 200), ORANGE, PINK)
# --- subhead ---
center_text(top + 290, 'The full shop is open', F(ARIAL, 46), (235, 235, 247))

# --- category chips ---
chips = ['GRADED', 'SEALED', 'SINGLES']
cf = F(ARIALBD, 38)
padx, padyt, gap = 34, 18, 22
sizes = [draw.textlength(c, font=cf) for c in chips]
cw = [s + padx * 2 for s in sizes]
total = sum(cw) + gap * (len(chips) - 1)
x = (W - total) / 2; cy = top + 380; chh = 38 + padyt * 2
cols = [ORANGE, CYAN, PINK]
for c, wc, col in zip(chips, cw, cols):
    draw.rounded_rectangle([x, cy, x + wc, cy + chh], radius=chh // 2, outline=col, width=3)
    draw.text((x + padx, cy + padyt - 2), c, font=cf, fill=col)
    x += wc + gap

# --- fresh inventory ---
center_text(cy + chh + 46, 'Fresh inventory just dropped', F(ARIALBD, 44), (255, 210, 120))

# --- website ---
gradient_text(cy + chh + 130, 'sakekittycards.com', F(BANGERS, 92), CYAN, PURPLE)

# --- bottom strip ---
center_text(H - 95, 'Even more singles on our TCGplayer store', F(ARIAL, 30), (200, 200, 220))

out = os.path.join(ROOT, 'scripts', '_ig_live.png')
img.save(out, 'PNG')
# also to Downloads for easy posting
dl = os.path.join(os.path.expanduser('~'), 'Downloads', 'sakekitty_now_live.png')
img.save(dl, 'PNG')
print('saved', out)
print('saved', dl)
