"""pop_fetch.py — fill in PSA pop columns on pop_and_profit_<date>.csv.

Reads the output of pop_and_profit.py and, for each row missing pop data,
emits a WebSearch query the caller (Claude) should run. The caller pastes the
search-result snippets back into a sidecar JSON, then re-runs this with
--apply to merge the answers into the CSV.

Two-phase intentionally — pop reports are anti-bot-protected so we can't
scrape directly; the human-in-the-loop step is brief per card.

Usage:
    python pop_fetch.py --emit       # print one search query per missing card
    python pop_fetch.py --apply      # merge pop_answers.json into the CSV
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TODAY = date.today().isoformat()
CSV_PATH = HERE / f"_pop_and_profit_report_{TODAY}.csv"
ANSWERS_PATH = HERE / f"_pop_answers_{TODAY}.json"
QUERIES_PATH = HERE / f"_pop_queries_{TODAY}.json"

# Set name -> short identifier used in search queries (drops noisy prefixes
# like "Obf En-" / "Meg En-" that PriceCharting and PSA both ignore)
SET_SHORT = {
    "Obf En-Obsidian Flames": "Obsidian Flames",
    "Meg En-Mega Evolution": "Mega Evolution",
    "Pre En-Prismatic Evolutions": "Prismatic Evolutions",
    "Paf En-Paldean Fates": "Paldean Fates",
    "Svp En-Sv Black Star Promo": "SVP Black Star Promo",
    "Sword and Shield Crown Zenith": "Crown Zenith",
    "Sword & Shield: Brilliant Stars": "Brilliant Stars",
    "Sword & Shield: Fusion Strike": "Fusion Strike",
    "Sword & Shield: Evolving Skies": "Evolving Skies",
    "Sword & Shield Evolving Skies": "Evolving Skies",
    "Sword & Shield VIVID Voltage": "Vivid Voltage",
    "Sun & Moon Shining Legends": "Shining Legends",
    "Sun & Moon Unified Minds": "Unified Minds",
    "Celebrations - Classic Coll.": "Celebrations Classic Collection",
    "Card 151 Japanese": "Japanese 151",
    "Simplified Chinese 151 C-Collection 151": "Chinese 151",
    "Xy Evolutions": "Evolutions",
    "Game": "Base Set",  # ambiguous; user can refine
    "Premium Trainer Xy Collection Promo": "Roaring Skies",
}


def short_set(name: str) -> str:
    return SET_SHORT.get(name, name)


_PRISTINE_HEAD = re.compile(r"^pristine\s+\d{4}\s+", re.IGNORECASE)


def clean_name(name: str, set_name: str) -> str:
    s = _PRISTINE_HEAD.sub("", name)
    sn = set_name.strip()
    if sn and s.lower().startswith(sn.lower() + " "):
        s = s[len(sn) + 1:]
    # Strip noisy "Fa /" prefix
    s = re.sub(r"^fa\s*/\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def build_query(row: dict) -> str:
    name = clean_name(row["name"], row["set"])
    set_short = short_set(row["set"])
    number = row["number"].split("/")[0] if row["number"] else ""
    return f"PSA pop report {name} {set_short} #{number} grade 10 grade 9 grade 8"


def emit():
    rows = list(csv.DictReader(CSV_PATH.open("r", encoding="utf-8")))
    queries = [{"cert": r["cert"], "query": build_query(r)} for r in rows]

    QUERIES_PATH.write_text(json.dumps(queries, indent=2, ensure_ascii=False), encoding="utf-8")
    queries_path = QUERIES_PATH

    # Print with replacement encoding for safety on Windows cp1252 consoles
    out = sys.stdout
    try:
        out.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(f"# {len(rows)} cards - pop search queries")
    print(f"# Queries written to: {queries_path}\n")
    for q in queries:
        print(f"[{q['cert']}]  {q['query']}")


def apply():
    if not ANSWERS_PATH.exists():
        print(f"ERROR: expected answers file at {ANSWERS_PATH}", file=sys.stderr)
        sys.exit(1)
    answers = {a["cert"]: a for a in json.loads(ANSWERS_PATH.read_text())}

    rows = list(csv.DictReader(CSV_PATH.open("r", encoding="utf-8")))
    fieldnames = list(rows[0].keys())

    updated = 0
    for r in rows:
        a = answers.get(r["cert"])
        if not a:
            continue
        r["psa_pop_current_grade"] = str(a.get("pop_current", ""))
        r["psa_pop_psa10"] = str(a.get("pop_psa10", ""))
        r["psa_pop_psa9"] = str(a.get("pop_psa9", ""))
        r["pop_source"] = a.get("source", "")
        updated += 1

    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Merged pop data for {updated}/{len(rows)} rows into {CSV_PATH.name}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--emit", action="store_true", help="Print one query per missing row")
    g.add_argument("--apply", action="store_true", help="Merge pop_answers.json into the CSV")
    args = p.parse_args()

    if args.emit:
        emit()
    elif args.apply:
        apply()
