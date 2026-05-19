"""Compose ChatGPT thank-you art + real QR into a thermal-print-ready 1200x1800 PNG."""
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import sys, pathlib, glob, os

URL_LINE = "A code waits at sakekittycards.com/tcg-thanks"

# Pick the most recent ChatGPT image from Downloads
DL = r"C:\Users\lunar\Downloads"
candidates = sorted(
    glob.glob(os.path.join(DL, "ChatGPT Image *.png")),
    key=os.path.getmtime,
    reverse=True,
)
if not candidates:
    print("No ChatGPT image found in Downloads"); sys.exit(1)
SRC = candidates[0]
print(f"Source: {SRC}")

QR  = r"C:\Users\lunar\OneDrive\Desktop\sake-kitty-cards-site\assets\print\promo-qr-tcg-thanks.png"
OUT_PNG  = r"C:\Users\lunar\OneDrive\Desktop\sake-kitty-cards-site\assets\print\thank-you-munbyn-4x6.png"
OUT_DBX  = r"C:\Users\lunar\Dropbox\sake-kitty-thank-you-munbyn-4x6.png"

# 1) Load art, upscale to 1200x1800 (4x6 @ 300 DPI)
art = Image.open(SRC).convert("L").resize((1200, 1800), Image.LANCZOS)
arr = np.array(art)

# 2) Auto-detect the blank slot inside the rope frame.
H, W = arr.shape
ystart = int(H * 0.55)
yend   = int(H * 0.90)

def longest_white_run(row):
    white = row > 235
    best_len = 0; best_lo = 0; best_hi = 0
    lo = None
    for x, w in enumerate(white):
        if w:
            if lo is None: lo = x
        else:
            if lo is not None:
                if x - lo > best_len:
                    best_len, best_lo, best_hi = x - lo, lo, x
                lo = None
    if lo is not None and W - lo > best_len:
        best_len, best_lo, best_hi = W - lo, lo, W
    return best_len, best_lo, best_hi

runs = []
for y in range(ystart, yend):
    L, lo, hi = longest_white_run(arr[y])
    runs.append((y, L, lo, hi))

threshold_w = int(W * 0.25)
band = [r for r in runs if r[1] >= threshold_w]
if not band:
    print("No blank slot found"); sys.exit(1)

groups = []
cur = [band[0]]
for prev, nxt in zip(band, band[1:]):
    if nxt[0] - prev[0] <= 3:
        cur.append(nxt)
    else:
        groups.append(cur); cur = [nxt]
groups.append(cur)
best_group = max(groups, key=len)

top    = best_group[0][0]
bottom = best_group[-1][0]
lefts  = [g[2] for g in best_group]
rights = [g[3] for g in best_group]
left   = int(np.median(lefts))
right  = int(np.median(rights))

slot_w = right - left
slot_h = bottom - top
# QR is square — fit to the smaller dim with small inset
side = min(slot_w, slot_h) - 8
cx = (left + right) // 2
cy = (top + bottom) // 2

print(f"Detected slot: top={top} bottom={bottom} left={left} right={right} (w={slot_w} h={slot_h}) -> QR side={side}")

qr = Image.open(QR).convert("L").resize((side, side), Image.NEAREST)
paste_x = cx - side // 2
paste_y = cy - side // 2

canvas = art.copy()
canvas.paste(qr, (paste_x, paste_y))

# 3) Overwrite the baked-in URL line with the real URL.
#    Find the divider above the footer — a row that's almost entirely solid black —
#    while excluding the outermost border rows. Then erase a thin band above it.
arr_c = np.array(canvas)
solid_dark_rows = []
# Skip the bottom outer border (last ~25px), only look between 85% and ~98% down
for y in range(int(H * 0.85), H - 25):
    if (arr_c[y] < 80).mean() > 0.9:  # 90%+ solid = real divider, not text
        solid_dark_rows.append(y)
if solid_dark_rows:
    # The URL line sits in a fixed-height band immediately above the bottom divider.
    # SCAN FOR A GIFT headline is bigger and lives further up — leave it alone.
    divider_top = solid_dark_rows[0]
    erase_top    = divider_top - 25
    erase_bottom = divider_top - 4
    print(f"Divider at y={divider_top}; erasing URL line y=[{erase_top},{erase_bottom}]")
    draw = ImageDraw.Draw(canvas)
    border_inset = 30
    draw.rectangle((border_inset, erase_top, W - border_inset, erase_bottom), fill=255)
    font = None
    for f in [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"]:
        if os.path.exists(f):
            font = ImageFont.truetype(f, size=18)
            break
    if font is not None:
        bbox = draw.textbbox((0, 0), URL_LINE, font=font)
        tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
        tx = (W - tw) // 2 - bbox[0]
        ty = (erase_top + erase_bottom) // 2 - th // 2 - bbox[1]
        draw.text((tx, ty), URL_LINE, fill=0, font=font)

# 4) Threshold to pure black/white for thermal
arr2 = np.array(canvas)
bw = (arr2 > 200).astype(np.uint8) * 255
out_l = Image.fromarray(bw, mode="L")
out_l.save(OUT_PNG, dpi=(300, 300))

pathlib.Path(OUT_DBX).write_bytes(pathlib.Path(OUT_PNG).read_bytes())
print(f"Saved: {OUT_PNG}")
print(f"Saved: {OUT_DBX}")
