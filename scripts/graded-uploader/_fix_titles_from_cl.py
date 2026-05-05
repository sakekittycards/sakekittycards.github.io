"""
Fix Square graded-item titles using the latest Card Ladder export as the
format source. Target file: C:\\Users\\lunar\\Downloads\\Collection - Card
Ladder (1).csv (CL's standard 17-column export with proper headers).

For every Square graded item with a Cert # in description:
  1. Look up the matching row in the CL CSV by Slab Serial # (Notes column 14)
  2. Build the correct title as "<grader> <grade> <year> <set> <name> #<num>"
     from CL's authoritative fields
  3. If the current Square name differs, POST to /admin/update-graded
     to rewrite title + description (price + images untouched)

Does NOT touch prices. Prices were applied in an earlier sync from the
hand-typed gospel; until CL populates real Current Values, prices stay
where they are.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CL_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder (1).csv")
WORKER_BASE = "https://sakekitty-square.nwilliams23999.workers.dev"


def get_token() -> str | None:
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t: return t.strip()
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return r.stdout.strip() or None
    except Exception: return None


def fetch_square(token: str) -> list[dict]:
    req = urllib.request.Request(
        f"{WORKER_BASE}/admin/inspect?types=ITEM",
        headers={"X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0",
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("objects", [])


def is_graded(item: dict) -> bool:
    data = item.get("item_data") or {}
    name = (data.get("name") or "").lower()
    desc = (data.get("description") or "").lower()
    if "cert #" in desc: return True
    return any(k in name for k in (" psa ", " cgc ", " bgs ", " sgc ")) \
        or name.startswith(("psa ", "cgc ", "bgs ", "sgc "))


def cert_from_desc(item: dict) -> str | None:
    desc = (item.get("item_data") or {}).get("description", "") or ""
    m = re.search(r"Cert #:\s*(\d+)", desc)
    return m.group(1) if m else None


def parse_cl_grade(condition: str) -> tuple[str, str]:
    """Split 'CGC Pristine' / 'PSA 10' / 'BGS 8.5' into (grader, grade_label)
    where grade_label is what gets rendered after the grader in the title.
    For CGC Pristine slabs (no number on the slab label per CGC's convention
    but it IS effectively a 10), we render 'Pristine 10' so the shop's
    categorizer recognizes the title as graded and the customer sees the
    full grade designation."""
    s = (condition or "").strip()
    s_upper = s.upper()
    if "CGC" in s_upper: grader = "CGC"
    elif "BGS" in s_upper: grader = "BGS"
    elif "SGC" in s_upper: grader = "SGC"
    elif "PSA" in s_upper or "GEM" in s_upper: grader = "PSA"
    else: grader = "PSA"
    m = re.search(r"\d+(?:\.\d+)?", s)
    if m:
        # Has explicit number — preserve any qualifier word in proper case
        # (e.g. "CGC 8.5" -> "8.5"; "PSA 10" -> "10").
        return grader, m.group(0)
    # Qualifier-only condition. CGC Pristine implies CGC Pristine 10
    # (CGC's convention: Pristine is their highest grade, equivalent to a 10).
    qualifier = re.sub(r"^(CGC|BGS|SGC|PSA)\s*", "", s, flags=re.IGNORECASE).strip()
    if qualifier.lower() == "pristine":
        return grader, "Pristine 10"
    return grader, qualifier or "10"


def build_target_title(grader: str, grade: str, year: str, set_: str, name: str, number: str) -> str:
    parts = []
    if grader and grade: parts.append(f"{grader} {grade}".strip())
    if year: parts.append(year)
    if set_: parts.append(set_)
    if name: parts.append(name)
    if number: parts.append(f"#{number}")
    return " ".join(parts).strip()


def update_title(cert: str, card: dict, token: str) -> tuple[bool, str]:
    body = json.dumps({"cert": cert, "card": card}).encode("utf-8")
    req = urllib.request.Request(
        f"{WORKER_BASE}/admin/update-graded",
        method="POST", data=body,
        headers={"Content-Type": "application/json",
                 "X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = get_token()
    if not token: print("[fix] SK_ADMIN_TOKEN not set"); return 1
    if not CL_CSV.exists(): print(f"[fix] {CL_CSV} not found"); return 1

    # Build cert -> CL row map
    cl_by_cert: dict[str, dict] = {}
    with CL_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            cert = (r.get("Slab Serial #") or "").strip()
            if cert:
                cl_by_cert[cert] = r
    print(f"[fix] {len(cl_by_cert)} CL rows indexed by cert")

    items = fetch_square(token)
    graded = [it for it in items if is_graded(it)]
    print(f"[fix] {len(graded)} graded items on Square")

    needs_update, no_match = [], []
    for it in graded:
        cert = cert_from_desc(it)
        if not cert:
            no_match.append((it, "no cert in description"))
            continue
        clrow = cl_by_cert.get(cert)
        if not clrow:
            no_match.append((it, f"cert {cert} not in CL CSV"))
            continue
        # Build target title from CL fields
        grader, grade = parse_cl_grade(clrow.get("Condition", ""))
        year   = (clrow.get("Year") or "").strip()
        set_   = (clrow.get("Set") or "").strip()
        name   = (clrow.get("Player") or "").strip()
        number = (clrow.get("Number") or "").strip()
        target_title = build_target_title(grader, grade, year, set_, name, number)
        current_name = (it.get("item_data") or {}).get("name", "")
        if target_title and target_title != current_name:
            needs_update.append({
                "cert":         cert,
                "current":      current_name,
                "target":       target_title,
                "grader":       grader,
                "grade":        grade,
                "year":         year,
                "set_name":     set_,
                "name":         name,
                "card_number":  number,
            })

    print(f"[fix] {len(needs_update)} titles need updating, {len(no_match)} skipped")

    if args.dry_run:
        print("\n=== TITLE CHANGES ===")
        for u in needs_update[:30]:
            print(f"  cert {u['cert']}")
            print(f"    OLD: {u['current'][:90]}")
            print(f"    NEW: {u['target'][:90]}")
        if len(needs_update) > 30:
            print(f"  ... and {len(needs_update)-30} more")
        return 0

    print()
    ok = fail = 0
    for i, u in enumerate(needs_update, 1):
        success, err = update_title(
            u["cert"],
            {
                "grader":       u["grader"],
                "grade":        u["grade"],
                "year":         u["year"],
                "set_name":     u["set_name"],
                "name":         u["name"],
                "card_number":  u["card_number"],
            },
            token,
        )
        if success:
            ok += 1
            print(f"[fix] {i:>2}/{len(needs_update)} OK  cert {u['cert']}  -> {u['target'][:60]}")
        else:
            fail += 1
            print(f"[fix] {i:>2}/{len(needs_update)} ERR cert {u['cert']}  {err}")
        time.sleep(0.4)

    print(f"\n[fix] done — {ok}/{len(needs_update)} titles updated")
    if no_match:
        print(f"\n[fix] {len(no_match)} items without CL match (untouched):")
        for it, why in no_match[:10]:
            n = (it.get("item_data") or {}).get("name", "")
            print(f"  - {n[:65]}  ({why})")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
