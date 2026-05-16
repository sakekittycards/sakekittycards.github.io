"""One-shot: sync pricing.csv metadata to Card Ladder truth.

CL is the source of truth (cert numbers verified against PSA). pricing.csv
display columns (name/set/year/number/grade) had drifted on many rows.
Square pushes are unaffected — those key off cert.

CL Subject strings are sometimes truncated awkwardly ("Orgn.frm.dialga Vstar",
"M.sbleye / Tyranitar Gx"). We use CL's set/year/number/grade verbatim where
clean, and a hand-curated NAME_OVERRIDES map for booth-sticker-friendly names.
Set strings also get a light cleanup pass (strip "Pokemon " prefix, fix casing).
"""
import csv
import re
import shutil
import sys
from pathlib import Path

CL_CSV = Path('C:/Users/lunar/Downloads/Collection - Card Ladder (17).csv')
PRICING = Path(__file__).parent / 'pricing.csv'

# Hand-curated display names — keyed by cert. Use these instead of CL's Subject.
# Combines CL Subject + Variation + reasonable expansions.
NAME_OVERRIDES = {
    '50358384':   'Celebi Holo',
    '58568623':   'Charizard VMAX (Shiny Vault FA)',
    '65570347':   'Venusaur Holo',
    '72016903':   'Charizard (Reverse Foil)',
    '75183695':   'Origin Forme Dialga VSTAR',
    '84566703':   'Moltres',
    '89932897':   'Charizard ex (Special Illustration Rare)',
    '92889917':   'Magikarp (Art Rare)',
    '94676138':   'Pikachu with Grey Felt Hat (FA)',
    '95199161':   'FA Arceus VSTAR',
    '95276041':   'Charizard ex (Ultra Rare)',
    '98517579':   'FA Shaymin EX',
    '99211118':   'FA Espeon VMAX',
    '99513425':   'Latias ex (Special Art Rare)',
    '102607615':  'Pikachu with Grey Felt Hat (FA)',
    '104313026':  'Palafin (Illustration Rare)',
    '106438552':  'FA Dragonite V',
    '107496657':  'FA Rayquaza VMAX',
    '108973922':  'Origin Forme Palkia VSTAR',
    '110420477':  'Umbreon VMAX (FA Secret)',
    '110772487':  'Charizard V (Alternate Full Art)',
    '111350109':  'FA Charizard VMAX',
    '112214360':  'Pidgeotto (Illustration Rare)',
    '113090244':  'Rowlet & Alolan Exeggutor GX (FA)',
    '113910492':  'FA Mewtwo V',
    '114068076':  'Milotic ex (Special Art Rare)',
    '115079776':  'Gardevoir ex (Special Illustration Rare)',
    '119392108':  'Pikachu ex (Special Illustration Rare)',
    '121116624':  'FA Deoxys',
    '126435156':  'Eevee ex',
    '128159429':  'Pikachu (Art Rare)',
    '131611480':  'Mewtwo GX (Secret)',
    '134321907':  'M Sableye & Tyranitar GX (FA)',
    '138441842':  'Umbreon Holo',
    '139036804':  'Zapdos Holo',
    '139206918':  'Mega Venusaur ex (Special Illustration Rare)',
    '143516232':  'Reshiram ex (Black White Rare)',
    '143540438':  'Roaring Moon ex (Special Illustration Rare)',
    '146514325':  'Eevee ex',
    '146746311':  'Mega Latias ex (Special Illustration Rare)',
    '147655076':  'FA Pikachu VMAX',
    '151607423':  'Zekrom ex (Black White Rare)',
    '151936010':  'Mega Dragonite ex (Special Illustration Rare)',
    '152039165':  'FA Deoxys VMAX',
    '156593992':  'Reshiram ex (Black White Rare)',
    '3914522049': 'Feraligatr Holo',
    '4321131035': 'Blastoise ex (Special Art Rare)',
    '4322429002': 'Eevee (Yu Nagaba)',
    '6021612152': 'Ceruledge (Pokémon Day Promo Cosmos Holo)',
    '6021615021': 'Pikachu (World Championships)',
    '6130902118': 'Mega Charizard X ex (UPC Promo)',
    '6136935033': 'Umbreon Gold Star',
}


