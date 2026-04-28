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

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from upscaler import upscale_pil

FONT_PATH = Path(__file__).parent / "fonts" / "Bangers-Regular.ttf"
LOGO_PATH = Path(__file__).parent.parent.parent / "logo-transparent.png"

# Lazy-loaded rembg session (one-time model load, ~4s).
_REMBG_SESSION = None


def _get_rembg_session():
    global _REMBG_SESSION
    if _REMBG_SESSION is None:
        from rembg import new_session
        # birefnet-general — newer than u2net, ~973MB. Edge accuracy is
        # markedly better, especially on rounded corners and translucent
        # plastic. Worth the model size (one-time download); inference
        # cost per card is comparable to u2net.
        _REMBG_SESSION = new_session("birefnet-general")
    return _REMBG_SESSION


def _walk_inward_to_slab_edge(rgb: np.ndarray,
                              x0: int, y0: int, x1: int, y1: int,
                              ) -> tuple[int, int, int, int]:
    """
    Given an inflated bbox containing the slab plus paper around it,
    walk each edge inward until the strip stops being uniform paper.

    "Paper" test: low saturation AND low brightness variance. A row of
    paper has pixels clustered tightly around its mean (~5-10 stdev)
    even when the scanner vignette has darkened the mean to 200-220.
    A row of slab content (label band, card art, edge refraction) has
    high variance from the text, color transitions, and outline shadows
    — that fails the test and stops the walk.

    Variance-based avoids the scanner-vignette failure mode where
    brightness-only tests stop walking partway through paper because
    the vignetted paper is dimmer than the threshold.
    """
    L = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[..., 1]

    SAT_MAX = 30      # paper is essentially zero-saturation
    STD_MAX = 14      # paper is uniformly toned, even with vignette
    OCCUPANCY = 0.85  # 85% of the strip must satisfy both

    def is_paper_row(r: int) -> bool:
        Lr = L[r, x0:x1].astype(np.float32)
        Sr = sat[r, x0:x1]
        # Local stdev via a sliding window: compare each pixel to its
        # neighborhood's mean. Cheap proxy: |L - row_mean| < STD_MAX.
        row_mean = float(np.mean(Lr))
        is_uniform = np.abs(Lr - row_mean) < STD_MAX
        is_unsaturated = Sr < SAT_MAX
        return float(np.mean(is_uniform & is_unsaturated)) > OCCUPANCY

    def is_paper_col(c: int) -> bool:
        Lc = L[y0:y1, c].astype(np.float32)
        Sc = sat[y0:y1, c]
        col_mean = float(np.mean(Lc))
        is_uniform = np.abs(Lc - col_mean) < STD_MAX
        is_unsaturated = Sc < SAT_MAX
        return float(np.mean(is_uniform & is_unsaturated)) > OCCUPANCY

    ny0 = y0
    while ny0 < y1 - 1 and is_paper_row(ny0):
        ny0 += 1
    ny1 = y1 - 1
    while ny1 > ny0 and is_paper_row(ny1):
        ny1 -= 1
    nx0 = x0
    while nx0 < x1 - 1 and is_paper_col(nx0):
        nx0 += 1
    nx1 = x1 - 1
    while nx1 > nx0 and is_paper_col(nx1):
        nx1 -= 1
    return nx0, ny0, nx1 + 1, ny1 + 1


