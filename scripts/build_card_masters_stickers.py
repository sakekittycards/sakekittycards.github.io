"""Build Card Masters sticker sheet (6-up, 4x6 portrait, 600 DPI).

Pulls the user's ChatGPT-generated source, extracts the circular sticker,
stamps a clean linktr.ee URL pill onto it programmatically (so we don't
depend on the image-gen model rendering the URL correctly), and tiles 6
copies on the print page with extra spacing.
"""
import os, shutil
import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont
from scipy.ndimage import label, binary_dilation

URL_TEXT = 'linktr.ee/soflocardmasters'

PAGE_W, PAGE_H = 2400, 3600       # 4x6 portrait @ 600 DPI
GRID_COLS, GRID_ROWS = 2, 3
STICKER_FILL = 0.72                # vs 0.85 on Sake Kitty -> noticeably more spacing

# === STEP 1: copy the source into the repo so we don't depend on Downloads ===
src_external = r'C:\Users\lunar\Downloads\ChatGPT Image Apr 30, 2026, 11_55_22 PM.png'
# Use the clean (no-pill) source so we can stamp a bigger URL pill programmatically.
# Print size of the URL: font_size factor × radius / page-scale ÷ 600 dpi.
# At 0.13, prints around ~7pt — readable from a foot away on a 1.5" sticker.
URL_ALREADY_IN_SOURCE = False
# No pill — URL is rendered as bold white text with a soft dark halo for
# legibility on the starfield. The URL is constrained to fit comfortably
# inside the inner red accent ring (NOT the outer white kiss-cut), with
# margin so it doesn't visually crowd the ring.
URL_FONT_SIZE_FACTOR = 0.16          # upper bound; auto-shrinks if URL doesn't fit
INNER_RADIUS_FRAC    = 0.83          # constrain URL to this fraction of total radius
URL_BREATHING_FRAC   = 0.10          # leave this much chord-space margin around the URL
brand_dir = 'assets/stickers/card-masters'
os.makedirs(brand_dir, exist_ok=True)
src_local = os.path.join(brand_dir, '_source-card-masters.png')
shutil.copy2(src_external, src_local)
print(f'[1/4] Source copied: {src_local}')
src = Image.open(src_local).convert('RGB')
print(f'      dims: {src.size}')

# === STEP 2: detect the sticker by finding the largest sticker-content blob ===
# Works for both single-sticker sources and 6-up mock-ups (picks the biggest blob;
# in 6-up, dilation is mild enough that adjacent circles don't merge).
arr = np.array(src)
H_a, W_a = arr.shape[:2]
mx = arr.max(axis=2).astype(int)
mn = arr.min(axis=2).astype(int)
sat = mx - mn
content = (mx < 80) | (sat > 80)
content_dil = binary_dilation(content, iterations=6)

labeled, n = label(content_dil)
sizes = np.bincount(labeled.ravel())
sizes[0] = 0
big_lbl = int(sizes.argmax())
ys, xs = np.where(labeled == big_lbl)
y0, y1 = int(ys.min()), int(ys.max())
x0, x1 = int(xs.min()), int(xs.max())

# Use width as diameter (height can be clipped at image edges; width is reliable
# when the sticker fills the source horizontally with margins).
diameter = max(x1 - x0, y1 - y0)
src_r = diameter // 2
src_cx = (x0 + x1) // 2
src_cy = (y0 + y1) // 2
src_r = int(src_r * 1.04)  # +4% to capture white kiss-cut ring already in design
print(f'[2/4] components: {n}, largest blob bbox: ({x0},{y0})-({x1},{y1})')
print(f'      circle: center=({src_cx},{src_cy}) radius={src_r}')

# === STEP 3: build clean single sticker on transparent bg ===
crop_size = (src_r + 50) * 2
out = np.zeros((crop_size, crop_size, 4), dtype=np.uint8)
new_cy = crop_size // 2
new_cx = crop_size // 2
y_o, x_o = np.ogrid[:crop_size, :crop_size]
visible = ((y_o - new_cy) ** 2 + (x_o - new_cx) ** 2) <= src_r ** 2

