"""
Reprice every graded card on the site against the latest Card Ladder CSV.

For each cert in pricing.csv:
  1. Look up Current Value in the Card Ladder CSV.
  2. Apply the locked aggressive formula:
       Base < $200      ->  CV * 1.15 + 3
       $200..$999       ->  CV * 1.10 + 10
       Base >= $1000    ->  CV * 1.08
     Snap to nearest $5.
  3. If pricing.csv row is NOT marked [uploaded], stamp the new price into
     `your_price` so upload_to_square.py picks it up on the next pass.
  4. If pricing.csv row IS [uploaded], push the new price to Square via
     /admin/update-graded-price (only if it differs from current).

Run with --dry-run to preview changes first.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICING_CSV = HERE / "pricing.csv"
EDIT_CSV = HERE / "pricing-edit.csv"
CARD_LADDER_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder (19).csv")
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
    except Exception:
        return None


def markup(base: float) -> float:
    if base < 200:
        return base * 1.15 + 3
    if base < 1000:
        return base * 1.10 + 10
    return base * 1.08


def snap_clean(price: float) -> int:
    if price <= 0: return 0
    base = int(round(price))
    candidates = [n for n in range(max(1, base - 6), base + 7) if n % 5 == 0]
    candidates.sort(key=lambda n: (abs(n - price), -n))
    return candidates[0]


def load_cl_values(path: Path) -> dict[str, tuple[float, float, str]]:
    """Return {cert: (current_value, investment, display_name)}."""
    out: dict[str, tuple[float, float, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            cert = (row.get("Graded Cert #") or "").strip()
            if not cert: continue
            try:
                cv = float((row.get("Current Value") or "0").replace(",", "").strip() or "0")
            except ValueError:
                continue
            try:
                inv = float((row.get("Investment") or "0").replace(",", "").strip() or "0")
            except ValueError:
                inv = 0.0
            name = (row.get("Card") or "").strip()
            out[cert] = (cv, inv, name)
    return out


def parse_uploaded(raw: str) -> tuple[bool, float | None]:
    """Return (is_uploaded, current_price). '[uploaded]265' -> (True, 265.0)."""
    if not raw: return (False, None)
    s = raw.strip()
    uploaded = s.startswith("[uploaded]")
    if uploaded:
        s = s[len("[uploaded]"):]
    s = s.lstrip("$").replace(",", "").strip()
    try:
        return (uploaded, float(s)) if s else (uploaded, None)
    except ValueError:
        return (uploaded, None)


def update_price_on_square(cert: str, price_cents: int, token: str) -> tuple[bool, str]:
    body = json.dumps({"cert": cert, "price_cents": price_cents}).encode("utf-8")
    req = urllib.request.Request(
        f"{WORKER_BASE}/admin/update-graded-price", method="POST", data=body,
        headers={"X-Sake-Admin-Token": token, "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 -> utf-8
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cl-csv", type=Path, default=None,
                    help="Override the Card Ladder CSV path (default: latest Collection - Card Ladder (N).csv in Downloads)")
    args = ap.parse_args()

    cl_csv = args.cl_csv or CARD_LADDER_CSV
    if not cl_csv.exists():
        print(f"[rp] Card Ladder CSV not found: {cl_csv}")
        return 1

    cl = load_cl_values(cl_csv)
    print(f"[rp] Loaded {len(cl)} certs from {cl_csv.name}")

    # Load pricing.csv
    with PRICING_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys()) if rows else []

    # Actions:
    #   no-change      — formula matches current sticker
    #   update-square  — formula proposes a HIGHER sticker; push it
    #   skip-floor     — formula proposes a LOWER sticker; HOLD current (sticky)
    #   skip-override  — manual override row, never touched
    #   stamp-new      — not yet uploaded, stamp price for first-time upload
    plan = []   # (cert, action, current_price, new_price, base, name, note)
    for row in rows:
        cert = (row.get("cert") or "").strip()
        if not cert: continue
        # Honor manual overrides — never let the formula clobber a hand-set price
        if "manual override" in (row.get("condition_note") or "").lower():
            uploaded, cur = parse_uploaded(row.get("your_price", ""))
            plan.append((cert, "skip-override", cur, cur, None, row.get("name", ""), "manual override"))
            continue
        meta = cl.get(cert)
        if not meta:
            plan.append((cert, "skip-no-cl", None, None, None, row.get("name", ""), "not in CL CSV"))
            continue
        cv, inv, cl_name = meta
        if cv <= 0:
            plan.append((cert, "skip-no-cv", None, None, None, row.get("name", ""), "CL CV is 0"))
            continue
        new_price = snap_clean(markup(cv))
        uploaded, cur = parse_uploaded(row.get("your_price", ""))
        note = ""
        if inv and new_price < inv:
            note = f"UNDER COST (paid ${inv:.0f})"
        if uploaded:
            if cur is not None and abs(cur - new_price) < 0.01:
                plan.append((cert, "no-change", cur, new_price, cv, cl_name, note))
            elif cur is not None and new_price < cur:
                # Sticky floor: one outlier comp shouldn't tank the sticker.
                # CL CV reflects recent solds; a single low sale drops CV
                # enough that the formula proposes a lower sticker than what
                # we know clears. Hold the line — only raise, never auto-lower.
                hold_note = f"hold (CL says ${new_price}, keep ${cur:.0f})"
                plan.append((cert, "skip-floor", cur, new_price, cv, cl_name, hold_note))
            else:
                plan.append((cert, "update-square", cur, new_price, cv, cl_name, note))
        else:
            plan.append((cert, "stamp-new", cur, new_price, cv, cl_name, note))

    # Print plan
    print()
    print(f"{'cert':<12} {'action':<14} {'cur':>7} {'new':>7} {'base':>9}  card  notes")
    counts = {"no-change": 0, "update-square": 0, "skip-floor": 0, "stamp-new": 0, "skip-no-cl": 0, "skip-no-cv": 0, "skip-override": 0}
    for cert, action, cur, new, base, name, note in plan:
        cur_s = f"${cur:.0f}" if cur is not None else "-"
        new_s = f"${new:.0f}" if new is not None else "-"
        base_s = f"${base:.2f}" if base is not None else "-"
        flag = "  <<<" if action == "update-square" and note else ""
        print(f"{cert:<12} {action:<14} {cur_s:>7} {new_s:>7} {base_s:>9}  {name[:55]} {note}{flag}")
        counts[action] = counts.get(action, 0) + 1
    print()
    print(f"[rp] Plan: {counts}")

    if args.dry_run:
        print("[rp] DRY RUN — no writes")
        return 0

    # 1. Stamp prices into pricing.csv for both stamp-new (8) and update-square (rewrite line)
    new_rows = []
    for row, (cert, action, cur, new, _, _, _) in zip(rows, plan):
        if action == "stamp-new" and new:
            row["your_price"] = f"{new}"
        elif action == "update-square" and new:
            # Bump the [uploaded] price in the CSV so it tracks the new Square price
            row["your_price"] = f"[uploaded]{new}"
        new_rows.append(row)

    with PRICING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(new_rows)
    print(f"[rp] pricing.csv updated.")

    # 2. Push the update-square ones to Square
    token = get_token()
    if not token:
        print("[rp] SK_ADMIN_TOKEN not set — cannot push Square updates. Stamped prices only.")
        return 0

    updates = [(cert, new) for cert, action, _, new, *_ in plan if action == "update-square" and new]
    if not updates:
        print("[rp] No Square price changes to push.")
        return 0

    print(f"[rp] Pushing {len(updates)} price updates to Square …")
    ok = fail = 0
    for i, (cert, new) in enumerate(updates, 1):
        cents = int(round(new * 100))
        success, err = update_price_on_square(cert, cents, token)
        if success:
            ok += 1
            print(f"  {i:>2}/{len(updates)} OK  cert {cert}  ${new}")
        else:
            fail += 1
            print(f"  {i:>2}/{len(updates)} ERR cert {cert}  {err}")
        time.sleep(0.25)

    print()
    print(f"[rp] Done — {ok} updated, {fail} failed.")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