def isolate_slab(img: Image.Image, deskew: bool = True,
                 paper_margin: float = 0.0) -> Image.Image:
    """
    Use rembg (U2Net) to find the slab silhouette and crop the ORIGINAL
    image (paper background and all) tight to the slab's bbox. Deskew
    via the silhouette's min-area rotated rect. Returns RGB.

    The hybrid approach: rembg gives us a precise slab edge to crop
    against, but we keep a thin paper margin (~1.5% of bbox dims) so
    the slab plastic has natural contrast against the dark backdrop
    via the paper-to-backdrop transition. Trying to silhouette-cut the
    slab against transparency makes the translucent plastic blend into
    the aura — paper edges read crisp.

    `paper_margin` is the additional border in fractional bbox dims —
    just enough to keep ~1-2% paper visible around the slab without
    inflating into the surrounding scanner shadow.
    """
    from rembg import remove
    session = _get_rembg_session()
    rgba = remove(img.convert("RGB"), session=session)
    arr_rgba = np.asarray(rgba)
    alpha = arr_rgba[..., 3]

    arr_rgb = np.asarray(img.convert("RGB"))

    if deskew:
        mask_u8 = (alpha > 16).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            biggest = max(contours, key=cv2.contourArea)
            (cx, cy), (rw, rh), angle = cv2.minAreaRect(biggest)
            rotation = angle if rw < rh else (angle + 90 if angle < 0 else angle - 90)
            if abs(rotation) > 0.3:
                M = cv2.getRotationMatrix2D((cx, cy), rotation, 1.0)
                # Rotate alpha (for the bbox lookup) AND original RGB
                # (for the actual crop) by the same matrix so they stay
                # aligned. Pad RGB with white (paper) so rotation corners
                # blend into the natural paper background.
                alpha = cv2.warpAffine(
                    alpha, M, (alpha.shape[1], alpha.shape[0]),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=0,
                )
                arr_rgb = cv2.warpAffine(
                    arr_rgb, M, (arr_rgb.shape[1], arr_rgb.shape[0]),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255),
                )

    # Stage 1: rembg silhouette bbox — gives us a starting region that
    # contains the slab plus some paper around it. We INFLATE it so the
    # walk-inward step has paper on every side to walk through.
    mask_u8 = (alpha > 64).astype(np.uint8) * 255
    ys, xs = np.where(mask_u8 > 0)
    if len(xs) == 0:
        return Image.fromarray(arr_rgb, "RGB")
    H, W = arr_rgb.shape[:2]
    bx0, bx1 = int(xs.min()), int(xs.max()) + 1
    by0, by1 = int(ys.min()), int(ys.max()) + 1
    inflate = max(40, int(max(bx1 - bx0, by1 - by0) * 0.03))
    bx0 = max(0, bx0 - inflate)
    by0 = max(0, by0 - inflate)
    bx1 = min(W, bx1 + inflate)
    by1 = min(H, by1 + inflate)

    # Stage 2: walk each edge inward until the strip stops being
    # predominantly paper. Lands precisely on the slab plastic edge
    # — the slab's edge refraction and outline shadow both fail the
    # paper test, so the walk stops at the slab regardless of rembg's
    # silhouette accuracy.
    x0, y0, x1, y1 = _walk_inward_to_slab_edge(arr_rgb, bx0, by0, bx1, by1)

    # Optional paper_margin pulls the bbox back outward by a fraction
    # of bbox dims if any paper sliver is wanted. Default 0 — flush
    # to the slab edge.
    if paper_margin > 0:
        mx = int((x1 - x0) * paper_margin)
        my = int((y1 - y0) * paper_margin)
        x0 = max(0, x0 - mx)
        y0 = max(0, y0 - my)
        x1 = min(W, x1 + mx)
        y1 = min(H, y1 + my)

    # Stage 3: FIT A ROUNDED RECTANGLE to birefnet's silhouette. The
    # slab is geometrically a rounded rectangle (straight sides, rounded
    # corners) — convex hull alone preserves silhouette noise as wavy
    # edges. Fitting the actual geometry gives pixel-perfect straight
    # sides and smooth rounded corners. Corner radius is auto-detected
    # per-card from the silhouette so PSA's tight corners, BGS's rounder
    # corners, etc. all render correctly without per-slab tuning.
    rgb_crop = arr_rgb[y0:y1, x0:x1]
    alpha_crop = alpha[y0:y1, x0:x1]
    a_bin = (alpha_crop >= 128).astype(np.uint8) * 255

    h_crop, w_crop = a_bin.shape[:2]

    # Find the silhouette's tight bbox within the crop.
    sys_arr, sxs_arr = np.where(a_bin > 0)
    if len(sxs_arr) == 0:
        # No silhouette — fall back to the full crop as opaque.
        mask_out = np.full((h_crop, w_crop), 255, dtype=np.uint8)
    else:
        sx0 = int(sxs_arr.min())
        sx1 = int(sxs_arr.max()) + 1
        sy0 = int(sys_arr.min())
        sy1 = int(sys_arr.max()) + 1

        # Auto-detect corner radius via AREA DEFICIT. The silhouette of
        # a rounded rectangle has area = (W × H) − (4 corners × area
        # missing per corner). Each missing corner is the difference
        # between a corner square (R × R) and a quarter-circle (πR²/4),
        # so total missing = 4 × R²(1 − π/4) = R²(4 − π).
        # Solve: R = sqrt(missing_area / (4 − π))
        rect_w = sx1 - sx0
        rect_h = sy1 - sy0
        rect_area = rect_w * rect_h
        silhouette_area = int((a_bin[sy0:sy1, sx0:sx1] > 0).sum())
        missing = max(0, rect_area - silhouette_area)
        radius_area = int(np.sqrt(missing / (4 - np.pi))) if missing > 0 else 0

        # Sanity-clamp: corner radius shouldn't exceed ~10% of the
        # smaller dimension. Anything bigger means the silhouette
        # is missing area for some reason other than rounded corners
        # (noise, bites, holes); fall back to a conservative 3%.
        max_reasonable = int(min(rect_w, rect_h) * 0.10)
        if radius_area > max_reasonable or radius_area < 2:
            radius = max(2, int(min(rect_w, rect_h) * 0.03))
        else:
            radius = radius_area

        # Render the rounded rectangle as the alpha mask.
        mask_pil = Image.new("L", (w_crop, h_crop), 0)
        ImageDraw.Draw(mask_pil).rounded_rectangle(
            (sx0, sy0, sx1 - 1, sy1 - 1), radius=radius, fill=255,
        )
        mask_out = np.asarray(mask_pil).copy()

    # 0.6px Gaussian for anti-aliasing on the binary edge.
    mask_out = cv2.GaussianBlur(mask_out, (3, 3), 0.6)

    rgba_arr = np.dstack([rgb_crop, mask_out])
    return Image.fromarray(rgba_arr, "RGBA")