out_y_idxs, out_x_idxs = np.where(visible)
src_y_idxs = np.clip(src_cy + (out_y_idxs - new_cy), 0, H_a - 1)
src_x_idxs = np.clip(src_cx + (out_x_idxs - new_cx), 0, W_a - 1)
out[out_y_idxs, out_x_idxs, 0] = arr[src_y_idxs, src_x_idxs, 0]
out[out_y_idxs, out_x_idxs, 1] = arr[src_y_idxs, src_x_idxs, 1]
out[out_y_idxs, out_x_idxs, 2] = arr[src_y_idxs, src_x_idxs, 2]
out[out_y_idxs, out_x_idxs, 3] = 255

# Smooth the alpha edge so the kiss-cut isn't staircased
alpha = out[..., 3]
alpha_pil = Image.fromarray(alpha)
alpha_blur = alpha_pil.filter(ImageFilter.GaussianBlur(radius=8))
alpha_smooth = np.maximum(np.array(alpha_blur), alpha)
out[..., 3] = alpha_smooth.astype(np.uint8)

sticker = Image.fromarray(out, 'RGBA')
print(f'[3a/4] Single sticker: {sticker.size}')

if URL_ALREADY_IN_SOURCE:
    print('[3b/4] URL already in source — skipping programmatic stamping')
