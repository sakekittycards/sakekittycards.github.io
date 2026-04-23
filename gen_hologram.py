"""
Generate a seamless-loop hologram-fan video of the Sake Kitty logo.

Effect stack on pure black:
  - rainbow hue cycle on the logo (one full revolution per loop)
  - gentle pulse + brightness throb (2s period)
  - subtle Y-axis rocking tilt (horizontal squash, 12s period)
  - 5 stars orbiting the logo on an elliptical path with depth-faked
    brightness/size (brighter+bigger in front, dim+small behind logo)
  - 40 drifting sparkle particles (ported from home page particle system)

Pure black background (fan treats black as LEDs-off / invisible).

Output: ~/OneDrive/Desktop/sake-kitty-hologram.mp4 by default.
Tweak CANVAS / LOOP_SEC / FPS / output_path below for a different fan.
"""
import math
import os
import random
import subprocess
import sys
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

# ─── Config ────────────────────────────────────────────────────────────────
CANVAS         = 640          # output resolution (square)
LOOP_SEC       = 24           # loop length (also = one full rainbow cycle)
FPS            = 30
LOGO_BASE      = 440          # rendered logo size
NUM_PARTS      = 40           # drifting particles (home-page port)
NUM_ORBITERS   = 5            # orbiting stars
ORBIT_RADIUS_X = 250          # ellipse semi-major (horizontal)
ORBIT_RADIUS_Y = 70           # ellipse semi-minor (vertical) — flat ellipse fakes depth
TILT_MAX_DEG   = 22           # max rocking angle (±)
TILT_PERIOD    = 12           # seconds per full tilt cycle

# Home-page palette
PARTICLE_COLORS = [
    (255, 106,   0),   # orange
    (255,   0, 128),   # pink
    (123,  47, 255),   # purple
    (  0, 212, 255),   # cyan
    (255, 255, 255),   # white
    (255, 204,   0),   # gold
]

HERE       = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH  = os.path.join(HERE, 'logo.png')
OUT_PATH   = os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop', 'sake-kitty-hologram.mp4')

TOTAL_FRAMES = LOOP_SEC * FPS
random.seed(42)   # deterministic particle layout

# ─── Particle system (ported from main.js tick loop) ───────────────────────
class Particle:
    """One particle cycles through its full life in exactly LOOP_SEC."""
    def __init__(self):
        self.phase         = random.random()                        # 0..1 offset
        self.x0            = random.uniform(0, CANVAS)
        self.x_drift       = random.uniform(-40, 40)
        self.y0            = random.uniform(CANVAS * 0.55, CANVAS + 30)
        self.y_travel      = random.uniform(160, 460)               # pixels traveled up over loop
        self.r             = random.uniform(1.4, 3.6)
        self.color         = random.choice(PARTICLE_COLORS)
        self.twinkle_freq  = random.uniform(3, 7)                   # cycles per loop
        self.twinkle_phase = random.uniform(0, 2 * math.pi)

    def pos(self, prog):
        x = self.x0 + self.x_drift * prog
        y = self.y0 - self.y_travel * prog
        return x, y

    def alpha(self, prog):
        # fade-in first 20%, fade-out last 25%, twinkle on top
        if   prog < 0.2:  fade = prog / 0.2
        elif prog > 0.75: fade = (1 - prog) / 0.25
        else:             fade = 1.0
        twinkle = 0.6 + 0.4 * math.sin(self.twinkle_freq * 2 * math.pi * prog + self.twinkle_phase)
        return max(0.0, min(1.0, fade * twinkle * 0.85))

# ─── Orbiter stars (depth-faked) ───────────────────────────────────────────
class Orbiter:
    """Star on an elliptical path around the logo center. One revolution per loop."""
    def __init__(self, idx, total):
        # Evenly-spaced phases so stars are distributed around the ellipse.
        self.phase = idx / total
        self.r     = random.uniform(6, 9.5)
        self.color = PARTICLE_COLORS[idx % len(PARTICLE_COLORS)]

    def sample(self, t_frac):
        theta = 2 * math.pi * ((t_frac + self.phase) % 1.0)
        x = CANVAS / 2 + ORBIT_RADIUS_X * math.cos(theta)
        y = CANVAS / 2 + ORBIT_RADIUS_Y * math.sin(theta)
        z = math.sin(theta)              # -1 (back) … +1 (front)
        depth_t = (z + 1) / 2            # 0 back, 1 front
        scale      = 0.55 + 0.75 * depth_t   # 0.55 back → 1.30 front
        brightness = 0.25 + 0.75 * depth_t   # 0.25 back → 1.00 front
        return x, y, z, scale, brightness

def star_points(cx, cy, r_outer, r_inner, tilt=math.pi / 2):
    """Return 10 vertices of a 5-pointed star centered on (cx, cy)."""
    pts = []
    for i in range(10):
        angle = tilt + i * math.pi / 5
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy - r * math.sin(angle)))
    return pts

# ─── Image helpers ─────────────────────────────────────────────────────────
def hue_rotate(im_rgba, degrees):
    """Rotate hue by `degrees` while preserving alpha."""
    r, g, b, a = im_rgba.split()
    hsv = Image.merge('RGB', (r, g, b)).convert('HSV')
    h, s, v = hsv.split()
    shift = int(degrees * 255 / 360) % 256
    h = h.point(lambda px, s=shift: (px + s) & 0xff)
    rgb = Image.merge('HSV', (h, s, v)).convert('RGB')
    r2, g2, b2 = rgb.split()
    return Image.merge('RGBA', (r2, g2, b2, a))

