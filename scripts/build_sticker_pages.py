"""Build sticker print pages: 2 character pages (6-up each) + 1 logo page (6-up)."""
import sys, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy.ndimage import label, binary_dilation, distance_transform_edt
from skimage.segmentation import watershed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'graded-uploader'))
from upscaler import upscale_pil

PAGE_W, PAGE_H = 2400, 3600
GRID_COLS, GRID_ROWS = 2, 3
STICKER_FILL = 0.85

# === PART 1: rebuild pages 1 and 2 with stragglers filtered ===
print('=== Pages 1 and 2 ===')
print('[1/3] Upscaling v7 source 4x...')
src_small = Image.open('assets/stickers/_source-sheet-v7.png').convert('RGB')
src_big = upscale_pil(src_small, scale=4)

print('[2/3] Watershed segmentation (12 stickers, no cell-line splits)...')
arr = np.array(src_small)
H_s, W_s = arr.shape[:2]
content_mask = (arr.min(axis=2) < 245)

SRC_COLS, SRC_ROWS = 4, 3
src_cell_w = W_s / SRC_COLS
src_cell_h = H_s / SRC_ROWS

# Seed markers: one seed per cell at its center (only if center hits content)
markers = np.zeros((H_s, W_s), dtype=np.int32)
seed_id = 1
cell_to_seed = {}
for r in range(SRC_ROWS):
    for c in range(SRC_COLS):
        cy = int((r + 0.5) * src_cell_h)
        cx = int((c + 0.5) * src_cell_w)
        # Plant a small disk of markers so seed is robust even if exact center is white
        for dy in range(-15, 16):
            for dx in range(-15, 16):
                yy, xx = cy + dy, cx + dx
                if 0 <= yy < H_s and 0 <= xx < W_s and content_mask[yy, xx]:
                    markers[yy, xx] = seed_id
        cell_to_seed[(r, c)] = seed_id
        seed_id += 1

# Watershed driven by distance transform of inverse mask -> grows each seed
# until it hits another seed, partitioning the content_mask cleanly.
distance = distance_transform_edt(content_mask)
ws = watershed(-distance, markers, mask=content_mask)
print(f'      watershed segments: {len(np.unique(ws)) - 1}')

def keep_largest_component(mask):
    if not mask.any():
        return mask
    sub_labeled, sub_n = label(mask)
    if sub_n <= 1:
        return mask
    sizes = np.bincount(sub_labeled.ravel())
    sizes[0] = 0
    biggest = sizes.argmax()
    return sub_labeled == biggest

