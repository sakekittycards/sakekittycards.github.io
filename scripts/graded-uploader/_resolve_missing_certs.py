"""
For each cert in _missing_certs_template.csv, walk every PNG in
inbox/_processed/, full-image OCR each one, find the IMG pair that
contains the cert number, then OCR the slab label and extract:
year, set, name, card_number, grade, grader.

Writes the filled-out template back to disk so the user can sanity-
check before uploading. Also writes _missing_cert_to_imgs.json so the
upload step knows which IMG pair to feed into the pipeline.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

HERE = Path(__file__).parent
PROCESSED = HERE / 'inbox' / '_processed'
INBOX = HERE / 'inbox'  # also OCR loose files in inbox/ that process_inbox didn't pair
TEMPLATE = HERE / '_missing_certs_template.csv'
OUT_MAP = HERE / '_missing_cert_to_imgs.json'


def ocr_full(ocr, img: Image.Image) -> tuple[str, list[str]]:
    """Return (digits-only blob, raw lines) for substring + structured
    matching."""
    arr = np.asarray(img)
    result, _ = ocr(arr)
    if not result:
        return '', []
    lines: list[str] = []
    for entry in result:
        for x in entry:
            if isinstance(x, str):
                lines.append(x)
                break
    blob = ' '.join(lines)
    digits_only = re.sub(r'\D', '', blob)
    return digits_only, lines


def parse_label(lines: list[str]) -> dict:
    """Pull the structured fields out of OCR'd slab label lines.

    Targets PSA's two-line format like:
        "2023 POKEMON SVP EN" / "PIKACHU/GREY FELT HAT" / "POKEMON X VAN GOGH"
        "#085 GEMMT 10 102607615"
    Plus CGC's variant ("Pokémon (2023) Japanese", "Pokémon Card 151 - 202/165",
    "PRISTINE 10") and BGS ("1999 BASE UNLIMITED #4 CHARIZARD HOLO R / 8.5 NM-MT+").

    Best-effort — anything we can't parse stays blank, the user fills it.
    """
    out = {'year': '', 'set': '', 'name': '', 'number': '',
           'grade': '', 'grader': ''}
    big = ' '.join(lines).upper()

    # Grader detection — look for distinctive markers.
    if 'CGC' in big or 'PRISTINE' in big or 'CERTIFIED GUARANTY' in big:
        out['grader'] = 'CGC'
    elif 'BGS' in big or 'BECKETT' in big or 'NM-MT+' in big:
        out['grader'] = 'BGS'
    elif 'SGC' in big:
        out['grader'] = 'SGC'
    else:
        out['grader'] = 'PSA'

    # Year — first 4-digit 19xx/20xx
    m = re.search(r'\b(19\d{2}|20\d{2})\b', big)
    if m:
        out['year'] = m.group(1)

    # Grade — number after "GEMMT", "MINT", "NM-MT+", "PRISTINE", "GEM MT"
    grade_patterns = [
        (r'GEM\s*MT\s*([0-9]+(?:\.[0-9])?)', 'GEM MT'),
        (r'GEMMT\s*([0-9]+(?:\.[0-9])?)', 'GEM MT'),
        (r'PRISTINE\s*([0-9]+(?:\.[0-9])?)', 'PRISTINE'),
        (r'NM-?MT\+?\s*([0-9]+(?:\.[0-9])?)', 'NM-MT+'),
        (r'MINT\s*([0-9]+(?:\.[0-9])?)', 'MINT'),
    ]
    for pat, prefix in grade_patterns:
        m = re.search(pat, big)
        if m:
            out['grade'] = f'{prefix} {m.group(1)}'
            break

    # Card number — # followed by digits/letters (e.g. #085, #GG67, #202/165)
    m = re.search(r'#\s*([A-Z0-9]+(?:/\d+)?)', big)
    if m:
        out['number'] = m.group(1).lstrip('0') or '0'

    # Name + Set are the harder fields. Heuristic: the label has lines
    # like "<NAME>" alone or "<SET-NAME>" alone. Without templates per
    # grader it's brittle to extract reliably — leave both blank by
    # default and let the user fill those two.
    # (Future: train a regex per grader; for now structured extraction
    # is good enough for year/grade/cert/grader.)

    return out


def main():
    # Load missing certs from template (has cert + price pre-filled)
    if not TEMPLATE.exists():
        print(f'ERROR: {TEMPLATE} not found')
        sys.exit(1)
    rows: list[dict] = []
    fieldnames: list[str] = []
    with TEMPLATE.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    targets = {r['cert'].strip(): r for r in rows if r.get('cert')}
    print(f'Looking for {len(targets)} missing certs in {PROCESSED}')

    # OCR every IMG in _processed once and cache the result. Heavy
    # operation; cache to disk so re-runs are cheap.
    cache_path = HERE / '_missing_ocr_cache.json'
    cache: dict[str, dict] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding='utf-8'))

    # Walk both _processed/ AND any loose IMG files in inbox/ — process_inbox
    # leaves unmatched scans in inbox/, and the user's missing certs are
    # likely sitting there (failed front+back pairing or OCR mis-read).
    files: list[Path] = []
    files.extend(p for p in PROCESSED.iterdir() if p.suffix.lower() == '.png')
    files.extend(p for p in INBOX.iterdir() if p.is_file() and p.suffix.lower() == '.png')
    files = sorted(files, key=lambda p: p.name)
    print(f'OCRing {len(files)} files (cache hits skip OCR)')

    print('Loading RapidOCR...')
    ocr = RapidOCR()

    for i, f in enumerate(files, 1):
        if f.name in cache:
            continue
        try:
            img = Image.open(f).convert('RGB')
            digits, lines = ocr_full(ocr, img)
            cache[f.name] = {'digits': digits, 'lines': lines}
            if i % 10 == 0:
                print(f'  [{i}/{len(files)}] ocred')
                cache_path.write_text(json.dumps(cache, indent=2), encoding='utf-8')
        except Exception as e:
            print(f'  {f.name}: ERROR {e}', file=sys.stderr)

    cache_path.write_text(json.dumps(cache, indent=2), encoding='utf-8')

    # Match each missing cert to its IMG pair
    cert_to_imgs: dict[str, list[str]] = {}
    for cert in sorted(targets.keys()):
        matches = [name for name, c in cache.items() if cert in c['digits']]
        cert_to_imgs[cert] = sorted(matches)
        if not matches:
            print(f'  {cert}: NOT FOUND in any scan')
            continue
        print(f'  {cert}: {matches}')

    OUT_MAP.write_text(json.dumps(cert_to_imgs, indent=2), encoding='utf-8')
    print(f'\nWrote {OUT_MAP}')

    # For each match, parse the front (odd-numbered IMG) to fill metadata
    for r in rows:
        cert = r['cert'].strip()
        imgs = cert_to_imgs.get(cert, [])
        if not imgs:
            continue
        # The front IMG is typically the lower number (or odd) — try both
        front_name = imgs[0]
        lines = cache.get(front_name, {}).get('lines', [])
        meta = parse_label(lines)
        for k, v in meta.items():
            # Only fill blanks; never overwrite user input
            if not r.get(k, '').strip() and v:
                r[k] = v

    with TEMPLATE.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f'Updated {TEMPLATE} with auto-extracted metadata where possible.')

    # Summary
    found = sum(1 for c in cert_to_imgs.values() if c)
    print(f'\nFound {found}/{len(targets)} certs.')
    missing = [c for c, imgs in cert_to_imgs.items() if not imgs]
    if missing:
        print(f'Still missing: {missing}')


if __name__ == '__main__':
    main()