def logo_with_black_transparent(path, size):
    """Load logo.png, derive alpha from max(r,g,b) so pure black = transparent."""
    im = Image.open(path).convert('RGBA').resize((size, size), Image.LANCZOS)
    r, g, b, _ = im.split()
    alpha = ImageChops.lighter(ImageChops.lighter(r, g), b)
    im.putalpha(alpha)
    return im

# ─── Render ────────────────────────────────────────────────────────────────
def draw_orbiter(glow_draw, core_draw, x, y, r, color, brightness):
    """Draw an orbiter on the given glow (blurred) and core (crisp) layers."""
    # Soft glow halo
    glow_r = r * 3.2
    glow_draw.ellipse((x - glow_r, y - glow_r, x + glow_r, y + glow_r),
                      fill=(*color, int(brightness * 130)))
    # Crisp 5-pointed star
    core_draw.polygon(star_points(x, y, r, r * 0.42),
                      fill=(*color, int(brightness * 240)))

def main():
    logo_base = logo_with_black_transparent(LOGO_PATH, LOGO_BASE)
    particles = [Particle() for _ in range(NUM_PARTS)]
    orbiters  = [Orbiter(i, NUM_ORBITERS) for i in range(NUM_ORBITERS)]

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    ffmpeg = subprocess.Popen([
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24',
        '-s', f'{CANVAS}x{CANVAS}', '-r', str(FPS),
        '-i', '-',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-preset', 'slow', '-crf', '16',
        '-movflags', '+faststart',
        OUT_PATH,
    ], stdin=subprocess.PIPE)

    try:
        for f in range(TOTAL_FRAMES):
            t      = f / FPS
            t_frac = t / LOOP_SEC

            # Logo transforms
            hue_deg    = t_frac * 360
            pulse      = 1.0 + 0.06 * math.sin(2 * math.pi * t / 2)    # 2s pulse
            brightness = 1.0 + 0.14 * math.sin(2 * math.pi * t / 2)
            tilt_deg   = TILT_MAX_DEG * math.sin(2 * math.pi * t / TILT_PERIOD)
            squash     = math.cos(math.radians(tilt_deg))              # horizontal scale

            logo_hued   = hue_rotate(logo_base, hue_deg)
            size        = int(LOGO_BASE * pulse)
            logo_scaled = logo_hued.resize((size, size), Image.LANCZOS)
            logo_bright = ImageEnhance.Brightness(logo_scaled).enhance(brightness)
            # Y-axis rocking via horizontal squash
            tilted_w    = max(1, int(size * squash))
            logo_tilted = logo_bright.resize((tilted_w, size), Image.LANCZOS)

            # Fresh black canvas (RGBA for compositing, will flatten to RGB at end)
            canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 255))

            # Drifting particles — glow layer (blurred) + cores
            drift_glow  = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
            drift_cores = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
            dg_draw = ImageDraw.Draw(drift_glow)
            dc_draw = ImageDraw.Draw(drift_cores)
            for p in particles:
                prog = (t_frac + p.phase) % 1.0
                a    = p.alpha(prog)
                if a <= 0: continue
                x, y = p.pos(prog)
                glow_r = p.r * 5
                dg_draw.ellipse((x - glow_r, y - glow_r, x + glow_r, y + glow_r),
                                fill=(*p.color, int(a * 110)))
                dc_draw.ellipse((x - p.r, y - p.r, x + p.r, y + p.r),
                                fill=(*p.color, int(a * 255)))
            drift_glow_blurred = drift_glow.filter(ImageFilter.GaussianBlur(radius=8))

            # Orbiters — split into back (behind logo) and front (in front of logo)
            back_glow  = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
            back_core  = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
            front_glow = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
            front_core = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
            bg_draw, bc_draw = ImageDraw.Draw(back_glow),  ImageDraw.Draw(back_core)
            fg_draw, fc_draw = ImageDraw.Draw(front_glow), ImageDraw.Draw(front_core)
            for orb in orbiters:
                x, y, z, scale, bright = orb.sample(t_frac)
                if z < 0:
                    draw_orbiter(bg_draw, bc_draw, x, y, orb.r * scale, orb.color, bright)
                else:
                    draw_orbiter(fg_draw, fc_draw, x, y, orb.r * scale, orb.color, bright)
            back_glow_b  = back_glow.filter(ImageFilter.GaussianBlur(radius=5))
            front_glow_b = front_glow.filter(ImageFilter.GaussianBlur(radius=4))

            # Composite (back to front):
            #   black → drift glow → back orbiter glow → back orbiter core
            #         → logo → front orbiter glow → front orbiter core → drift cores
            canvas.alpha_composite(drift_glow_blurred)
            canvas.alpha_composite(back_glow_b)
            canvas.alpha_composite(back_core)
            lx = (CANVAS - tilted_w) // 2
            ly = (CANVAS - size) // 2
            canvas.alpha_composite(logo_tilted, (lx, ly))
            canvas.alpha_composite(front_glow_b)
            canvas.alpha_composite(front_core)
            canvas.alpha_composite(drift_cores)

            ffmpeg.stdin.write(canvas.convert('RGB').tobytes())

            if f % 60 == 0:
                print(f'  frame {f}/{TOTAL_FRAMES}', flush=True)
    finally:
        ffmpeg.stdin.close()
        ret = ffmpeg.wait()
    if ret != 0:
        sys.exit(f'ffmpeg exited {ret}')
    print(f'\nwritten: {OUT_PATH}')

if __name__ == '__main__':
    main()