def upscale_rgba(img: Image.Image, scale: int = 4) -> Image.Image:
    """
    Upscale an RGBA image. Real-ESRGAN's pipeline runs RGB only, so we
    split the channels: RGB goes through Real-ESRGAN for the AI quality
    boost on card art, alpha goes through nearest-neighbor (it's already
    been hardened in isolate_slab to a binary mask, so we want to keep
    it binary through the upscale — LANCZOS would re-soften it).
    Recombine at the upscaled resolution.
    """
    if img.mode != "RGBA":
        return upscale_pil(img, scale=scale)
    rgb = img.convert("RGB")
    alpha = img.split()[3]
    rgb_up = upscale_pil(rgb, scale=scale)
    nw, nh = rgb_up.size
    # Nearest-neighbor preserves the hard binary edge from isolate_slab.
    alpha_up = alpha.resize((nw, nh), Image.NEAREST)
    # Tiny anti-alias pass after upscaling — 1px Gaussian smooths the
    # nearest-neighbor staircasing without re-introducing the feathered
    # halo that LANCZOS produces.
    alpha_up = alpha_up.filter(ImageFilter.GaussianBlur(radius=1.0))
    rgb_up.putalpha(alpha_up)
    return rgb_up

# Sake Kitty palette — pulled from main.js particle COLORS + hero blobs.
NAVY = (10, 10, 20)
ORANGE = (255, 106, 0)
PINK = (255, 0, 128)
PURPLE = (123, 47, 255)
CYAN = (0, 212, 255)
GOLD = (255, 204, 0)


# ---------- crop ---------------------------------------------------------- #

