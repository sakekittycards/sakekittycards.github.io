"""Graded buy-offer in the canonical dark "BUY OFFER" Sake Kitty format
(matches tcgplayerpost/offers/SakeKitty_BigOffer_*), showing Cash + Store Credit
at the graded buy tiers. Values verified (PSA cert + eBay PSA last-sold +
tcgsearch + PriceCharting). Deliberate 2-page layout: financials on p1,
process + terms on p2. Saved to tcgplayerpost/offers/ + PDF."""
import base64, html as _h, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SITE = Path(r"C:\Users\lunar\OneDrive\Desktop\sake-kitty-cards-site")
OFFERS = Path(r"C:\Users\lunar\OneDrive\Desktop\tcgplayerpost\offers")
OFFERS.mkdir(parents=True, exist_ok=True)
DATE = "June 10, 2026"
font_b64 = base64.b64encode((SITE / "Bangers-Regular.ttf").read_bytes()).decode()
logo_b64 = base64.b64encode((SITE / "logo-hat-wordmark.png").read_bytes()).decode()

# (name, set, number, grade, year, market, cert)
ROWS = [
 ("Greninja ex (SIR)","Twilight Masquerade","214/167","PSA 10","2024",930,"96312970"),
 ("Mew ex","151 Ultra-Premium Coll. (SVP)","053","PSA 10","2023",900,"83631916"),
 ("Rayquaza GX (Full Art)","Celestial Storm / Hidden Fates P.C.","177a/168","PSA 10","2018",875,"116488408"),
 ("Mewtwo","151 Ultra-Premium Coll. (SVP)","052","PSA 10","2023",700,"94690245"),
 ("Mega Lucario ex (SIR)","Mega Evolution","179/132","PSA 10","2025",540,"144574835"),
 ("Pikachu (Full Art Secret)","Crown Zenith","160/159","PSA 10","2023",320,"106087735"),
 ("Pikachu (Full Art Secret)","Crown Zenith","160/159","PSA 10","2023",320,"109419989"),
 ("Moltres & Zapdos & Articuno GX","Hidden Fates ETB Promo","SM210","PSA 9","2019",170,"109438260"),
]
# Excluded as illiquid / low-cost (Nick 2026-06-10 — doesn't buy these):
#   Bulbasaur (IR) Mega Evo #133 PSA 10 ~$145 (cert 144574836) — high-pop modern IR, slow mover.
#   Umbreon Gold Star Celebrations #17 PSA 9 ~$118 (cert 127713828) — lowest value + off-grade reprint.


def rate(mk):  # GRADED tiers (cash, store credit). <$100 not accepted (none here).
    if mk < 500:  return 0.80, 0.90
    if mk < 1000: return 0.85, 0.95
    return 0.90, 1.00


def esc(s): return _h.escape(str(s))
def money(x): return round(x + 0.005, 2)


def grade_color(grade):
    g = (grade or "").upper().replace(" ", "")
    if "10" in g:                      return "#ffb000"   # gem 10 — gold
    if "9.5" in g or "95" in g:        return "#c084fc"   # 9.5 — purple
    if "9" in g:                       return "#00d4ff"   # 9 — cyan
    if "8" in g:                       return "#5eead4"   # 8 — teal
    return "#8a94a5"                                       # other — gray


def _rowval(r, *keys, default=""):
    for k in keys:
        if r.get(k) not in (None, ""):
            return r[k]
    return default