def clean_set(s):
    """CL set names → clean booth labels."""
    s = s.strip()
    # Drop leading 'Pokemon '
    if s.lower().startswith('pokemon '):
        s = s[8:]
    # Specific cleanups
    rep = {
        'Japanese Vending': 'Japanese Vending Series II',
        'Japanese Neo 2': 'Neo 2 (Japanese)',
        'Japanese Neo 3': 'Neo 3 (Japanese)',
        'Japanese Sword & Shield Vmax Climax': 'VMAX Climax (Japanese)',
        'Japanese Sword & Shield Shiny Star V': 'Shiny Star V (Japanese)',
        'Japanese Sun & Moon Sky Legend': 'Sky Legend (Japanese)',
        'Japanese Sv1a-Triplet Beat': 'SV1a Triplet Beat (Japanese)',
        'Japanese Sv7a-Paradise Dragona': 'SV7a Paradise Dragona (Japanese)',
        'Japanese Sv8-Super Electric Breaker': 'SV8 Super Electric Breaker (Japanese)',
        'Card 151 Japanese': 'Card 151 (Japanese)',
        'Scarlet & Violet Promos Japanese': 'Scarlet & Violet Promos (Japanese)',
        'Simplified Chinese 151 C-Collection 151': 'Simplified Chinese 151',
        'Sword & Shield Evolving Skies': 'Evolving Skies',
        'Sword & Shield: Evolving Skies': 'Evolving Skies',
        'Sword & Shield: Brilliant Stars': 'Brilliant Stars',
        'Sword & Shield: Fusion Strike': 'Fusion Strike',
        'Sword & Shield: Shining Fates': 'Shining Fates',
        'Sword & Shield VIVID Voltage': 'Vivid Voltage',
        'Sword and Shield Crown Zenith': 'Crown Zenith',
        'Sun & Moon Shining Legends': 'Shining Legends',
        'Sun & Moon Unified Minds': 'Unified Minds',
        'Xy Evolutions': 'XY Evolutions',
        'Premium Trainer Xy Collection Promo': 'XY Premium Trainer Collection',
        'Obf En-Obsidian Flames': 'Obsidian Flames',
        'Paf En-Paldean Fates': 'Paldean Fates',
        'Paldean Fates - PAF EN': 'Paldean Fates',
        'Pre En-Prismatic Evolutions': 'Prismatic Evolutions',
        'Meg En-Mega Evolution': 'Mega Evolution',
        'Asc En-Ascended Heroes': 'Ascended Heroes',
        'Wht En-White Flare': 'White Flare',
        'Blk En-Black Bolt': 'Black Bolt',
        'Svp En-Sv Black Star Promo': 'Scarlet & Violet Promos',
        'SVP Black Star Promos': 'Scarlet & Violet Promos',
        'Black Star Promos - Scarlet & Violet SVP EN': 'Scarlet & Violet Promos',
        'Scarlet & Violet: Surging Sparks': 'Surging Sparks',
        'Scarlet & Violet 151': '151',
        'Celebrations - Classic Coll.': 'Celebrations Classic Collection',
        'Game': 'Base Set',
        'Black Star Promos': 'Black Star Promos',
        'Go': 'Pokémon GO',
    }
    for k, v in rep.items():
        if s == k:
            return v
    return s


def clean_grade(g):
    """CL grade strings → pricing.csv format."""
    g = g.strip()
    # Collapse double spaces
    g = re.sub(r'\s+', ' ', g)
    # Common normalizations
    g = g.replace('CGC 10 Pristine', 'CGC Pristine 10')
    g = g.replace('CGC 8.5', 'CGC 8.5')
    return g


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if not CL_CSV.exists():
        print(f'CL CSV not found: {CL_CSV}'); return 1
    if not PRICING.exists():
        print(f'pricing.csv not found: {PRICING}'); return 1

    # Load CL
    cl = {}
    with open(CL_CSV, 'r', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            cert = r['Graded Cert #'].strip()
            cl[cert] = r

    # Load pricing
    with open(PRICING, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)

    changed = []
    missing = []
    for r in rows:
        cert = r['cert'].strip()
        if cert not in cl:
            missing.append(cert)
            continue
        c = cl[cert]
        new_year = c['Year'].strip()
        new_set = clean_set(c['Set'].strip())
        new_num = c['Number'].strip().lstrip('0') or c['Number'].strip()
        new_grade = clean_grade(c['Condition'].strip())
        new_name = NAME_OVERRIDES.get(cert, c['Subject'].strip())

        before = {k: r[k] for k in ('year','set','name','number','grade')}
        diffs = {}
        if r['year'] != new_year:
            diffs['year'] = (r['year'], new_year); r['year'] = new_year
        if r['set'] != new_set:
            diffs['set'] = (r['set'], new_set); r['set'] = new_set
        if r['name'] != new_name:
            diffs['name'] = (r['name'], new_name); r['name'] = new_name
        if r['number'].lstrip('0') != new_num.lstrip('0') and r['number'] != new_num:
            diffs['number'] = (r['number'], new_num); r['number'] = new_num
        elif r['number'] != new_num:
            # Same numerically (e.g., "85" vs "085") — keep CL's leading-zero form for consistency
            diffs['number'] = (r['number'], new_num); r['number'] = new_num
        if r['grade'] != new_grade:
            diffs['grade'] = (r['grade'], new_grade); r['grade'] = new_grade

        if diffs:
            changed.append((cert, r.get('your_price','').replace('[uploaded]',''), diffs))

    # Write
    with open(PRICING, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f'pricing.csv: {len(rows)} rows, {len(changed)} updated.')
    if missing:
        print(f'WARNING: {len(missing)} certs not in CL: {missing}')
    print()
    for cert, price, diffs in sorted(changed, key=lambda x: -float(x[1] or 0)):
        print(f'cert {cert}  ${price}')
        for field, (old, new) in diffs.items():
            print(f'    {field:6s}  {old!r:<50}  ->  {new!r}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