def _slab_contour_by_brightness(img: Image.Image) -> np.ndarray | None:
    """
    Primary slab detector — keys on "anything not paper-bright" via a
    fixed 240 threshold. Works on the overwhelming majority of scans
    where the paper is uniformly bright and the slab plastic darkens
    pixels even slightly via refraction.

    This is the original detector that produced the clean tight crops
    on the catalog. It's kept as the primary because the bbox lands on
    the actual slab outline (not the slab content), so no extra margin
    or refinement is strictly needed for these cards. Edge-refinement
    in crop_slab is still applied for safety.

    Falls through to _slab_contour_by_content when the paper background
    runs darker than 240 (vignetted scans, gray-cast scanners) — those
    were the failure mode that motivated the content detector.
    """
    arr = np.asarray(img.convert("L"))
    arr = cv2.GaussianBlur(arr, (5, 5), 0)
    _, mask = cv2.threshold(arr, 240, 255, cv2.THRESH_BINARY_INV)
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (45, 45))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_k)
    open_k = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_k)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    img_area = arr.shape[0] * arr.shape[1]
    best, best_score = None, 0.0
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if h == 0 or w == 0:
            continue
        bbox_area = w * h
        # The brightness mask catches scanner-edge vignette as one giant
        # blob covering nearly the full frame on some scans — reject
        # anything > 85% area so the dispatcher falls through to the
        # content detector for those.
        if bbox_area < img_area * 0.05 or bbox_area > img_area * 0.85:
            continue
        aspect = h / w
        if not (0.55 < aspect < 2.2):
            continue
        # Reject elongated shadow strips via minAreaRect aspect — same
        # guard the content detector uses.
        rect = cv2.minAreaRect(c)
        (_, _), (rw, rh), _ = rect
        if rw == 0 or rh == 0:
            continue
        rect_aspect = max(rw, rh) / min(rw, rh)
        if rect_aspect > 2.4:
            continue
        score = bbox_area * (1.0 - min(1.0, abs(aspect - 1.60) / 1.60))
        if score > best_score:
            best, best_score = c, score
    return best


def _slab_contour_by_content(img: Image.Image) -> np.ndarray | None:
    """
    Fallback slab detector — used when the paper is too gray for the
    brightness threshold to separate it from the slab. Keys on slab
    content (saturated pixels + dark text/edges) and morph-closes the
    label band into the card art so the slab interior reads as one blob.

    Bbox from this detector hits slab CONTENT, not the slab outline. The
    crop_slab edge-refinement step expands outward from this bbox until
    it leaves paper, so the final crop still hugs the slab edge.

    Filters tightened against three failure modes:
      1. Scanner-edge vignette / shadow strips: rejected by minAreaRect
         aspect (rect-aspect > 2.4 is too elongated for a slab).
      2. L-shaped or hollow blobs: rejected by contour-fill ratio.
      3. Inner card contour outscoring the slab: scoring uses contour
         area (slab content fills its bbox after the close).
    """
    rgb = np.asarray(img.convert("RGB"))
    L = np.asarray(img.convert("L"))
    L = cv2.GaussianBlur(L, (7, 7), 0)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[..., 1]

    mask_sat = (sat > 25).astype(np.uint8) * 255
    mask_dark = (L < 150).astype(np.uint8) * 255
    mask = cv2.bitwise_or(mask_sat, mask_dark)

    open_k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_k)
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (251, 251))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_k)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    img_area = L.shape[0] * L.shape[1]
    best, best_score = None, 0.0
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w == 0 or h == 0:
            continue
        ba = w * h
        if ba < img_area * 0.05 or ba > img_area * 0.85:
            continue
        rect = cv2.minAreaRect(c)
        (_, _), (rw, rh), _ = rect
        if rw == 0 or rh == 0:
            continue
        rect_aspect = max(rw, rh) / min(rw, rh)
        if rect_aspect > 2.4:
            continue
        c_area = cv2.contourArea(c)
        if c_area / max(rw * rh, 1) < 0.55:
            continue
        score = c_area * (1.0 - min(1.0, abs(rect_aspect - 1.6) / 2.0))
        if score > best_score:
            best, best_score = c, score
    return best