def table(rows, show_pct=False, show_credit=False):
    """rows: list of dicts — {name, set, number, market, cash?, credit?, grade?/chip?, cert?}.
    Uses the engine's precomputed cash/credit when present (each card type carries
    its own tier math); falls back to the graded rate() for bare {market} rows."""
    M = C = CR = 0.0
    trs = []
    for r in rows:
        name = _rowval(r, "name", "disp")
        setn = _rowval(r, "set", "setn")
        num = str(_rowval(r, "number", "num"))
        grade = r.get("grade", "")
        mk = float(r["market"])
        cash = r["cash"] if r.get("cash") is not None else money(mk * rate(mk)[0])
        cred = r["credit"] if r.get("credit") is not None else money(mk * rate(mk)[1])
        M += mk; C += cash; CR += cred
        # chip: PSA grade for slabs, else a type/condition tag (LP / Sealed)
        chip = grade or r.get("chip", "")
        chiphtml = (' <span class="chip" style="--cc:' + grade_color(grade) + '">' + esc(chip)
                    + '</span>') if chip else ''
        qty = r.get("qty", 1)
        qtyhtml = (' <span class="qty">&times;' + str(qty) + '</span>') if qty and qty > 1 else ''
        cert = r.get("cert")
        if cert:
            idtail = '<span class="cert">cert ' + esc(cert) + '</span>'
        elif r.get("idnote"):
            idtail = '<span class="cert">' + esc(r["idnote"]) + '</span>'
        elif grade:
            idtail = '<span class="cert">grade per your list</span>'
        else:
            idtail = '<span class="cert">condition pending inspection</span>'
        numhtml = (' &middot; #' + esc(num)) if num else ''
        trs.append(
          '<tr><td class="c-card"><div class="cname">' + esc(name) + qtyhtml + chiphtml + '</div>'
          '<div class="csub">' + esc(setn) + numhtml +
          ' &middot; ' + idtail + '</div></td>'
          '<td class="num mkt">${:,.2f}</td>'.format(mk) +
          '<td class="num offer">${:,.2f}</td>'.format(cash) +
          ('<td class="num cred">${:,.2f}</td>'.format(cred) if show_credit else '') +
          ('<td class="num pct">{:.0f}%</td>'.format(r["pct"] if r.get("pct") is not None else (cash / mk * 100 if mk else 0)) if show_pct else '') +
          '</tr>')
    head = ('<table><thead><tr><th>Card</th><th class="num">Market</th>'
            '<th class="num">Cash Offer</th>'
            + ('<th class="num">Trade Credit</th>' if show_credit else '')
            + ('<th class="num">Buy %</th>' if show_pct else '')
            + '</tr></thead>'
            '<tbody>' + "\n".join(trs) + '</tbody></table>')
    return head, M, C, CR


def _norm_sections(data):
    """Accept either a flat rows list or a list of {title, rows} section dicts."""
    if data and isinstance(data[0], dict) and "rows" in data[0]:
        return [s for s in data if s.get("rows")]
    return [{"title": None, "rows": data}]


