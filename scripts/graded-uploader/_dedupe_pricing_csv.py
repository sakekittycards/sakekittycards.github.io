"""Consolidate pricing.csv against Square's canonical graded inventory.

Problem: pricing.csv has accumulated duplicate cert rows from prior upload
cycles. For 24 certs there are 2 rows each, sometimes with mismatched names
(the same cert # showing as "Latias ex" in one row and "Furfrou" in another).
Plus orphan certs that are no longer on Square (sold + delisted).

Strategy:
  1. Fetch Square's graded items via /admin/inspect (canonical source of truth)
  2. Build canonical {cert -> name} map from Square item descriptions
  3. For each cert in pricing.csv:
       a. If cert NOT on Square -> drop all its rows (orphan)
       b. If cert IS on Square -> pick the best row from its group:
            - prefer rows with [uploaded] in your_price (current Square state)
            - tie-break on completeness: name + year + set + grade non-empty
            - tie-break on identified_at (most recent wins)
  4. Write a backup of the original, then overwrite pricing.csv
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICING_CSV = HERE / "pricing.csv"
BACKUP_CSV = HERE / f"pricing.csv.bak.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT_URL = f"{WORKER_BASE}/admin/inspect?types=ITEM"


def get_token() -> str | None:
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t:
        return t.strip()
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def cert_from_description(item: dict) -> str | None:
    desc = (item.get("item_data") or {}).get("description", "") or ""
    m = re.search(r"Cert #:\s*(\d+)", desc)
    return m.group(1) if m else None


def is_graded_item(item: dict) -> bool:
    data = item.get("item_data") or {}
    name = (data.get("name") or "").lower()
    desc = (data.get("description") or "").lower()
    if "cert #" in desc:
        return True
    return any(k in name for k in (" psa ", " cgc ", " bgs ", " sgc ")) \
        or name.startswith(("psa ", "cgc ", "bgs ", "sgc "))


def fetch_square_certs(token: str) -> dict[str, str]:
    """Returns {cert_no_leading_zeros: square_item_name}."""
    req = urllib.request.Request(INSPECT_URL, headers={
        "X-Sake-Admin-Token": token,
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        inv = json.loads(r.read())
    items = inv.get("objects", [])
    out: dict[str, str] = {}
    for it in items:
        if not is_graded_item(it):
            continue
        cert = cert_from_description(it)
        if not cert:
            continue
        # Strip leading zeros to match the format used in pricing.csv
        # comparisons elsewhere
        key = cert.lstrip("0") or cert
        name = (it.get("item_data") or {}).get("name", "")
        out[key] = name
    return out


def cert_key(s: str) -> str:
    return (s or "").strip().lstrip("0")


def is_uploaded(your_price: str) -> bool:
    return (your_price or "").strip().startswith("[uploaded]")


def completeness(row: dict) -> int:
    """Higher == more complete metadata."""
    score = 0
    for k in ("name", "year", "set", "grade"):
        if (row.get(k) or "").strip():
            score += 1
    return score


def parse_identified_at(row: dict) -> str:
    return (row.get("identified_at") or "").strip()


def pick_best(rows: list[dict]) -> dict:
    """Pick the canonical row for a cert from its duplicate group."""
    if len(rows) == 1:
        return rows[0]
    return sorted(
        rows,
        key=lambda r: (
            is_uploaded(r.get("your_price", "")),
            completeness(r),
            parse_identified_at(r),
        ),
        reverse=True,
    )[0]


def main() -> None:
    token = get_token()
    if not token:
        print("[dedupe] SK_ADMIN_TOKEN not set; aborting")
        return

    print("[dedupe] fetching Square graded inventory...")
    square_certs = fetch_square_certs(token)
    print(f"[dedupe] Square has {len(square_certs)} graded items")

    rows = list(csv.DictReader(PRICING_CSV.open("r", encoding="utf-8")))
    fields = list(rows[0].keys()) if rows else []
    print(f"[dedupe] pricing.csv has {len(rows)} rows")

    # Group by normalized cert
    groups: dict[str, list[dict]] = {}
    for r in rows:
        ck = cert_key(r.get("cert", ""))
        if not ck:
            continue
        groups.setdefault(ck, []).append(r)

    kept: list[dict] = []
    dropped_orphan: list[str] = []
    consolidated: list[tuple[str, int]] = []

    for ck, group in groups.items():
        if ck not in square_certs:
            dropped_orphan.append(ck)
            continue
        if len(group) > 1:
            consolidated.append((ck, len(group)))
        kept.append(pick_best(group))

    # Sort kept rows by cert for stability
    kept.sort(key=lambda r: cert_key(r.get("cert", "")))

    print(f"[dedupe]   kept: {len(kept)} rows ({len(consolidated)} consolidated)")
    print(f"[dedupe]   dropped orphan certs: {len(dropped_orphan)}")
    if dropped_orphan:
        for c in dropped_orphan[:20]:
            sq_name = square_certs.get(c, "<not on Square>")
            print(f"           - {c}  (sq: {sq_name})")
        if len(dropped_orphan) > 20:
            print(f"           ... and {len(dropped_orphan) - 20} more")

    # Backup
    shutil.copy2(PRICING_CSV, BACKUP_CSV)
    print(f"[dedupe] backup written: {BACKUP_CSV.name}")

    # Write cleaned pricing.csv
    with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in kept:
            w.writerow(r)
    print(f"[dedupe] pricing.csv rewritten: {len(kept)} unique-cert rows")


if __name__ == "__main__":
    main()
