"""
One-shot batch corrections — POST /admin/update-graded for each cert
where pokemontcg.io's auto-match got the card wrong.

Usage:
    SK_ADMIN_TOKEN=<token> python update_titles.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"
ENDPOINT = f"{WORKER_BASE}/admin/update-graded"

# (cert, card metadata) — what each item SHOULD be, based on reading the
# actual PSA / CGC / BGS label on the slab. These override whatever
# pokemontcg.io originally returned.
CORRECTIONS = [
    {
        'cert': '107496657',
        'card': {
            'name': 'FA Rayquaza VMAX',
            'year': '2021', 'set_name': 'VMAX Climax (Japanese)',
            'card_number': '252', 'grade': 'GEM MT 10',
        },
    },
    {
        'cert': '139206918',
        'card': {
            'name': 'Mega Venusaur ex (Special Illustration Rare)',
            'year': '2025', 'set_name': 'Pokemon Mega Evolution',
            'card_number': '177', 'grade': 'GEM MT 10',
        },
    },
    {
        'cert': '99746732',
        'card': {
            'name': 'Blastoise Holo',
            'year': '1999', 'set_name': 'Base Set',
            'card_number': '2', 'grade': 'MINT 9',
        },
    },
    {
        'cert': '131611480',
        'card': {
            'name': 'Mewtwo GX (Secret Rainbow)',
            'year': '2017', 'set_name': 'Shining Legends',
            'card_number': '78', 'grade': 'NM-MT 8',
        },
    },
    {
        'cert': '84566703',
        'card': {
            'name': 'Moltres',
            'year': '1998', 'set_name': 'Japanese Vending Series II',
            'card_number': '146', 'grade': 'GEM MT 10',
        },
    },
    {
        'cert': '134321907',
        'card': {
            'name': 'M Sableye & Tyranitar GX (Tag Team)',
            'year': '2019', 'set_name': 'Unified Minds',
            'card_number': '226', 'grade': 'MINT 9',
        },
    },
    {
        'cert': '63063677',
        'card': {
            'name': 'Charizard Stadium TIP-Shiny',
            'year': '2000', 'set_name': 'Danone Pokemon (French Promo)',
            'card_number': '2', 'grade': 'GEM MT 10',
        },
    },
    {
        'cert': '110772487',
        'card': {
            'name': 'FA Charizard V',
            'year': '2022', 'set_name': 'Brilliant Stars',
            'card_number': '154', 'grade': 'MINT 9',
        },
    },
    # Cleanup pass — title polish on cards whose set/name was OCR-mangled
    # but the right Pokémon was identified.
    {
        'cert': '111350109',
        'card': {
            'name': 'FA Charizard VMAX',
            'year': '2020', 'set_name': 'Shiny Star V (Japanese)',
            'card_number': '308', 'grade': 'GEM MT 10',
        },
    },
    {
        'cert': '108973922',
        'card': {
            'name': 'Origin Forme Palkia VSTAR (Gold Secret)',
            'year': '2023', 'set_name': 'Crown Zenith Galarian Gallery',
            'card_number': 'GG67', 'grade': 'GEM MT 10',
        },
    },
    {
        'cert': '75183695',
        'card': {
            'name': 'Origin Forme Dialga VSTAR (Gold Secret)',
            'year': '2023', 'set_name': 'Crown Zenith Galarian Gallery',
            'card_number': 'GG68', 'grade': 'GEM MT 10',
        },
    },
    # Fix the grader prefix on CGC and BGS slabs — title was using "PSA"
    # by default. Pass grader explicitly.
    {
        'cert': '4321131035',
        'card': {
            'name': 'Blastoise ex (Special Art Rare)',
            'year': '2023', 'set_name': 'Pokemon Card 151 (Japanese)',
            'card_number': '202/165', 'grade': '10',
            'grader': 'CGC Pristine',
        },
    },
    {
        'cert': '0014250139',
        'card': {
            'name': 'Charizard Holo',
            'year': '1999', 'set_name': 'Base Set Unlimited',
            'card_number': '4', 'grade': '8.5',
            'grader': 'BGS NM-MT+',
        },
    },
    {
        'cert': '110420477',
        'card': {
            'name': 'FA Umbreon VMAX (Alt Art)',
            'year': '2021', 'set_name': 'Evolving Skies',
            'card_number': '215', 'grade': 'MINT 9',
        },
    },
    # OCR mis-IDed this as "Team Rocket Trainer (needs review)". The PSA
    # slab label (visible after the round-2 reprocess) reads:
    #   "2025 POKEMON SVP EN / ROCKET'S WOBBUFFET / DESTINED RIVALS PC ETB
    #   / #203 / GEM MT 10". The Pokemon Center "PC" tag means it's the
    #   Pokemon Center variant of the Destined Rivals ETB exclusive.
    {
        'cert': '135860324',
        'card': {
            'name': "Rocket's Wobbuffet (Destined Rivals Pokemon Center ETB)",
            'year': '2025',
            'set_name': 'Scarlet & Violet Black Star Promos',
            'card_number': '203',
            'grade': 'GEM MT 10',
        },
    },
    # ── Today's batch corrections (verified against PSA slab OCR) ──
    {'cert': '113910492', 'card': {'name': 'FA Mewtwo V', 'year': '2022', 'set_name': 'Pokemon GO', 'card_number': '072', 'grade': 'GEM MT 10'}},
    {'cert': '106438552', 'card': {'name': 'FA Dragonite V', 'year': '2021', 'set_name': 'Evolving Skies', 'card_number': '192', 'grade': 'GEM MT 10'}},
    {'cert': '138441842', 'card': {'name': 'Umbreon Holo', 'year': '2000', 'set_name': 'Japanese Neo 2', 'card_number': '197', 'grade': 'MINT 9'}},
    {'cert': '119392108', 'card': {'name': 'Pikachu ex (Special Illustration Rare)', 'year': '2024', 'set_name': 'Surging Sparks', 'card_number': '238', 'grade': 'GEM MT 10'}},
    {'cert': '102369962', 'card': {'name': 'Charizard ex (Ultra Rare)', 'year': '2023', 'set_name': 'Obsidian Flames', 'card_number': '215', 'grade': 'GEM MT 10'}},
    {'cert': '115079776', 'card': {'name': 'Gardevoir ex (Special Illustration Rare)', 'year': '2024', 'set_name': 'Paldean Fates', 'card_number': '233', 'grade': 'GEM MT 10'}},
    {'cert': '105740011', 'card': {'name': 'FA Charizard VSTAR (Ultra Premium Collection)', 'year': '2022', 'set_name': 'SWSH Black Star Promos', 'card_number': '262', 'grade': 'GEM MT 10'}},
    {'cert': '114068076', 'card': {'name': 'Milotic ex (Special Art Rare)', 'year': '2024', 'set_name': 'Pokemon Card SV8 (Japanese)', 'card_number': '131', 'grade': 'GEM MT 10'}},
    {'cert': '113090244', 'card': {'name': 'Rowlet & Alolan Exeggutor GX (Tag Team Full Art)', 'year': '2019', 'set_name': 'Japanese Sky Legend (Sun & Moon)', 'card_number': '056', 'grade': 'GEM MT 10'}},
    {'cert': '104313030', 'card': {'name': 'Flittle (Shiny Rare)', 'year': '2024', 'set_name': 'Paldean Fates', 'card_number': '164', 'grade': 'GEM MT 10'}},
    {'cert': '120406485', 'card': {'name': 'Psyduck (Illustration Rare)', 'year': '2023', 'set_name': 'Pokemon Card 151', 'card_number': '175', 'grade': 'MINT 9'}},
    {'cert': '44690212',  'card': {'name': 'Pikachu (1st Edition)', 'year': '1999', 'set_name': 'Jungle', 'card_number': '60', 'grade': 'GEM MT 10'}},
    {'cert': '51557052',  'card': {'name': "Rocket's Scyther Holo (1st Edition)", 'year': '2000', 'set_name': 'Gym Heroes', 'card_number': '13', 'grade': 'MINT 9'}},
    {'cert': '54700750',  'card': {'name': 'Raichu Holo', 'year': '2000', 'set_name': 'Base Set 2', 'card_number': '16', 'grade': 'MINT 9'}},
    {'cert': '65570347',  'card': {'name': 'Venusaur Holo', 'year': '1999', 'set_name': 'Base Set', 'card_number': '15', 'grade': 'NM 7'}},
    {'cert': '88084896',  'card': {'name': 'Radiant Charizard', 'year': '2023', 'set_name': 'Crown Zenith', 'card_number': '020', 'grade': 'GEM MT 10'}},
    {'cert': '89676057',  'card': {'name': 'Squirtle (Art Rare)', 'year': '2023', 'set_name': 'Pokemon Card SV2a (Japanese)', 'card_number': '170', 'grade': 'GEM MT 10'}},
    {'cert': '60607369',  'card': {'name': 'Rayquaza (Amazing Rare)', 'year': '2020', 'set_name': 'Vivid Voltage', 'card_number': '138', 'grade': 'GEM MT 10'}},
    {'cert': '50358384',  'card': {'name': 'Celebi Holo', 'year': '2000', 'set_name': 'Japanese Neo 3', 'card_number': '251', 'grade': 'MINT 9'}},
    {'cert': '56276763',  'card': {'name': 'Alakazam Holo', 'year': '1999', 'set_name': 'Base Set', 'card_number': '1', 'grade': 'NM-MT 8'}},
    {'cert': '83320225',  'card': {'name': 'FA Raikou V', 'year': '2023', 'set_name': 'Crown Zenith Galarian Gallery', 'card_number': 'GG41', 'grade': 'MINT 9'}},
]


def update_one(entry, admin_token):
    body = json.dumps(entry).encode('utf-8')
    req = urllib.request.Request(
        ENDPOINT, method='POST', data=body,
        headers={
            'Content-Type': 'application/json',
            'X-Sake-Admin-Token': admin_token,
            'User-Agent':
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0 Safari/537.36',
            'Accept': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return {'http_error': e.code, 'body': body}
    except Exception as e:
        return {'error': str(e)}


def main():
    admin_token = os.environ.get('SK_ADMIN_TOKEN', '')
    if not admin_token:
        print('Set SK_ADMIN_TOKEN env var.')
        sys.exit(1)

    print(f'Updating {len(CORRECTIONS)} graded-card listing(s) via {ENDPOINT}')
    for i, entry in enumerate(CORRECTIONS, 1):
        cert = entry['cert']
        name = entry['card'].get('name', '?')
        print(f'[{i}/{len(CORRECTIONS)}] cert={cert}  -> {name}')
        res = update_one(entry, admin_token)
        if res.get('ok'):
            print(f'   updated  title="{res.get("title")}"')
        elif 'http_error' in res:
            print(f'   HTTP {res["http_error"]}: {res["body"][:200]}')
        else:
            print(f'   error: {res}')
        time.sleep(0.4)


if __name__ == '__main__':
    main()
