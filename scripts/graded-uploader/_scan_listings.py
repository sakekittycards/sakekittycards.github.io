import urllib.request, json, io, os
from PIL import Image, ImageDraw, ImageFont

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36'}
d = json.loads(urllib.request.urlopen(urllib.request.Request(
    'https://sakekitty-square.nwilliams23999.workers.dev/items', headers=UA), timeout=90).read())
items = d.get('items') or d.get('objects') or d
singles = [i for i in items if 'Card ID:' in (i.get('description') or '')]
print('singles found:', len(singles))

def img_url(i):
    for k in ('image', 'imageUrl'):
        if i.get(k):
            return i[k]
    imgs = i.get('images')
    if isinstance(imgs, list) and imgs:
        return imgs[0] if isinstance(imgs[0], str) else imgs[0].get('url')
    return None

# sort by name for stable order
singles.sort(key=lambda i: i.get('name', ''))
cells = []
noimg = []
for i in singles:
    u = img_url(i)
    name = (i.get('name') or '')[:42]
    if not u:
        noimg.append(name)
        cells.append((None, name))
        continue
    try:
        b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()
        im = Image.open(io.BytesIO(b)).convert('RGB')
        cells.append((im, name))
    except Exception as e:
        cells.append((None, name + ' [DL ERR]'))

print('no-image listings:', noimg)

# build contact sheets: 5 cols, thumb 240x335 + label band
COLS, TW, TH, LBL = 5, 240, 335, 28
import math
per_sheet = COLS * 4  # 20 per sheet
sheets = math.ceil(len(cells) / per_sheet)
os.makedirs('_scan', exist_ok=True)
for s in range(sheets):
    chunk = cells[s*per_sheet:(s+1)*per_sheet]
    rows = math.ceil(len(chunk) / COLS)
    W = COLS * TW
    H = rows * (TH + LBL)
    sheet = Image.new('RGB', (W, H), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for idx, (im, name) in enumerate(chunk):
        r, c = divmod(idx, COLS)
        x, y = c * TW, r * (TH + LBL)
        if im:
            t = im.copy(); t.thumbnail((TW - 8, TH - 8))
            sheet.paste(t, (x + (TW - t.width)//2, y + 4))
        else:
            draw.rectangle([x+4, y+4, x+TW-4, y+TH-4], outline=(200,0,0), width=2)
            draw.text((x+12, y+TH//2), 'IMAGELESS', fill=(200,0,0))
        draw.text((x + 4, y + TH + 6), name, fill=(0, 0, 0))
    out = f'_scan/sheet_{s+1}.png'
    sheet.save(out)
    print('saved', out, sheet.size, 'cards', len(chunk))