CSS = r"""
@font-face{font-family:'Bangers';src:url(data:font/ttf;base64,__FONT__) format('truetype');font-display:swap;}
*{box-sizing:border-box;margin:0;padding:0;}
:root{--bg:#060608;--orange:#ff6a00;--pink:#ff0080;--purple:#7b2fff;--cyan:#00d4ff;--text:#f4f5f8;--muted:#9aa3b2;--dim:#6b7280;--line:rgba(255,255,255,.08);--card:rgba(255,255,255,.04);}
body{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,'Segoe UI',sans-serif;line-height:1.55;position:relative;overflow-x:hidden;padding:34px 18px 60px;}
.blob{position:fixed;border-radius:50%;filter:blur(120px);opacity:.5;z-index:0;}
.b1{width:560px;height:560px;background:radial-gradient(circle,#ff4e00,#ff0080);top:-220px;left:-200px;}
.b2{width:520px;height:520px;background:radial-gradient(circle,#3a00ff,#00d4ff);bottom:-260px;right:-220px;}
.wrap{position:relative;z-index:1;max-width:900px;margin:0 auto;}
.grad-text{background:linear-gradient(135deg,var(--orange),var(--pink),var(--purple));-webkit-background-clip:text;background-clip:text;color:transparent;padding-right:.14em;}

/* ── header ── */
header{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:12px;}
header img{height:56px;display:block;}
.htitle{text-align:right;}
.htitle .kick{font-family:'Bangers',cursive;font-size:40px;letter-spacing:.03em;line-height:1;background:linear-gradient(135deg,var(--orange),var(--pink),var(--purple));-webkit-background-clip:text;background-clip:text;color:transparent;padding-right:.1em;}
.htitle .meta{color:var(--muted);font-size:12.5px;margin-top:6px;line-height:1.6;}
.htitle .meta b{color:var(--text);}
.rule{height:3px;border-radius:3px;background:linear-gradient(90deg,var(--orange),var(--pink),var(--purple),var(--cyan));margin:0 0 16px;}
.collabel{font-family:'Bangers',cursive;font-size:26px;letter-spacing:.03em;margin-bottom:10px;}
.collabel-row{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:10px;}
.collabel-row .collabel{margin-bottom:0;}
.srating{flex:0 0 auto;font-family:'Bangers',cursive;font-size:30px;letter-spacing:.05em;line-height:1;color:#fff;padding:7px 16px 9px;border-radius:13px;background:linear-gradient(135deg,var(--orange),var(--pink),var(--purple));box-shadow:0 0 18px rgba(255,0,128,.38);}

/* ── stat cards ── */
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:14px;}
.stats2{grid-template-columns:repeat(2,1fr);}
.stat{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:15px 18px;backdrop-filter:blur(8px);}
.stat .lbl{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.12em;font-weight:600;}
.stat .val{font-family:'Bangers',cursive;font-size:33px;letter-spacing:.02em;margin-top:5px;padding-right:.1em;}
.stat.cash .val{background:linear-gradient(135deg,var(--orange),var(--pink));-webkit-background-clip:text;background-clip:text;color:transparent;}
.stat.cred .val{background:linear-gradient(135deg,var(--cyan),var(--purple));-webkit-background-clip:text;background-clip:text;color:transparent;}
.stat .sub{color:var(--dim);font-size:11.5px;margin-top:4px;}

/* ── table ── */
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;}
thead th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);padding:11px 20px;background:rgba(255,255,255,.03);border-bottom:1px solid var(--line);}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums;}
tbody td{padding:8px 20px;border-bottom:1px solid var(--line);vertical-align:middle;}
tbody tr:last-child td{border-bottom:none;}
tbody tr:nth-child(even){background:rgba(255,255,255,.02);}
.cname{font-weight:700;font-size:15px;}
.csub{color:var(--muted);font-size:12px;margin-top:4px;}
.csub .cert{font-variant-numeric:tabular-nums;color:var(--dim);}
.chip{font-size:10px;font-weight:800;letter-spacing:.04em;padding:2px 8px;border-radius:5px;color:var(--cc,#8a94a5);background:color-mix(in srgb,var(--cc,#8a94a5) 16%,transparent);border:1px solid color-mix(in srgb,var(--cc,#8a94a5) 35%,transparent);}
.qty{font-size:11px;font-weight:800;color:var(--orange);}
td.mkt{color:var(--muted);}
td.offer{font-weight:800;font-size:16px;color:var(--orange);}
td.cred{font-weight:800;font-size:16px;color:var(--cyan);}
td.pct{font-weight:700;font-size:14px;color:#9aa3b2;}
.subhead{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin:16px 0 8px;}
.subhead .st{font-family:'Bangers',cursive;font-size:20px;letter-spacing:.03em;padding-right:.1em;}
.subhead .sc{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.1em;}
.subhead:first-of-type{margin-top:2px;}

/* ── grand total ── */
.grand{margin-top:10px;background:linear-gradient(135deg,rgba(255,106,0,.16),rgba(255,0,128,.14),rgba(123,47,255,.16));border:1px solid rgba(255,106,0,.35);border-radius:18px;padding:13px 24px;display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap;}
.grand .gl{font-family:'Bangers',cursive;font-size:26px;letter-spacing:.03em;}
.grand .gr{text-align:right;}
.grand .gr .big{font-family:'Bangers',cursive;font-size:31px;line-height:1.05;background:linear-gradient(135deg,var(--orange),var(--pink));-webkit-background-clip:text;background-clip:text;color:transparent;padding-right:.1em;}
.grand .gr .cr{font-family:'Bangers',cursive;font-size:19px;line-height:1.25;background:linear-gradient(135deg,var(--cyan),var(--purple));-webkit-background-clip:text;background-clip:text;color:transparent;padding-right:.1em;}
.grand .gr .mk{color:var(--muted);font-size:12.5px;margin-top:2px;}

/* ── page 2: process + terms ── */
.section-h{font-family:'Bangers',cursive;font-size:24px;letter-spacing:.03em;margin:0 0 16px;}
.steps{display:grid;gap:11px;}
.step{display:flex;gap:14px;align-items:flex-start;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 17px;}
.step .n{flex:0 0 auto;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:'Bangers',cursive;font-size:17px;background:linear-gradient(135deg,var(--orange),var(--pink));color:#fff;}
.step .b{font-size:12.5px;color:var(--muted);line-height:1.55;}
.step .b b{color:var(--text);font-weight:700;}
.terms{margin-top:24px;background:rgba(255,255,255,.02);border:1px solid var(--line);border-radius:12px;padding:18px 20px;}
.terms h4{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:11px;}
.terms ol{margin:0;padding-left:16px;}
.terms li{color:var(--dim);font-size:10.6px;line-height:1.6;margin-bottom:7px;}
.terms li:last-child{margin-bottom:0;}
.terms li b{color:var(--muted);}
.foot{color:var(--dim);font-size:11px;text-align:center;margin-top:18px;line-height:1.7;}

@media print{@page{size:letter;margin:0;}body{-webkit-print-color-adjust:exact;print-color-adjust:exact;padding:36px 34px 20px;
  background:radial-gradient(720px 460px at 10% -4%,rgba(255,78,0,.22),transparent 55%),radial-gradient(720px 460px at 106% 103%,rgba(58,0,255,.18),transparent 55%),#060608;}
 .blob{display:none;}.wrap{max-width:100%;}
 .stat,tr,.step,.grand,.terms li{break-inside:avoid;}
 thead{display:table-header-group;}.section-h{break-after:avoid;}
 .subhead{break-after:avoid;break-inside:avoid;}
 .pagebreak{break-before:page;}.page2{margin-top:0;}}
"""
CSS = CSS.replace("__FONT__", font_b64)


