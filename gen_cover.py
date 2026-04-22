from PIL import Image, ImageDraw, ImageFilter, ImageFont
import os

W, H = 1500, 500
out_path = os.path.join(os.path.dirname(__file__), "cover-image.png")
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

# Orange/pink glow — top left
blob1 = radial_blob(700, "#ff4e00", "#ff0080")
img.paste(blob1, (-200, -250), blob1)

# Blue/cyan glow — bottom right
blob2 = radial_blob(600, "#3a00ff", "#00d4ff")
img.paste(blob2, (W - 400, H - 350), blob2)

# Purple center bloom
blob3 = radial_blob(450, "#7b2fff", "#ff0080")
img.paste(blob3, (W // 2 - 225, H // 2 - 225), blob3)

# Logo — left side
logo = Image.open(logo_path).convert("RGBA")
logo_size = 360
logo = logo.resize((logo_size, logo_size), Image.LANCZOS)

logo_x = 90
logo_y = (H - logo_size) // 2

# Glow ring behind logo
glow = Image.new("RGBA", (logo_size + 60, logo_size + 60), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([0, 0, logo_size + 60, logo_size + 60], fill=(255, 106, 0, 70))
glow = glow.filter(ImageFilter.GaussianBlur(25))
img.paste(glow, (logo_x - 30, logo_y - 30), glow)

img.paste(logo, (logo_x, logo_y), logo)

# Text — right side
try:
    font_brand = ImageFont.truetype("C:/Windows/Fonts/ariblk.ttf", 72)
    font_tag   = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 22)
    font_url   = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 20)
except:
    font_brand = ImageFont.load_default()
    font_tag   = font_brand
    font_url   = font_brand

text_x = logo_x + logo_size + 70
text_y = H // 2 - 110

# Brand name — two lines
for line_i, line in enumerate(["SAKE KITTY", "CARDS"]):
    ly = text_y + line_i * 80
    for offset in range(4, 0, -1):
        draw.text((text_x + offset, ly + offset), line,
                  font=font_brand, fill=(255, 106, 0, 30))
    draw.text((text_x, ly), line, font=font_brand, fill="#ff6a00")

# Tagline
draw.text((text_x, text_y + 180),
          "POKEMON CARDS  ·  SINGLES  ·  SEALED  ·  EVENTS",
          font=font_tag, fill=(255, 255, 255, 200))

# Divider
div_y = text_y + 220
draw.rectangle([text_x, div_y, text_x + 220, div_y + 3], fill="#7b2fff")

# URL
draw.text((text_x, div_y + 18), "sakekittycards.com",
          font=font_url, fill=(255, 255, 255, 140))

img.save(out_path, "PNG", optimize=True)
print(f"Saved: {out_path}")
