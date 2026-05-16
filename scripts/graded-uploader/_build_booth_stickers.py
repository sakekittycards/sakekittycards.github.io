"""Generate booth_stickers_<date>.csv (and .pdf) from pricing.csv.

Columns:
  cert    — PSA/CGC cert number (matches Square graded item)
  name    — "{year} {name} {set} #{number} {grade}" denormalized title
  sticker — current posted price (your_price in pricing.csv)
  floor   — walk-away price = sticker * 0.92, rounded to nearest $5

Pulls live prices from pricing.csv so it reflects every reprice +
competitive drop that has actually been pushed to Square.
"""
from __future__ import annotations
import csv
import datetime
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICING = HERE / 'pricing.csv'


def parse_price(s):
    s = (s or '').replace('[uploaded]', '').strip().lstrip('$').replace(',', '')
    try:
        return int(float(s))
    except Exception:
        return None


def round5(n):
    return int(round(n / 5.0) * 5)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    today = datetime.date.today().isoformat()
    out_csv = HERE / f'booth_stickers_{today}.csv'

    with PRICING.open('r', encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))

    out = []
    for r in rows:
        price = parse_price(r.get('your_price', ''))
        if price is None:
            continue
        title_parts = []
        if r.get('year'):
            title_parts.append(r['year'].strip())
        if r.get('name'):
            title_parts.append(r['name'].strip())
        if r.get('set'):
            title_parts.append(r['set'].strip())
        num = r.get('number', '').strip()
        if num:
            title_parts.append(f'#{num}' if not num.startswith('#') else num)
        if r.get('grade'):
            title_parts.append(r['grade'].strip())
        name = ' '.join(title_parts)
        floor = round5(price * 0.92)
        out.append({
            'cert': r['cert'].strip(),
            'name': name,
            'sticker': f'${price}',
            'floor': f'${floor}',
            '_sort': price,
        })

    out.sort(key=lambda x: -x['_sort'])

    with out_csv.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['cert', 'name', 'sticker', 'floor'])
        w.writeheader()
        for row in out:
            row.pop('_sort')
            w.writerow(row)

    total_sticker = sum(int(r['sticker'].lstrip('$')) for r in out)
    total_floor = sum(int(r['floor'].lstrip('$')) for r in out)
    print(f'Wrote {out_csv.name}')
    print(f'{len(out)} cards | sticker total ${total_sticker:,} | floor total ${total_floor:,}')

    # PDF
    try:
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError:
        print('(reportlab not installed — CSV only)')
        return 0

    out_pdf = HERE / f'booth_stickers_{today}.pdf'
    doc = SimpleDocTemplate(
        str(out_pdf), pagesize=landscape(letter),
        leftMargin=0.4 * inch, rightMargin=0.4 * inch,
        topMargin=0.4 * inch, bottomMargin=0.4 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('T', parent=styles['Title'], fontSize=16, spaceAfter=4)
    sub_style = ParagraphStyle('S', parent=styles['Normal'], fontSize=9, textColor=colors.grey, spaceAfter=8)
    cell = ParagraphStyle('C', parent=styles['Normal'], fontSize=8, leading=10)

    elements = [
        Paragraph(f'Sake Kitty Cards — Booth Stickers ({today})', title_style),
        Paragraph(
            f'{len(out)} cards · sticker total <b>${total_sticker:,}</b> · '
            f'walk-away floor total <b>${total_floor:,}</b>',
            sub_style,
        ),
    ]

    data = [['Cert', 'Card', 'Sticker', 'Floor']]
    for r in out:
        data.append([
            Paragraph(r['cert'], cell),
            Paragraph(r['name'], cell),
            Paragraph(f'<b>{r["sticker"]}</b>', cell),
            Paragraph(r['floor'], cell),
        ])
    tbl = Table(
        data,
        colWidths=[0.9 * inch, 6.6 * inch, 0.7 * inch, 0.7 * inch],
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f1f1f')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (2, 0), (3, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7f7f7')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(tbl)
    doc.build(elements)
    print(f'Wrote {out_pdf.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