def build(data, date=DATE, label=None, out_stem="SakeKitty_GradedBuyOffer", rating=None, show_pct=False, show_credit=False):
    sections = _norm_sections(data)
    M = C = CR = 0.0; n = 0; sec_html = []
    for s in sections:
        tbl, m, c, cr = table(s["rows"], show_pct=show_pct, show_credit=show_credit)
        M += m; C += c; CR += cr; n += len(s["rows"])
        if s.get("title"):
            sub = ('<div class="subhead"><span class="st grad-text">' + s["title"] +
                   '</span><span class="sc">' + str(len(s["rows"])) +
                   (' &middot; ' + s["subtitle"] if s.get("subtitle") else '') +
                   '</span></div>')
        else:
            sub = ''
        sec_html.append(sub + tbl)
    sections_html = "".join(sec_html)
    collabel = label or "Collection Buy Offer &mdash; {} Item{}".format(n, "" if n == 1 else "s")
    # methodology line derives from the row types actually present (CardLadder for
    # graded; live TCGplayer market via tcgsearch for raw/sealed).
    all_rows = [r for s in sections for r in s["rows"]]
    has_graded = any((r.get("grade") or "").strip() for r in all_rows)
    has_rawsealed = any(not (r.get("grade") or "").strip() for r in all_rows)
    multi = len([s for s in sections if s.get("title")]) > 1
    if has_graded and has_rawsealed:
        subtitle = ("Graded &middot; CardLadder recent-sold &nbsp;&middot;&nbsp; "
                    "Raw &amp; sealed &middot; lower of TCGplayer market &amp; recent-sold")
    elif has_graded:
        subtitle = "Graded slabs &middot; CardLadder recent-sold (last-5, no outlier)"
    else:
        subtitle = "Raw singles &amp; sealed &middot; lower of TCGplayer market &amp; recent-sold"
    doc = (
     '<!doctype html><html lang="en"><head><meta charset="utf-8">'
     '<meta name="viewport" content="width=device-width,initial-scale=1">'
     '<title>Sake Kitty Cards - Buy Offer</title>'
     '<link rel="preconnect" href="https://fonts.googleapis.com">'
     '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">'
     '<style>' + CSS + '</style></head><body>'
     '<div class="blob b1"></div><div class="blob b2"></div><div class="wrap">'
     '<header><span class="logobox"><img src="data:image/png;base64,' + logo_b64 + '" alt="Sake Kitty Cards"></span>'
     '<div class="htitle"><div class="kick">BUY OFFER</div>'
     '<div class="meta">' + date + ' &nbsp;&middot;&nbsp; <b>nick@sakekittycards.com</b><br>'
     + subtitle + '</div></div></header>'
     '<div class="rule"></div>'
     '<div class="collabel-row"><div class="collabel grad-text">' + collabel + '</div>' +
     (('<span class="srating" title="Liquidity rating (1-9, higher = easier to sell)">S'
       + str(rating) + '</span>') if rating else '') +
     '</div>' +
     '<div class="stats ' + ('' if show_credit else 'stats2') + '">'
     '<div class="stat"><div class="lbl">Total Market</div><div class="val">${:,.0f}</div><div class="sub">${:,.2f} &middot; {} item{}</div></div>'.format(M, M, n, "" if n == 1 else "s") +
     '<div class="stat cash"><div class="lbl">Cash Offer</div><div class="val">${:,.0f}</div><div class="sub">{:.0f}% of market &middot; paid on arrival</div></div>'.format(C, C/M*100) +
     (('<div class="stat cred"><div class="lbl">Trade Credit</div><div class="val">${:,.0f}</div><div class="sub">{:.0f}% of market &middot; spends in-store</div></div>'.format(CR, CR/M*100)) if show_credit else '') +
     '</div>' + sections_html +
     '<div class="grand"><div class="gl grad-text">TOTAL OFFER</div>'
     '<div class="gr"><div class="big">${:,.2f} cash</div>'.format(C) +
     (('<div class="cr">${:,.2f} trade credit</div>'.format(CR)) if show_credit else '') +
     '<div class="mk">on ${:,.2f} verified market value &middot; paid on arrival</div></div></div>'.format(M) +
     # ── page 2 ──
     '<div class="section-h grad-text pagebreak page2">How It Works</div><div class="steps">'
     '<div class="step"><div class="n">1</div><div class="b"><b>Accept the offer.</b> Reply to lock it in. This quote is valid 7 days &mdash; graded prices move with the market, so the offer may be re-quoted if the shipment arrives after that window.</div></div>'
     '<div class="step"><div class="n">2</div><div class="b"><b>Pack &amp; ship &mdash; seller&rsquo;s cost.</b> The seller ships the cards <b>fully insured for the offer value</b> with <b>signature confirmation required</b>, and covers all shipping &amp; insurance fees. Just pack everything <b>safely &amp; securely</b> so it arrives in the same condition &mdash; a rigid box with enough cushioning that nothing can shift is plenty.</div></div>'
     '<div class="step"><div class="n">3</div><div class="b"><b>Recorded unboxing.</b> Every package is opened on a continuous, timestamped video &mdash; sealed to open &mdash; and kept on file to protect <b>both parties</b> against loss, swaps, or damage disputes.</div></div>'
     '<div class="step"><div class="n">4</div><div class="b"><b>Cert &amp; condition check.</b> Each PSA cert is verified at psacard.com; raw cards are condition-checked in hand; every item is inspected to confirm it matches this offer. Raw values use the card&rsquo;s listed condition and are finalized on inspection.</div></div>'
     '<div class="step"><div class="n">5</div><div class="b"><b>Get paid on arrival.</b> On successful verification, payment goes out the <b>same business day</b> &mdash; cash via Venmo / PayPal / Cash App.</div></div>'
     '<div class="step"><div class="n">6</div><div class="b"><b>Discrepancies.</b> If a slab isn&rsquo;t as represented (wrong cert, altered, damaged, or grade mismatch) we&rsquo;ll send a revised offer or return it; return shipping on a declined item is the seller&rsquo;s.</div></div>'
     '</div>'
     '<div class="terms"><h4>Terms &amp; Conditions</h4><ol>'
     '<li>This sheet is a good-faith <b>quote, not a binding contract of sale</b>, until the cards are received, verified, and payment is issued. Sake Kitty Cards may revise or withdraw the offer if the shipment arrives after the validity window, market value moves materially, or the items differ from this listing.</li>'
     '<li><b>Risk of loss in transit remains with the seller</b> until delivery and verification &mdash; full carrier insurance and signature confirmation are required for this reason. Title and risk of loss pass to Sake Kitty Cards only upon payment.</li>'
     '<li>The seller <b>represents and warrants</b> they are the lawful owner with full authority to sell, and that the cards are authentic, unaltered, and as described, free of any liens or claims.</li>'
     '<li>The <b>recorded unboxing</b> is retained as the controlling record of the package contents and condition at the time of receipt, and may be shared with the seller or a carrier in any claim.</li>'
     '<li>Sake Kitty Cards is <b>not liable for items lost, delayed, or damaged in transit</b>; the seller&rsquo;s carrier insurance is the sole remedy for transit loss or damage.</li>'
     '<li>By shipping cards in response to this offer, the seller <b>agrees to these terms</b>. This agreement is governed by the laws of the State of Florida.</li>'
     '</ol></div>'
     '<div class="foot">' + (
        ('Graded buy rates &mdash; Cash by value tier. '
         if has_graded else '') +
        ('Raw singles &amp; sealed &mdash; Cash by value; raw quoted at the listed condition, finalized on inspection.'
         if has_rawsealed else '')
     ) + '<br>'
     'Values from ' + (
        'CardLadder recent-sold (graded) &amp; the lower of TCGplayer market or recent-sold via tcgsearch (raw/sealed).'
        if has_graded and has_rawsealed else
        'CardLadder recent-sold comps (last-5, outliers dropped).' if has_graded else
        'the lower of TCGplayer market or recent-sold avg (tcgsearch); final value confirmed on in-hand inspection.'
     ) + ' '
     'Sake Kitty Cards &middot; nick@sakekittycards.com &middot; Offer valid 7 days from ' + date +
     '; final offer subject to in-hand verification of cert &amp; condition.</div>'
     '</div></body></html>'
    )
    out = OFFERS / (out_stem + ".html")
    out.write_text(doc, encoding="utf-8")
    print("{} item(s) | MARKET ${:,.2f} | CASH ${:,.2f} ({:.0f}%) | STORE CREDIT ${:,.2f} ({:.0f}%)".format(
        n, M, C, C/M*100, CR, CR/M*100))
    return out


def to_pdf(htmlpath, out_stem="SakeKitty_GradedBuyOffer"):
    pdf = OFFERS / (out_stem + ".pdf")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto("file://" + str(htmlpath).replace("\\", "/"), wait_until="networkidle")
        pg.wait_for_timeout(1200)
        pg.pdf(path=str(pdf), format="Letter", print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        b.close()
    print("WROTE", pdf)
    return pdf


def render(rows, date=DATE, label=None, out_stem="SakeKitty_GradedBuyOffer", rating=None, show_pct=False, show_credit=False):
    """Build HTML + PDF for an offer; returns (html_path, pdf_path)."""
    html = build(rows, date=date, label=label, out_stem=out_stem, rating=rating, show_pct=show_pct, show_credit=show_credit)
    pdf = to_pdf(html, out_stem=out_stem)
    return html, pdf


def _sample_rows():
    return [dict(name=n, set=s, number=num, grade=g, year=y, market=mk, cert=c)
            for (n, s, num, g, y, mk, c) in ROWS]


if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    render(_sample_rows())