def build_sticker(r, c):
    seed = cell_to_seed[(r, c)]
    sticker_mask = (ws == seed)
    sticker_mask = keep_largest_component(sticker_mask)
    if not sticker_mask.any():
        return None
    BIG_W, BIG_H = src_big.size
    mask_pil = Image.fromarray((sticker_mask * 255).astype(np.uint8))
    mask_big = mask_pil.resize((BIG_W, BIG_H), Image.LANCZOS)

    # Smooth the inner silhouette ITSELF (not just the alpha edge) so the
    # kiss-cut shape the Pixcut app traces is a clean curve, not a staircase.
    # Heavy Gaussian + threshold = morphological "rounding" of corners + ridges.
    inner_smooth = mask_big.filter(ImageFilter.GaussianBlur(radius=12))
    mask_big_arr = np.array(inner_smooth) > 127

    # Build the kiss-cut shape: dilate the smoothed inner, then blur HARD and
    # re-threshold. This gives a smooth outline that follows the silhouette
    # without inheriting any of its noise.
    border_px_big = 60   # ~14px after final scale to print
    border_mask_big = binary_dilation(mask_big_arr, iterations=border_px_big)
    border_pil = Image.fromarray((border_mask_big * 255).astype(np.uint8))
    border_smooth = border_pil.filter(ImageFilter.GaussianBlur(radius=10))
    border_alpha = np.array(border_smooth)  # 0..255, AA edge

    # bbox from the alpha (anything visible at all)
    visible = border_alpha > 8
    if not visible.any():
        return None
    ys, xs = np.where(visible)
    pad = 12
    py0 = max(int(ys.min()) - pad, 0)
    py1 = min(int(ys.max()) + 1 + pad, BIG_H)
    px0 = max(int(xs.min()) - pad, 0)
    px1 = min(int(xs.max()) + 1 + pad, BIG_W)

    big_arr = np.array(src_big)
    crop_rgb = big_arr[py0:py1, px0:px1]
    crop_inner = mask_big_arr[py0:py1, px0:px1]
    crop_alpha = border_alpha[py0:py1, px0:px1]

    h, w = py1 - py0, px1 - px0
    out = np.zeros((h, w, 4), dtype=np.uint8)
    # White everywhere visible (forms kiss-cut ring)
    out[..., 0] = 255
    out[..., 1] = 255
    out[..., 2] = 255
    # Then paint the (smoothed) inner sticker on top
    out[crop_inner, 0] = crop_rgb[crop_inner, 0]
    out[crop_inner, 1] = crop_rgb[crop_inner, 1]
    out[crop_inner, 2] = crop_rgb[crop_inner, 2]
    # Alpha = anti-aliased outer silhouette (with full opacity in the interior)
    out[..., 3] = np.maximum(crop_alpha, (crop_inner * 255).astype(np.uint8))
    return Image.fromarray(out, 'RGBA')