def _slab_contour_by_saturation(img: Image.Image) -> np.ndarray | None:
    """
    Fallback slab detector for colored holders (PSA's orange / blue slabs)
    that tilt at an angle on the scanner.

    Canny on grayscale doesn't reliably close the edges of a heavily-tilted
    colored slab (the long edges break into diagonal slivers that won't
    merge through morphology). Saturation works because the slab plastic
    is highly saturated against essentially-zero-saturation paper, even
    when tilted. The Pokémon-back blue + orange slab plastic both register,
    closing into one blob through MORPH_CLOSE.
    """
    arr = np.asarray(img.convert("HSV"))
    sat = arr[..., 1]
    _, mask = cv2.threshold(sat, 60, 255, cv2.THRESH_BINARY)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (60, 60)),
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    img_area = arr.shape[0] * arr.shape[1]
    best, best_score = None, 0.0
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if h == 0 or w == 0: continue
        ba = w * h
        if ba < img_area * 0.05 or ba > img_area * 0.95: continue
        aspect = h / w
        if not (0.55 < aspect < 2.2): continue
        score = ba * (1.0 - min(1.0, abs(aspect - 1.60) / 1.60))
        if score > best_score:
            best, best_score = c, score
    return best


def _slab_contour(img: Image.Image) -> np.ndarray | None:
    """
    Find the slab's outer contour.

    Strategy: brightness-threshold first (most reliable on the white-paper
    scanner background), Canny-edge as a fallback for cases where the slab
    plastic blends too closely with the paper, saturation-based as a
    last-ditch fallback for heavily-tilted colored holders.

    The Canny path on its own had a failure mode where the inner card's
    high-contrast edges formed a more "closed" contour than the slab's
    faint plastic outline — so the algorithm cropped the label off and
    kept just the card art. Brightness keys on the entire slab darkness
    against paper, so it doesn't get fooled by tighter inner edges.
    """
    primary = _slab_contour_by_brightness(img)
    if primary is not None:
        return primary

    # Brightness failed — paper is probably too gray. Try the content
    # detector before falling further down to Canny / saturation.
    content = _slab_contour_by_content(img)
    if content is not None:
        return content

    arr = np.asarray(img.convert("L"))
    arr = cv2.GaussianBlur(arr, (7, 7), 0)
    edges = cv2.Canny(arr, 30, 90)
    # Dilate to connect broken edge fragments along the slab perimeter.
    dilate_k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    edges = cv2.dilate(edges, dilate_k, iterations=2)
    # Close any remaining gaps so the perimeter is one ring.
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 35))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, close_k)
    # Erode back by roughly the dilation amount so the contour hugs the
    # actual slab edge instead of the inflated detection mask. Slight
    # under-erode (smaller kernel/iter than the dilate) keeps the slab
    # connected if there's any speckle in the perimeter.
    erode_k = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 13))
    edges = cv2.erode(edges, erode_k, iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    img_area = arr.shape[0] * arr.shape[1]
    best = None
    best_score = 0.0
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if h == 0 or w == 0:
            continue
        # Score by the bounding-rect area, not contour area: colored slabs
        # (PSA's orange/blue holders for high-value cards) trace a hollow
        # ring contour around the slab perimeter, which makes
        # cv2.contourArea report only the border thickness — well under
        # 1%. The bbox still captures the true slab footprint.
        bbox_area = w * h
        if bbox_area < img_area * 0.01 or bbox_area > img_area * 0.95:
            continue
        aspect = h / w
        # PSA slabs are ~1.3–1.55 tall:wide; allow 0.55–2.2 for either
        # orientation in case a card was scanned sideways.
        if not (0.55 < aspect < 2.2):
            continue
        # PSA slabs are 3.62" × 5.81" (aspect ≈ 1.60). The card inside is
        # 2.48" × 3.46" (aspect ≈ 1.39). With clean slab edges the outer
        # slab is the only "external" contour, but on some scans (older
        # PSA labels, low-contrast plastic) both the slab AND the inner
        # card register as separate externals. Tuning the ideal aspect to
        # the slab (not the card) ensures the larger slab outscores the
        # card even when both pass the filter.
        ideal_aspect = 1.60
        score = bbox_area * (1.0 - min(1.0, abs(aspect - ideal_aspect) / ideal_aspect))
        if score > best_score:
            best_score = score
            best = c
    if best is not None:
        return best
    # Canny+morph found nothing usable — fall back to saturation-based
    # detection for colored / heavily-tilted slabs.
    return _slab_contour_by_saturation(img)


def _refine_to_slab_edge(rotated: np.ndarray,
                         x: int, y: int, w: int, h: int,
                         search_pct: float = 0.18) -> tuple[int, int, int, int]:
    """
    Given a content-keyed bbox (which captures slab content but may stop
    short of the empty plastic strips), expand outward by `search_pct`
    of the bbox dimensions and then walk back inward from each edge
    until we leave paper.

    "Paper" = high brightness AND near-zero saturation. This test is
    stable regardless of slab color: clear PSA plastic, colored CGC
    pearl, BGS holographic gold, and rainbow holders all have either
    saturation, refraction-darkening, or some content that registers as
    "not paper". Walking inward stops at the slab outer edge precisely,
    which means no white halo on the composited backdrop AND no clipped
    plastic strips.

    Returns refined (x, y, w, h) clipped to the rotated frame.
    """
    H, W = rotated.shape[:2]
    L = cv2.cvtColor(rotated, cv2.COLOR_RGB2GRAY) if rotated.ndim == 3 else rotated
    if rotated.ndim == 3:
        hsv = cv2.cvtColor(rotated, cv2.COLOR_RGB2HSV)
        sat = hsv[..., 1]
    else:
        sat = np.zeros_like(L)

    # Inflate bbox to give the inward walk some slack at each edge.
    mx = int(w * search_pct)
    my = int(h * search_pct)
    x0 = max(0, x - mx)
    y0 = max(0, y - my)
    x1 = min(W, x + w + mx)
    y1 = min(H, y + h + my)

    # "Mostly paper" test: bright AND unsaturated for >70% of the strip.
    # 70% — not 100% — so a single dust speck or scanner artifact in an
    # otherwise-paper row doesn't accidentally extend the bbox outward.
    paper_thresh_v = 232
    paper_thresh_s = 14
    occupancy = 0.70

    def is_paper_row(r: int) -> bool:
        L_strip = L[r, x0:x1]
        s_strip = sat[r, x0:x1]
        return float(np.mean((L_strip > paper_thresh_v) & (s_strip < paper_thresh_s))) > occupancy

    def is_paper_col(c: int) -> bool:
        L_strip = L[y0:y1, c]
        s_strip = sat[y0:y1, c]
        return float(np.mean((L_strip > paper_thresh_v) & (s_strip < paper_thresh_s))) > occupancy

    # Walk top edge down until we hit slab.
    ny0 = y0
    while ny0 < y1 - 1 and is_paper_row(ny0):
        ny0 += 1
    # Walk bottom edge up.
    ny1 = y1 - 1
    while ny1 > ny0 and is_paper_row(ny1):
        ny1 -= 1
    # Walk left edge right.
    nx0 = x0
    while nx0 < x1 - 1 and is_paper_col(nx0):
        nx0 += 1
    # Walk right edge left.
    nx1 = x1 - 1
    while nx1 > nx0 and is_paper_col(nx1):
        nx1 -= 1

    return nx0, ny0, max(1, nx1 - nx0 + 1), max(1, ny1 - ny0 + 1)


def crop_slab(img: Image.Image, pad: int = 0) -> Image.Image:
    """
    Find the slab, deskew (rotate to level), refine the bbox to the
    actual slab edge, and crop.

    Detection is two-stage:
      1. Content-keyed contour finds the slab content (label + card).
      2. Edge-refinement walks outward from that bbox and back in until
         it leaves paper, locking the bbox to the true slab outline —
         including the empty plastic strips at top/bottom of clear PSA
         holders that step 1 misses, while NOT inflating into the white
         paper background on slabs where step 1 already covered the
         plastic edge (rainbow holders, colored slabs).

    `pad` is an optional fixed-pixel cushion (defaults to 0 since the
    refinement step is tight to the slab — adding a pad here puts paper
    back into the crop). Kept as a knob for callers that want a small
    breathing room.

    If detection fails entirely, returns the original image.
    """
    contour = _slab_contour(img)
    if contour is None:
        return img

    rect = cv2.minAreaRect(contour)
    (cx, cy), (rw, rh), angle = rect

    if rw < rh:
        rotation = angle
    else:
        rotation = angle + 90 if angle < 0 else angle - 90

    arr = np.array(img)
    h, w = arr.shape[:2]

    if abs(rotation) > 0.3:
        M = cv2.getRotationMatrix2D((cx, cy), rotation, 1.0)
        rotated = cv2.warpAffine(
            arr, M, (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255),
        )
        rotated_pil = Image.fromarray(rotated)
        contour = _slab_contour(rotated_pil)
        if contour is None:
            return rotated_pil
        x, y, ww, hh = cv2.boundingRect(contour)
    else:
        rotated = arr
        x, y, ww, hh = cv2.boundingRect(contour)

    # Refine to the actual slab edge.
    x, y, ww, hh = _refine_to_slab_edge(rotated, x, y, ww, hh)

    # Optional fixed-pixel cushion (default 0 keeps the crop flush).
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(w, x + ww + pad)
    y1 = min(h, y + hh + pad)
    return Image.fromarray(rotated[y0:y1, x0:x1])


# Legacy alias kept for any caller that still imports it.
def find_slab_bbox(img: Image.Image, pad: int = 24):
    contour = _slab_contour(img)
    if contour is None:
        return None
    x, y, w, h = cv2.boundingRect(contour)
    H, W = np.asarray(img).shape[:2]
    return (max(0, x - pad), max(0, y - pad),
            min(W, x + w + pad), min(H, y + h + pad))


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
    Build a soft drop shadow for the slab.

    If the slab is RGBA (rembg silhouette), the shadow is shaped by the
    slab's alpha so it follows the slab outline. For RGB inputs we fall
    back to a rectangular shadow for the slab footprint.
    """
    w, h = slab.size
    pad = blur * 2

    if slab.mode == "RGBA":
        alpha = slab.split()[3]
        shadow = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        # Tint the alpha with black at the requested opacity.
        tint = Image.new("RGBA", (w, h), (0, 0, 0, int(255 * opacity)))
        tint.putalpha(alpha.point(lambda v: int(v * opacity)))
        shadow.paste(tint, (pad, pad), tint)
    else:
        shadow = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rectangle(
            (pad, pad, pad + w, pad + h),
            fill=(0, 0, 0, int(255 * opacity)),
        )

    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur))
    return shadow


def compose(slab: Image.Image, canvas_size: tuple[int, int] = (4096, 4096),
            scale: float = 0.86,
            palette_override: list[tuple[int, int, int]] | None = None,
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

    if slab.mode == "RGBA":
        # LANCZOS downsample of a binary alpha re-feathers the edge —
        # downsample RGB with LANCZOS for smooth card-art rescale, alpha
        # with BILINEAR (preserves edge sharpness better than LANCZOS at
        # downscale) followed by a hardness re-pass.
        rgb_resized = slab.convert("RGB").resize((target_w, target_h), Image.LANCZOS)
        alpha_resized = slab.split()[3].resize((target_w, target_h), Image.BILINEAR)
        # Re-threshold to keep the slab edge crisp on the backdrop.
        a_arr = np.asarray(alpha_resized)
        a_hard = (a_arr >= 128).astype(np.uint8) * 255
        a_hard = cv2.GaussianBlur(a_hard, (3, 3), 0.6)
        slab_resized = rgb_resized.convert("RGBA")
        slab_resized.putalpha(Image.fromarray(a_hard))
    else:
        slab_resized = slab.resize((target_w, target_h), Image.LANCZOS)
    # Output sharpening — two passes at different scales:
    #   1) Broad pass (radius 2.5) tightens card art edges, label borders.
    #   2) Fine pass (radius 0.8) pulls small text out of the holo
    #      surface — cert number, QR code, label barcode are 8-10px on
    #      the source scan and lose contrast through the upscale chain.
    # Run sharpening on RGB only — sharpening the alpha channel of an
    # rembg silhouette would amplify edge aliasing and produce a
    # crunchy outline around the slab on the backdrop.
    if slab_resized.mode == "RGBA":
        rgb_part = slab_resized.convert("RGB")
        alpha_part = slab_resized.split()[3]
        rgb_part = rgb_part.filter(
            ImageFilter.UnsharpMask(radius=2.5, percent=170, threshold=2)
        )
        rgb_part = rgb_part.filter(
            ImageFilter.UnsharpMask(radius=0.8, percent=110, threshold=1)
        )
        rgb_part.putalpha(alpha_part)
        slab_resized = rgb_part
    else:
        slab_resized = slab_resized.filter(
            ImageFilter.UnsharpMask(radius=2.5, percent=170, threshold=2)
        )
        slab_resized = slab_resized.filter(
            ImageFilter.UnsharpMask(radius=0.8, percent=110, threshold=1)
        )

    # Aura: multi-layer glow tinted to harmonize with this card's art.
    palette = palette_override if palette_override else extract_palette(slab_resized, n=3)
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

    # Slab edge halo — slab plastic is translucent gray and blends into the
    # bright aura behind it, making the silhouette read as soft. Pasting a
    # slightly dilated dark version of the silhouette BEHIND the slab gives
    # a hard outline ring (3-4px) that visually separates slab from aura
    # without changing the slab pixels themselves.
    if slab_resized.mode == "RGBA":
        a = np.asarray(slab_resized.split()[3])
        # Dilate the alpha by ~4px to get a halo ring
        dilate_k = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        a_dilated = cv2.dilate(a, dilate_k, iterations=1)
        # Use the dilated alpha (at moderate opacity) as a deep-navy stamp
        halo = np.zeros((target_h, target_w, 4), dtype=np.uint8)
        halo[..., 0] = 5    # near-black with a hint of navy
        halo[..., 1] = 5
        halo[..., 2] = 15
        halo[..., 3] = (a_dilated.astype(np.float32) * 0.78).astype(np.uint8)
        halo_img = Image.fromarray(halo, "RGBA")
        # Slight blur so the outline ring isn't crisp-jagged.
        halo_img = halo_img.filter(ImageFilter.GaussianBlur(radius=1.2))
        ph_x = (cw - target_w) // 2
        ph_y = (ch - target_h) // 2
        bg.paste(halo_img, (ph_x, ph_y), halo_img)

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
                out_name: str | None = None,
                palette_override: list[tuple[int, int, int]] | None = None,
                upscale: int = 4,
                ) -> tuple[Path, list[tuple[int, int, int]]]:
    """
    Run the full image pipeline on a single scan.

    `palette_override` lets callers force a specific 3-color palette —
    used by process_inbox to make sure the back of a card uses the same
    glow + wordmark colors as its front.

    `upscale` runs Real-ESRGAN on the cropped slab before composition so
    the final downscale to the canvas keeps more fine detail than a raw
    600 DPI scan provides. Set to 1 to skip. Falls back to LANCZOS if the
    upscaler binary isn't installed.

    Returns (output_path, palette_used) so callers can chain.
    """
    img = Image.open(src).convert("RGB")
    # rembg removes paper background → RGBA silhouette, deskewed + tight-cropped.
    # Falls back to the bbox crop if rembg isn't available so the pipeline
    # still runs on a misconfigured machine.
    try:
        cropped = isolate_slab(img)
    except Exception as e:
        print(f"    [rembg] {e} — falling back to bbox crop")
        cropped = crop_slab(img)
    if upscale and upscale > 1:
        before = cropped.size
        cropped = upscale_rgba(cropped, scale=upscale)
        print(f"    upscaled {before} -> {cropped.size} (x{upscale})")
    finished, _slab_rect, palette = compose(cropped, palette_override=palette_override)
    finished = add_wordmark(finished, colors=palette)
    name = out_name or f"{src.stem}_processed.jpg"
    out_path = out_dir / name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    finished.save(out_path, "JPEG", quality=97)
    print(f"  {src.name} -> {out_path.name}  "
          f"(crop {cropped.size}, out {finished.size})")
    return out_path, palette


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
        process_one(src, args.out)  # standalone CLI; palette per image is fine


if __name__ == "__main__":
    main()
