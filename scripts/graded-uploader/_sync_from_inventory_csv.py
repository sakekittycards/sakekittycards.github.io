"""
Single source of truth pass: sync Square graded catalog against
D:\\Dropbox\\Personal Use\\sakekitty_inventory_full.csv.

This file is the user's authoritative inventory list. Each row:
    card_id (SK-26-G-NNNN), qr_value, name, set, number, price, condition

Algorithm:
    1. Read inventory CSV; for each row apply the markup formula
       (<$200: x1.15+$3, $200..$999: x1.10+$10, >=$1000: x1.08; snap to 0/5).
    2. Inspect Square graded items; parse (grade, number) from each name.
    3. Match Square items against inventory by (grade_norm, number_norm),
       with name-token tiebreaker if multiple inventory rows share the key.
    4. KEEP+UPDATE: matched Square items get the new price via
       /admin/update-graded-price.
    5. DELETE: Square items NOT in inventory get removed via /admin/delete-item.
    6. NEW (NOT ON SQUARE): inventory rows with no Square match are written
       to _inventory_pending_upload.csv for the image-processing pipeline to
       pick up later.

Run with --dry-run to preview.
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

# `re` is imported above; format-detection regex needs it.

HERE = Path(__file__).resolve().parent
INVENTORY_CSV = Path(r"D:\Dropbox\Personal Use\sakekitty_inventory_full.csv")
GOSPEL_CSV    = Path(r"C:\Users\lunar\Downloads\cardladder_import - Sheet1 (1).csv")
PENDING_OUT   = HERE / "_inventory_pending_upload.csv"
WORKER_BASE   = "https://sakekitty-square.nwilliams23999.workers.dev"


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


# ── Pricing helpers ────────────────────────────────────────────────────────
def markup(base: float) -> float:
    """User-mandated 2026-05-05 — softer schedule (replaces the earlier
    1.15+3/1.10+10/1.08 tier). Still above market everywhere, but trimmed
    by ~3 percentage points on the multiplier and ~half on the flat add."""
    if base < 200: return base * 1.10 + 2
    if base < 1000: return base * 1.07 + 5
    return base * 1.05

def snap_clean(p: float) -> int:
    """Round to nearest integer ending in 0 or 5; ties round up."""
    if p <= 0: return 0
    base = int(round(p))
    cands = [n for n in range(max(1, base-6), base+7) if n % 5 == 0]
    cands.sort(key=lambda n: (abs(n-p), -n))
    return cands[0]


# ── Normalization ──────────────────────────────────────────────────────────
def normalize_grade(s: str) -> str:
    s = (s or "").upper()
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    num = nums[0] if nums else ""
    grader = ""
    if "BGS" in s: grader = "BGS"
    elif "CGC" in s: grader = "CGC"
    elif "SGC" in s: grader = "SGC"
    elif "PSA" in s or "GEM" in s or "MT" in s: grader = "PSA"
    return f"{grader}{num}"

def normalize_number(s: str) -> str:
    s = (s or "").strip().upper()
    m = re.match(r"^([A-Z]*)(\d+)$", s)
    if m: return f"{m.group(1)}{int(m.group(2))}"
    return re.sub(r"\s+", "", s)

def name_tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower())
            if len(t) > 1 and t not in {"with","the","a","an","of","and","or","in","on"}}


# ── Square API helpers ────────────────────────────────────────────────────
def _hdrs(token: str) -> dict:
    return {"X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json", "Accept": "application/json"}

def fetch_square(token: str) -> list[dict]:
    req = urllib.request.Request(f"{WORKER_BASE}/admin/inspect?types=ITEM", headers=_hdrs(token))
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("objects", [])

def is_graded(item: dict) -> bool:
    data = item.get("item_data") or {}
    name = (data.get("name") or "").lower()
    desc = (data.get("description") or "").lower()
    if "cert #" in desc: return True
    return any(k in name for k in (" psa "," cgc "," bgs "," sgc ")) \
        or name.startswith(("psa ","cgc ","bgs ","sgc "))

def cert_from_desc(item: dict) -> str | None:
    desc = (item.get("item_data") or {}).get("description","") or ""
    m = re.search(r"Cert #:\s*(\d+)", desc)
    return m.group(1) if m else None

def parse_square_grade_number(name: str) -> tuple[str, str]:
    grader_m = re.search(r"\b(PSA|CGC|BGS|SGC)\b", name, re.IGNORECASE)
    num_m = re.search(r"\b(\d+(?:\.\d)?)\b", name[grader_m.end():] if grader_m else "")
    grade_norm = ""
    if grader_m and num_m:
        grade_norm = normalize_grade(f"{grader_m.group(1)} {num_m.group(1)}")
    num_field_m = re.search(r"#([A-Za-z]*\d+(?:/\d+)?)", name)
    number_norm = normalize_number(num_field_m.group(1)) if num_field_m else ""
    return grade_norm, number_norm

def update_price(cert: str, price_cents: int, token: str) -> tuple[bool, str]:
    body = json.dumps({"cert": cert, "price_cents": price_cents}).encode("utf-8")
    req = urllib.request.Request(f"{WORKER_BASE}/admin/update-graded-price",
                                 method="POST", data=body, headers=_hdrs(token))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}"
    except Exception as e:
        return False, str(e)

def delete_item(item_id: str, token: str) -> tuple[bool, str]:
    body = json.dumps({"item_id": item_id}).encode("utf-8")
    req = urllib.request.Request(f"{WORKER_BASE}/admin/delete-item",
                                 method="POST", data=body, headers=_hdrs(token))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}"
    except Exception as e:
        return False, str(e)


# ── Main flow ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = get_token()
    if not token: print("[sync] SK_ADMIN_TOKEN not set"); return 1

    # Prefer the Card Ladder import CSV (gospel) when present — that's the
    # user's hand-typed truth list. Fall back to sakekitty_inventory_full.csv
    # if the gospel hasn't been refreshed.
    inv: list[dict] = []
    if GOSPEL_CSV.exists():
        # Card Ladder import format, no header. Field positions:
        # 0=date, 1=qty, 2=name, 3=year, 4=set, 5=variation, 6=number,
        # 7=category, 8=condition, 9=investment, 10=condition_repeat,
        # 11=cert, 12=current_value, 13=sk_code
        print(f"[sync] reading Card Ladder gospel CSV: {GOSPEL_CSV.name}")
        with GOSPEL_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if not row or len(row) < 14: continue
                # First row may be a header — skip if column 1 isn't numeric
                if not row[1].strip().isdigit(): continue
                # Detect format by position 3: 4-digit year = short format,
                # otherwise full 17-col format (where position 3 is Player name).
                pos3 = (row[3] or "").strip()
                is_short = bool(re.fullmatch(r"\d{4}", pos3))
                if is_short:
                    name      = row[2].strip()
                    year      = row[3].strip()
                    set_      = row[4].strip()
                    number    = row[6].strip()
                    condition = row[8].strip()
                    cert      = row[11].strip()
                    try: base = float((row[12] or "0").replace(",", "").strip() or "0")
                    except: continue
                    sk        = row[13].strip() if len(row) > 13 else ""
                else:
                    # Full 17-col format: 0=Date, 1=Qty, 2=Card title, 3=Player,
                    # 4=Year, 5=Set, 6=Variation, 7=Number, 8=Category, 9=Condition,
                    # 10=Investment, 11=CurrentValue, 12=Profit, 13=LadderId,
                    # 14=SlabSerial, 15=Population, 16=Notes
                    name      = row[3].strip()
                    year      = row[4].strip() if len(row) > 4 else ""
                    set_      = row[5].strip() if len(row) > 5 else ""
                    number    = row[7].strip() if len(row) > 7 else ""
                    condition = row[9].strip() if len(row) > 9 else ""
                    cert      = row[14].strip() if len(row) > 14 else ""
                    try: base = float((row[11] or "0").replace(",", "").strip() or "0")
                    except: continue
                    sk        = row[16].strip() if len(row) > 16 else ""
                if base <= 0 or not name: continue
                inv.append({
                    "sk":       sk,
                    "name":     name,
                    "set":      set_,
                    "number":   number,
                    "condition":condition,
                    "year":     year,
                    "cert":     cert,
                    "base":     base,
                    "final":    snap_clean(markup(base)),
                    "g_norm":   normalize_grade(condition),
                    "n_norm":   normalize_number(number),
                    "tokens":   name_tokens(name),
                })
    elif INVENTORY_CSV.exists():
        print(f"[sync] reading inventory CSV: {INVENTORY_CSV.name}")
        with INVENTORY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                try: base = float((r.get("price") or "0").replace(",", "").strip() or "0")
                except: continue
                if base <= 0: continue
                inv.append({
                    "sk":       (r.get("card_id") or "").strip(),
                    "name":     (r.get("name") or "").strip(),
                    "set":      (r.get("set") or "").strip(),
                    "number":   (r.get("number") or "").strip(),
                    "condition":(r.get("condition") or "").strip(),
                    "year":     "",
                    "cert":     "",
                    "base":     base,
                    "final":    snap_clean(markup(base)),
                    "g_norm":   normalize_grade(r.get("condition") or ""),
                    "n_norm":   normalize_number(r.get("number") or ""),
                    "tokens":   name_tokens(r.get("name") or ""),
                })
    else:
        print(f"[sync] no input CSV found at {GOSPEL_CSV} or {INVENTORY_CSV}"); return 1
    print(f"[sync] inventory: {len(inv)} cards")

    # Two indexes: by cert (primary, exact) and by (grade, number) (fallback).
    inv_by_cert: dict[str, dict] = {}
    inv_by_key:  dict[tuple, list[dict]] = {}
    for row in inv:
        if row.get("cert"):
            inv_by_cert[row["cert"]] = row
        inv_by_key.setdefault((row["g_norm"], row["n_norm"]), []).append(row)

    # ── Step 2: Inspect Square ──
    items = fetch_square(token)
    graded = [it for it in items if is_graded(it)]
    print(f"[sync] Square: {len(items)} items, {len(graded)} graded")

    # ── Step 3: Match Square → inventory ──
    # Pass 1: cert-exact (strongest signal, comes straight from PSA/CGC slab).
    # Pass 2: (grade, number) with name-token tiebreaker for items where the
    # Square cert isn't in the gospel CSV (older listings, OCR misses).
    used_inv = set()
    keep, delete = [], []
    for it in graded:
        name = (it.get("item_data") or {}).get("name", "")
        cert = cert_from_desc(it)
        g, n = parse_square_grade_number(name)
        match = None
        if cert and cert in inv_by_cert and id(inv_by_cert[cert]) not in used_inv:
            match = inv_by_cert[cert]
        if match is None and n:
            cands = inv_by_key.get((g, n), [])
            sq_tokens = name_tokens(name)
            best, best_score = None, -1
            for c in cands:
                if id(c) in used_inv: continue
                overlap = len(c["tokens"] & sq_tokens)
                if overlap > best_score:
                    best, best_score = c, overlap
            match = best
        if match is not None:
            used_inv.add(id(match))
            keep.append((it, cert, name, match))
        elif not n:
            delete.append((it, cert, name, "no card number parsed"))
        else:
            delete.append((it, cert, name, f"no inventory row with cert={cert} or grade={g} num={n}"))

    pending = [c for c in inv if id(c) not in used_inv]

    print(f"[sync]   keep + price-update: {len(keep)}")
    print(f"[sync]   delete (Square but not in inventory): {len(delete)}")
    print(f"[sync]   pending upload (in inventory but not on Square): {len(pending)}")

    if args.dry_run:
        print()
        print("=== KEEP & PRICE-UPDATE ===")
        for it, cert, name, c in keep[:20]:
            print(f"  cert {cert or '?'}  ${c['final']:>5}  {name[:80]}")
        if len(keep) > 20: print(f"  ... and {len(keep)-20} more")
        print()
        print("=== DELETE ===")
        for it, cert, name, why in delete:
            print(f"  cert {cert or '?'}  {name[:78]}  ({why})")
        print()
        print("=== PENDING UPLOAD (inventory, no Square match) ===")
        for c in pending:
            print(f"  {c['sk']}  ${c['final']:>5}  {c['name']:<22} {c['set'][:30]:<30} #{c['number']:<10} {c['condition']}")
        print("\n[sync] DRY RUN — no changes made")
        return 0

    # ── Execute updates ──
    print()
    print("[sync] === Updating prices ===")
    upd_ok = upd_fail = 0
    for it, cert, name, c in keep:
        if not cert:
            print(f"[sync] SKIP no cert in description for {name[:60]}"); upd_fail += 1; continue
        ok, err = update_price(cert, c["final"] * 100, token)
        if ok:
            upd_ok += 1
            print(f"[sync] UPD cert {cert}  ${c['final']:>5}  {c['name'][:55]}")
        else:
            upd_fail += 1
            print(f"[sync] ERR cert {cert}  {err}")
        time.sleep(0.4)

    # ── Execute deletes ──
    print()
    print("[sync] === Deleting items not in inventory ===")
    del_ok = del_fail = 0
    for it, cert, name, why in delete:
        ok, err = delete_item(it.get("id"), token)
        if ok:
            del_ok += 1
            print(f"[sync] DEL cert {cert or '?'}  {name[:65]}")
        else:
            del_fail += 1
            print(f"[sync] ERR cert {cert or '?'}  {err}")
        time.sleep(0.3)

    # ── Write pending-upload manifest ──
    if pending:
        with PENDING_OUT.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sk_code","name","set","number","condition","price"])
            for c in pending:
                w.writerow([c["sk"], c["name"], c["set"], c["number"], c["condition"], c["final"]])
        print()
        print(f"[sync] {len(pending)} cards written to {PENDING_OUT.name} for image processing")

    print()
    print(f"[sync] done — updated {upd_ok}/{len(keep)}, deleted {del_ok}/{len(delete)}, "
          f"{len(pending)} pending upload  (failures: {upd_fail} upd + {del_fail} del)")
    return 0 if (upd_fail + del_fail) == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
