from PIL import Image, ImageDraw, ImageFilter, ImageFont
import math, os

W, H = 1200, 630
out_path = os.path.join(os.path.dirname(__file__), "og-image.png")
logo_path = os.path.join(os.path.dirname(__file__), "logo.png")

img = Image.new("RGB", (W, H), "#060608")
draw = ImageDraw.Draw(img)

def radial_blob(size, color_inner, color_outer):
    blob = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob)
    steps = 80
    r_inner = tuple(int(color_inner[i:i+2], 16) for i in (1, 3, 5))
    r_outer = tuple(int(color_outer[i:i+2], 16) for i in (1, 3, 5))
    for i in range(steps, 0, -1):
        t = i / steps
        r = tuple(int(r_inner[j] * t + r_outer[j] * (1 - t)) for j in range(3))
        alpha = int(180 * t)
        radius = int(size / 2 * t)
        cx, cy = size // 2, size // 2
        bd.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                   fill=(*r, alpha))
    return blob.filter(ImageFilter.GaussianBlur(size // 6))

# Orange/pink blob — top left
blob1 = radial_blob(700, "#ff4e00", "#ff0080")
img.paste(blob1, (-180, -180), blob1)

# Blue/cyan blob — bottom right
blob2 = radial_blob(600, "#3a00ff", "#00d4ff")
img.paste(blob2, (W - 420, H - 420), blob2)

# Purple center bloom
blob3 = radial_blob(400, "#7b2fff", "#ff0080")
img.paste(blob3, (W // 2 - 200, H // 2 - 200), blob3)

# Logo — left-of-center
logo = Image.open(logo_path).convert("RGBA")
logo_size = 320
logo = logo.resize((logo_size, logo_size), Image.LANCZOS)

logo_x = 100
logo_y = (H - logo_size) // 2

# Glow ring behind logo
glow = Image.new("RGBA", (logo_size + 40, logo_size + 40), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([0, 0, logo_size + 40, logo_size + 40], fill=(255, 106, 0, 60))
glow = glow.filter(ImageFilter.GaussianBlur(20))
img.paste(glow, (logo_x - 20, logo_y - 20), glow)

img.paste(logo, (logo_x, logo_y), logo)

# Text — right side
try:
    font_sub   = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 28)
    font_url   = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
except:
    font_sub   = ImageFont.load_default()
    font_url   = font_sub

text_x = logo_x + logo_size + 60
text_y_start = H // 2 - 130

try:
    font_title = ImageFont.truetype("C:/Windows/Fonts/ariblk.ttf", 78)
except:
    font_title = ImageFont.load_default()

# Two lines — "POKÉMON / CARDS"
for line_i, line in enumerate(["POKEMON", "CARDS"]):
    ly = text_y_start + line_i * 86
    for offset in range(4, 0, -1):
        draw.text((text_x + offset, ly + offset), line,
                  font=font_title, fill=(255, 106, 0, 30))
    draw.text((text_x, ly), line, font=font_title, fill="#ff6a00")

# Tagline
draw.text((text_x, text_y_start + 190), "SINGLES · SEALED · EVENTS",
          font=font_sub, fill=(255, 255, 255, 160))

# Divider line
div_y = text_y_start + 230
draw.rectangle([text_x, div_y, text_x + 200, div_y + 3], fill="#7b2fff")

# URL
draw.text((text_x, div_y + 16), "sakekittycards.com",
          font=font_url, fill=(255, 255, 255, 90))

img.save(out_path, "PNG", optimize=True)
print(f"Saved: {out_path}")
