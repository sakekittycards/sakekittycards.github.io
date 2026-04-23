"""
Generate a seamless-loop hologram-fan video of the Sake Kitty logo.

Effect: rainbow hue cycle + gentle pulse/brightness throb on the centered
logo, with the home-page sparkle particles drifting upward around it.
Pure black background (fan treats black as LEDs-off / invisible).

Output: ../sake-kitty-hologram.mp4 on the Desktop by default.
Tweak CANVAS / LOOP_SEC / FPS / output_path below for a different fan.
"""
import math
import os
import random
import subprocess
import sys
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

# ─── Config ────────────────────────────────────────────────────────────────
CANVAS      = 640            # output resolution (square)
LOOP_SEC    = 24             # loop length
FPS         = 30
LOGO_BASE   = 440            # rendered logo size (leaves room for particles)
NUM_PARTS   = 40             # particle count (home page uses 60 across a wide viewport)

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
def main():
    logo_base = logo_with_black_transparent(LOGO_PATH, LOGO_BASE)
    particles = [Particle() for _ in range(NUM_PARTS)]

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

            logo_hued = hue_rotate(logo_base, hue_deg)
            size = int(LOGO_BASE * pulse)
            logo_scaled = logo_hued.resize((size, size), Image.LANCZOS)
            logo_bright = ImageEnhance.Brightness(logo_scaled).enhance(brightness)

            # Fresh black canvas (RGBA for compositing, will flatten to RGB at end)
            canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 255))

            # Particle glow layer (blurred) + cores
            glow  = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
            cores = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
            gdraw = ImageDraw.Draw(glow)
            cdraw = ImageDraw.Draw(cores)
            for p in particles:
                prog = (t_frac + p.phase) % 1.0
                a    = p.alpha(prog)
                if a <= 0: continue
                x, y = p.pos(prog)
                glow_r = p.r * 5
                gdraw.ellipse((x - glow_r, y - glow_r, x + glow_r, y + glow_r),
                              fill=(*p.color, int(a * 110)))
                cdraw.ellipse((x - p.r, y - p.r, x + p.r, y + p.r),
                              fill=(*p.color, int(a * 255)))
            glow_blurred = glow.filter(ImageFilter.GaussianBlur(radius=8))

            # Composite order: black → glow → logo → cores
            canvas = Image.alpha_composite(canvas, glow_blurred)
            lx = (CANVAS - size) // 2
            ly = (CANVAS - size) // 2
            canvas.alpha_composite(logo_bright, (lx, ly))
            canvas.alpha_composite(cores)

            ffmpeg.stdin.write(canvas.convert('RGB').tobytes())

            if f % 30 == 0:
                print(f'  frame {f}/{TOTAL_FRAMES}', flush=True)
    finally:
        ffmpeg.stdin.close()
        ret = ffmpeg.wait()
    if ret != 0:
        sys.exit(f'ffmpeg exited {ret}')
    print(f'\nwritten: {OUT_PATH}')

if __name__ == '__main__':
    main()
