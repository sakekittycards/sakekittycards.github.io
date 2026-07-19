#!/usr/bin/env python3
"""Build assets/graded-prices.json for the SK site.
Prices each live Square graded slab from PriceCharting (same gates as the TCGenie app),
applies a STRICT confidence filter, and lists at PC x 1.15 (Nick's graded markup) rounded to $5.
Only clean modern-English Pokemon slabs with a number+console match are auto-priced; everything
else (One Piece, Dragon Ball, JP/CN/KR, pre-2016 vintage, mismatches) is LEFT OUT -> Make-Offer.
"""
import json, re, time, urllib.request, urllib.parse, pathlib

REPO = pathlib.Path(r"C:\Users\lunar\OneDrive\Desktop\sake-kitty-cards-site")
OUT  = REPO / "assets" / "graded-prices.json"
TOK  = re.search(r't=([A-Za-z0-9]+)', pathlib.Path.home().joinpath('.claude','pricecharting_csv_url.txt').read_text()).group(1)
UA   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MARKUP = 1.15

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)

items = get("https://sakekitty-square.nwilliams23999.workers.dev/items")["items"]
grx = re.compile(r'\b(PSA|CGC|BGS|SGC|BECKETT)\s*([0-9]+(?:\.[0-9])?)', re.I)

def parse(name):
    m = grx.search(name or "")
    if not m: return None
    grader = m.group(1).upper(); grade = m.group(2)
    if grader == "BECKETT": grader = "BGS"
    ym = re.search(r'\b(19|20)\d{2}\b', name); year = int(ym.group(0)) if ym else 0
    rest = re.sub(r'\b(19|20)\d{2}\b',' ', name[:m.start()] + " " + name[m.end():]).strip()
    lang = 'JP' if re.search(r'japanese',rest,re.I) else 'CN' if re.search(r'chinese',rest,re.I) else 'KR' if re.search(r'korean',rest,re.I) else 'EN'
    game = 'onepiece' if re.search(r'one piece',name,re.I) else 'dbs' if re.search(r'dragon ball',name,re.I) else 'pokemon'
    numm = re.search(r'#\s*([A-Za-z]*\d+[A-Za-z0-9\-]*)', rest)
    number = numm.group(1) if numm else ""
    core = re.sub(r'#\s*[A-Za-z0-9\-]+',' ', rest)
    core = re.sub(r'\bPokemon\b|\bJapanese\b|\bSimplified Chinese\b|\bChinese\b|\bKorean\b|\bPromos?\b',' ',core,flags=re.I)
    core = re.sub(r'\s+',' ',core).strip()
    toks = core.split(); cardname = " ".join(toks[-3:]) if toks else core
    return dict(grader=grader,grade=grade,lang=lang,game=game,year=year,number=number,core=core,cardname=cardname)

def field_for(grader,grade):
    g=grade
    if '10' in g and '.' not in g:
        return {'BGS':'bgs-10-price','CGC':'condition-17-price','SGC':'condition-18-price'}.get(grader,'manual-only-price')
    if '9.5' in g: return 'box-only-price'
    if re.search(r'(^|\D)9($|\D)',g): return 'graded-price'
    if re.search(r'(^|\D)8($|\D)',g): return 'new-price'
    if re.search(r'(^|\D)7($|\D)',g): return 'cib-price'
    return None
def pc_lang(con):
    c=con.lower(); return 'JP' if 'japanese' in c else 'CN' if 'chinese' in c else 'KR' if 'korean' in c else 'EN'
def pc_nums(pn):
    out=[]; m=re.search(r'#\s*[A-Za-z]{0,5}0*(\d+)',pn)
    if m: out.append(m.group(1).lstrip('0'))
    for x in re.finditer(r'\b[A-Za-z]{2,4}\d{0,2}-[A-Za-z]{0,3}0*(\d+)\b',pn): out.append(x.group(1).lstrip('0'))
    return out

def price_pc(p):
    field=field_for(p['grader'],p['grade'])
    if not field: return None
    bare=re.sub(r'\D','',p['number'].split('/')[0]).lstrip('0')
    want=re.sub(r'[^a-z]','',p['cardname'].lower())
    def build(query):
        try: d=get("https://www.pricecharting.com/api/products?t=%s&q=%s"%(TOK,urllib.parse.quote(query)))
        except Exception: return []
        prods=d.get('products') or ([d] if d.get('product-name') else [])
        cands=[]
        for pr in prods:
            pn=str(pr.get('product-name') or ''); con=str(pr.get('console-name') or '')
            if re.search(r'funko|plush|figure|statue',con,re.I): continue
            nums=pc_nums(pn)
            if nums and bare and bare not in nums: continue
            if pc_lang(con)!=p['lang']: continue
            try: cents=int(pr.get(field) or 0)
            except: cents=0
            if not cents and field in ('condition-17-price','condition-18-price'):
                try: psa10=int(pr.get('manual-only-price') or 0)
                except: psa10=0
                if psa10: cents=round(psa10*0.6)
            if not cents: continue
            if bare and not nums: continue
            numok = bool(nums and bare and bare in nums)
            score=(80 if numok else 0)
            got=re.sub(r'[^a-z]','',pn.lower())
            if want and want[:6] in got: score+=30
            cands.append((score,cents,pn,con,numok))
        return cands
    cands=build(p['core'] or p['cardname'])
    if not cands and bare: cands=build((p['cardname']+" "+p['number']).strip())
    if not cands: return None
    cands.sort(key=lambda c:(-c[0],len(c[2])))
    sc,cents,pn,con,numok=cands[0]
    return dict(pc=round(cents/100,2),product=f"{pn} [{con}]",console=con,numok=numok)

def round5(x): return int(round(x/5.0)*5)

priced={}; included=[]; excluded=[]
for it in items:
    nm=it.get('name') or ''; p=parse(nm)
    if not p: excluded.append((nm,'not-graded')); continue
    r=price_pc(p)
    time.sleep(1.1)
    reason=None
    if not r: reason='no-PC-match'
    elif p['game']!='pokemon': reason='non-pokemon(%s)'%p['game']
    elif p['lang']!='EN': reason='foreign(%s)'%p['lang']
    elif p['year'] and p['year']<2016: reason='vintage(%d)'%p['year']
    elif not r['numok']: reason='no-number-match'
    elif 'pokemon' not in r['console'].lower() or re.search(r'japanese|chinese|korean',r['console'],re.I): reason='console-mismatch'
    elif not (5 < r['pc'] < 20000): reason='pc-out-of-range(%s)'%r['pc']
    if reason:
        excluded.append((nm,reason+(' -> '+r['product'] if r else ''))); continue
    listprice=round5(r['pc']*MARKUP)
    priced[str(it['id'])]={'price':listprice,'pc':r['pc'],'grade':p['grader']+' '+p['grade'],'product':r['product'],'name':nm[:70]}
    included.append((nm,it.get('price'),r['pc'],listprice))

OUT.write_text(json.dumps(priced,indent=1))
print("=== INCLUDED (auto-priced, PC x1.15 round $5) ===")
for nm,cur,pc,lp in sorted(included,key=lambda x:-x[3]):
    print(f"  cur ${str(cur):>6}  PC ${pc:>8}  -> LIST ${lp:<7}  {nm[:60]}")
print(f"\n=== EXCLUDED ({len(excluded)}) -> stay Make-Offer ===")
for nm,why in excluded: print(f"  {why:<34} {nm[:58]}")
print(f"\nWROTE {OUT}  ({len(priced)} priced, {len(excluded)} Make-Offer)")