else:
    # Stamp the linktr.ee URL pill onto the sticker programmatically.
    # Deterministic text rendering — no image-gen hallucination risk.
    def _load_bold_font(size):
        candidates = [
            r'C:\Windows\Fonts\segoeuib.ttf',
            r'C:\Windows\Fonts\arialbd.ttf',
            r'C:\Windows\Fonts\arial.ttf',
        ]
        for fp in candidates:
            if os.path.exists(fp):
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    measure_draw = ImageDraw.Draw(sticker.copy(), 'RGBA')
    ctr_x, ctr_y = new_cx, new_cy
    radius_eff = src_r

    # The URL must fit inside the INNER red accent ring (which sits inside
    # the white kiss-cut). That's `radius_eff * INNER_RADIUS_FRAC` — not
    # the full sticker radius. We also leave breathing room around the URL
    # so it doesn't visually crowd the red ring.
    inner_radius = int(radius_eff * INNER_RADIUS_FRAC)
    TARGET_Y_OFFSET_FRACTION = 0.45  # fraction of INNER radius, not full radius
    target_y_offset = int(inner_radius * TARGET_Y_OFFSET_FRACTION)
    desired_font = max(int(inner_radius * URL_FONT_SIZE_FACTOR), 22)

    def _measure(fs):
        f = _load_bold_font(fs)
        bbox = measure_draw.textbbox((0, 0), URL_TEXT, font=f)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        # Breathing margin scales with inner radius so it feels natural
        sm = max(int(inner_radius * URL_BREATHING_FRAC), int(fs * 0.7))
        return f, bbox, tw, th, sm

    font_size = desired_font
    while font_size >= 22:
        _, _, _tw, _th, _sm = _measure(font_size)
        py_bottom = target_y_offset + _th // 2 + 8
        half_text_w_safe = _tw / 2 + _sm
        # Constraint: text + safety margin must fit inside the INNER ring
        if py_bottom < inner_radius and half_text_w_safe ** 2 + py_bottom ** 2 <= inner_radius ** 2:
            break
        font_size -= 1

    font, text_bbox, text_w, text_h, _ = _measure(font_size)
    cx_text = ctr_x
    cy_text = ctr_y + target_y_offset
    text_x = cx_text - text_w // 2 - text_bbox[0]
    text_y = cy_text - text_h // 2 - text_bbox[1]

    # Build the entire URL effect (halo + text + stroke) on a separate
    # overlay, then alpha-clip the overlay to the sticker's existing alpha
    # channel before compositing. This guarantees nothing can leak past
    # the kiss-cut border — the halo is mathematically constrained to
    # only show inside the visible sticker.
    overlay = Image.new('RGBA', sticker.size, (0, 0, 0, 0))

    # Halo: blurred dark text drawn on its own layer, composited twice to
    # build up opacity, all into the overlay
    halo = Image.new('RGBA', sticker.size, (0, 0, 0, 0))
    halo_draw = ImageDraw.Draw(halo)
    halo_draw.text((text_x, text_y), URL_TEXT, font=font, fill=(0, 0, 0, 230))
    halo = halo.filter(ImageFilter.GaussianBlur(radius=max(8, int(font_size * 0.55))))
    overlay = Image.alpha_composite(overlay, halo)
    overlay = Image.alpha_composite(overlay, halo)

    # Bold white text with thin black stroke for crisp edges
    overlay_draw = ImageDraw.Draw(overlay)
    stroke_w = max(2, int(font_size * 0.08))
    overlay_draw.text((text_x, text_y), URL_TEXT, font=font,
                      fill=(255, 255, 255, 255),
                      stroke_width=stroke_w, stroke_fill=(0, 0, 0, 240))

    # Clip the overlay to a circular mask matching the INNER red accent
    # ring (with a small soft falloff so the edge isn't a hard cutoff).
    # This keeps the halo entirely inside the red ring — it cannot bleed
    # onto the red border or the white kiss-cut.
    H_s = sticker.size[1]; W_s = sticker.size[0]
    yy, xx = np.ogrid[:H_s, :W_s]
    dist = np.sqrt((yy - ctr_y) ** 2 + (xx - ctr_x) ** 2)
    # Hard inside, soft falloff over the last 6px of inner radius
    soft_edge = 6.0
    inner_mask = np.clip((inner_radius - dist) / soft_edge, 0, 1)
    inner_mask_u8 = (inner_mask * 255).astype(np.uint8)

    overlay_arr = np.array(overlay)
    clipped_alpha = (overlay_arr[..., 3].astype(np.uint16) * inner_mask_u8 // 255).astype(np.uint8)
    overlay_arr[..., 3] = clipped_alpha
    overlay = Image.fromarray(overlay_arr, 'RGBA')

    sticker = Image.alpha_composite(sticker, overlay)
    print(f'[3b/4] URL stamped (no pill, alpha-clipped): "{URL_TEXT}" @ font {font_size}px, text {text_w}x{text_h}')

# === STEP 4: tile 6 on 4x6 portrait page with extra spacing ===
print('[4/4] Tiling 6 copies on 4x6 portrait page...')
canvas = Image.new('RGBA', (PAGE_W, PAGE_H), (0, 0, 0, 0))
out_cell_w = PAGE_W / GRID_COLS
out_cell_h = PAGE_H / GRID_ROWS
target_w = int(out_cell_w * STICKER_FILL)
target_h = int(out_cell_h * STICKER_FILL)
sw, sh = sticker.size
scale = min(target_w / sw, target_h / sh)
new_w, new_h = int(sw * scale), int(sh * scale)
sticker_resized = sticker.resize((new_w, new_h), Image.LANCZOS)
for i in range(6):
    out_c = i % GRID_COLS
    out_r = i // GRID_COLS
    cell_cx = int((out_c + 0.5) * out_cell_w)
    cell_cy = int((out_r + 0.5) * out_cell_h)
    canvas.paste(sticker_resized, (cell_cx - new_w // 2, cell_cy - new_h // 2), sticker_resized)

out_path = os.path.join(brand_dir, 'sticker-sheet-card-masters.png')
canvas.save(out_path, 'PNG', dpi=(600, 600), optimize=True)
print(f'      saved: {out_path}  ({canvas.size})')
print()
print('Done.')
