"""One-shot: push competitive-sticker drops to Square, sync pricing.csv.

Generated 2026-05-15 from full multi-source audit. Anchors to
max(eBay sold avg if >=3 clean comps else CL CV, PC) and applies a
tier-aligned margin (1.20 under $200, 1.12 in $200-$999, 1.08 at $1000+),
with vintage-scarce protection (pre-2010 + pop<500 capped at -10%).
Hand-tuned 4 cards upward from the model for cushion: Umbreon Neo 2 ($1050),
Tyranitar/M Sableye GX ($475), Ceruledge CGC ($75), Moltres Vending ($1100).
"""
import csv
import json
import os
import sys
import time
import urllib.request

DROPS = [
    ('134321907',  475, 'M Sableye/Tyranitar GX UM PSA 9'),
    ('138441842', 1050, 'Umbreon #197 Neo 2 PSA 9 JP'),
    ('110420477', 2390, 'FA Umbreon VMAX Ev. Skies PSA 9'),
    ('113090244',  200, 'Rowlet/Alolan Exeggutor GX Sky Legend'),
    ('84566703',  1100, 'Moltres Vending PSA 10 pop=141'),
    ('89932897',  1840, 'Charizard ex SIR 151 PSA 10'),
    ('106438552', 1405, 'FA Dragonite V Ev. Skies'),
    ('111350109',  305, 'FA Charizard VMAX #308 Shiny Star V'),
    ('112214360',  225, 'Pidgeotto IR Obsidian Flames'),
    ('139036804',  175, 'Zapdos #16 Base PSA 8'),
    ('95199161',   470, 'FA Arceus VSTAR GG70'),
    ('99211118',   895, 'Espeon VMAX Fusion Strike'),
    ('6021612152',  75, 'Ceruledge CGC Pristine PAF'),
    ('4321131035', 395, 'Blastoise SAR 151 JP CGC Pristine'),
    ('6130902118', 360, 'Mega Charizard X JP CGC Pristine'),
    ('6136935033', 425, 'Umbreon Gold Star Celebrations CGC'),
    ('151607423', 2090, 'Zekrom ex Black Bolt'),
    ('4322429002', 210, 'Eevee Yu Nagaba PRISTINE'),
    ('151936010', 2800, 'Mega Dragonite SIR Ascended Heroes'),
    ('75183695',   375, 'Dialga VSTAR GG68'),
    ('92889917',   370, 'Magikarp AR SV1a JP'),
    ('110772487',  355, 'Charizard V Brilliant Stars JP PSA 9'),
    ('114068076',  175, 'Milotic ex SAR SV8'),
    ('50358384',   300, 'Celebi #251 Neo 3 PSA 9'),
    ('121116624',  335, 'FA Deoxys GG12'),
    ('72016903',   185, 'Charizard #11 XY Evolutions RF PSA 9'),
    ('95276041',   225, 'Charizard ex OBF'),
    ('139206918',  360, 'Mega Venusaur ex'),
    ('119392108', 1405, 'Pikachu ex Surging Sparks JP'),
    ('60607369',   265, 'Rayquaza Vivid Voltage'),
    ('98517579',   550, 'FA Shaymin EX XY Promo'),
    ('108973922',  360, 'Palkia VSTAR GG67'),
    ('99513425',   280, 'Latias ex SV7a JP'),
    ('143540438',  955, 'Roaring Moon ex Prismatic Evol.'),
    ('152039165',  235, 'Deoxys VMAX GG45'),
    ('113910492',  420, 'FA Mewtwo V Pokemon GO'),
    ('65570347',   300, 'Venusaur Base / Game'),
    ('58568623',   365, 'Charizard VMAX Shining Fates SV107'),
]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    token = os.environ.get('SK_ADMIN_TOKEN', '').strip()
    if not token:
        print('SK_ADMIN_TOKEN missing'); return 1
    url = 'https://sakekitty-square.nwilliams23999.workers.dev/admin/update-graded-price'

    ok = fail = 0
    for cert, price, label in DROPS:
        body = json.dumps({'cert': cert, 'price_cents': price * 100}).encode()
        req = urllib.request.Request(
            url, method='POST', data=body,
            headers={'X-Sake-Admin-Token': token,
                     'Content-Type': 'application/json',
                     'User-Agent': 'Mozilla/5.0'},
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                print(f'OK  ${price:<5} {cert:<11} {label}')
                ok += 1
        except Exception as e:
            print(f'ERR ${price:<5} {cert:<11} {label} -> {e}')
            fail += 1
        time.sleep(0.20)
    print()
    print(f'Square: {ok} pushed, {fail} failed.')

    # Sync pricing.csv
    update_map = {c: p for c, p, _ in DROPS}
    with open('pricing.csv', 'r', encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())
    n = 0
    for r in rows:
        if r['cert'] in update_map:
            r['your_price'] = f'[uploaded]{update_map[r["cert"]]}'
            # Clear stale manual-override on Moltres now that we've repriced it
            if r['cert'] == '84566703':
                r['condition_note'] = ''
            n += 1
    with open('pricing.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f'pricing.csv: {n} rows synced.')
    return 0 if fail == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