def build_page(picks):
    canvas = Image.new('RGBA', (PAGE_W, PAGE_H), (0, 0, 0, 0))
    out_cell_w = PAGE_W / GRID_COLS
    out_cell_h = PAGE_H / GRID_ROWS
    target_w = int(out_cell_w * STICKER_FILL)
    target_h = int(out_cell_h * STICKER_FILL)
    for i, (sr, sc) in enumerate(picks):
        out_c = i % GRID_COLS
        out_r = i // GRID_COLS
        sticker = build_sticker(sr, sc)
        if sticker is None: continue
        sw, sh = sticker.size
        scale = min(target_w / sw, target_h / sh)
        new_w, new_h = int(sw * scale), int(sh * scale)
        sticker_resized = sticker.resize((new_w, new_h), Image.LANCZOS)
        cell_cx = int((out_c + 0.5) * out_cell_w)
        cell_cy = int((out_r + 0.5) * out_cell_h)
        canvas.paste(sticker_resized, (cell_cx - new_w // 2, cell_cy - new_h // 2), sticker_resized)
    return canvas

print('[3/3] Saving pages 1 and 2...')
build_page([(0,0),(0,1),(1,0),(1,1),(2,0),(2,1)]).save(
    'assets/stickers/sticker-sheet-page1.png', 'PNG', dpi=(600, 600), optimize=True)
build_page([(0,2),(0,3),(1,2),(1,3),(2,2),(2,3)]).save(
    'assets/stickers/sticker-sheet-page2.png', 'PNG', dpi=(600, 600), optimize=True)

# === PART 2: logo sticker page (6-up, ChatGPT-designed circular logo) ===
print()
print('=== Logo sticker page (ChatGPT circular design) ===')
print('[1/4] Loading logo source...')
logo_src = r'C:\Users\lunar\Downloads\ChatGPT Image Apr 30, 2026, 09_34_46 PM.png'
logo = Image.open(logo_src).convert('RGB')
print(f'      logo: {logo.size}')
logo.save('assets/stickers/_source-logo-circular.png', 'PNG', optimize=True)

print('[2/4] Upscaling 4x via Real-ESRGAN...')
logo_up = upscale_pil(logo, scale=4)
print(f'      upscaled: {logo_up.size}')

print('[3/4] Detecting circle bounds + adding kiss-cut white border...')
arr = np.array(logo_up)
# Logo content = anything not near-white. Find its bbox, derive circle
non_white = arr.min(axis=2) < 245
ys, xs = np.where(non_white)
y0, y1 = int(ys.min()), int(ys.max())
x0, x1 = int(xs.min()), int(xs.max())
src_cy = (y0 + y1) // 2
src_cx = (x0 + x1) // 2
# Use the larger half-extent so we capture full design even if not perfectly centered
radius = max((y1 - y0), (x1 - x0)) // 2

# Build canvas: circle + ~60px kiss-cut white border
border_px = 60
extra = border_px + 30
out_size = (radius + extra) * 2
out = np.full((out_size, out_size, 4), 255, dtype=np.uint8)  # white canvas
out[..., 3] = 0  # transparent except where painted
new_cy = out_size // 2
new_cx = out_size // 2

y_o, x_o = np.ogrid[:out_size, :out_size]
circle_inner = ((y_o - new_cy) ** 2 + (x_o - new_cx) ** 2) <= radius ** 2
circle_outer = ((y_o - new_cy) ** 2 + (x_o - new_cx) ** 2) <= (radius + border_px) ** 2

# White kiss-cut ring
out[circle_outer] = [255, 255, 255, 255]

# Paste design pixels into the inner circle
out_y_idxs, out_x_idxs = np.where(circle_inner)
src_y_idxs = np.clip(src_cy + (out_y_idxs - new_cy), 0, arr.shape[0] - 1)
src_x_idxs = np.clip(src_cx + (out_x_idxs - new_cx), 0, arr.shape[1] - 1)
out[out_y_idxs, out_x_idxs, 0] = arr[src_y_idxs, src_x_idxs, 0]
out[out_y_idxs, out_x_idxs, 1] = arr[src_y_idxs, src_x_idxs, 1]
out[out_y_idxs, out_x_idxs, 2] = arr[src_y_idxs, src_x_idxs, 2]
out[out_y_idxs, out_x_idxs, 3] = 255

# Smooth the outer cut edge so the discrete circle isn't staircased at print res.
# Heavy blur + max with original keeps the interior opaque while the boundary
# fades cleanly across many pixels — Pixcut traces this as a smooth curve.
alpha = out[..., 3]
alpha_pil = Image.fromarray(alpha)
alpha_blur = alpha_pil.filter(ImageFilter.GaussianBlur(radius=10))
alpha_smooth = np.maximum(np.array(alpha_blur), alpha)
out[..., 3] = alpha_smooth.astype(np.uint8)

sticker_img = Image.fromarray(out, 'RGBA')
print(f'      sticker dims: {sticker_img.size}')
sticker_img.save('assets/stickers/logo-sticker.png', 'PNG', optimize=True)

print('[4/4] Tiling 6 copies on 4x6 portrait page (transparent bg)...')
canvas = Image.new('RGBA', (PAGE_W, PAGE_H), (0, 0, 0, 0))
out_cell_w = PAGE_W / GRID_COLS
out_cell_h = PAGE_H / GRID_ROWS
target_w = int(out_cell_w * STICKER_FILL)
target_h = int(out_cell_h * STICKER_FILL)

sw, sh = sticker_img.size
scale = min(target_w / sw, target_h / sh)
new_w, new_h = int(sw * scale), int(sh * scale)
sticker_resized = sticker_img.resize((new_w, new_h), Image.LANCZOS)

for i in range(6):
    out_c = i % GRID_COLS
    out_r = i // GRID_COLS
    cell_cx = int((out_c + 0.5) * out_cell_w)
    cell_cy = int((out_r + 0.5) * out_cell_h)
    canvas.paste(sticker_resized, (cell_cx - new_w // 2, cell_cy - new_h // 2), sticker_resized)

canvas.save('assets/stickers/sticker-sheet-logo.png', 'PNG', dpi=(600, 600), optimize=True)
print(f'      logo page: {canvas.size}')

print()
print('All done.')
