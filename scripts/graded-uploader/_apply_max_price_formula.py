"""Multi-source max-price formula for graded card pricing.

For each row in the Card Ladder CSV, gather the base price from up to three
sources and use whichever is HIGHEST (user policy 2026-05-05):
  - Card Ladder Current Value (always available)
  - PriceCharting graded value (via productId lookup against pc-graded.json)
  - 130point sales average (via the sakekitty-prices worker)

Then apply the TIGHTENED tier markup (replaces 2026-05-05 morning's softer tiers):
  Base < $200:    Price = Base * 1.08 + $2
  $200..$999:     Price = Base * 1.04 + $5
  Base >= $1000:  Price = Base * 1.02

Snap to nearest $5.

Outputs:
  - _card_ladder_prices.csv (drop-in for _match_card_ladder_to_pricing.py)
    extra columns: src_cl, src_pc, src_130p, src_winner
"""
from __future__ import annotations

import csv
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
CARD_LADDER_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder.csv")
OUT_PATH = Path(__file__).resolve().parent / "_card_ladder_prices.csv"
PC_GRADED_PATH = REPO_DIR / "assets" / "pc-graded.json"
ALL_CARDS_PATH = REPO_DIR / "assets" / "all-cards-fallback.json"

WORKER_BASE = "https://sakekitty-prices.nwilliams23999.workers.dev"
LOOKUP_URL = f"{WORKER_BASE}/lookup"

# pc-graded.json columns: [loose, new(PSA8), graded(PSA9), box-only(PSA9.5/BGS9.5),
#                          manual(PSA10), bgs-10]
PC_GRADE_COL = {
    "PSA10": 4,
    "PSA9":  2,
    "PSA9.5": 3,
    "PSA8":  1,
    "BGS9.5": 3,
    "BGS10": 5,
    "CGCPRISTINE": 4,  # CGC Pristine ≈ PSA 10 column (PC doesn't track CGC separately)
    "CGC10":  4,
    "CGC9.5": 3,
    "CGC9":   2,
    "BGS8.5": 1,  # PC's PSA8/new column is the closest proxy for raw NM-MT 8.5
    "BGS9":   2,
    "PSA7":   0,  # No grading column — fall back to ungraded loose-price
    "PSA6":   0,
}


# ─── markup ────────────────────────────────────────────────────────────────
def markup(base: float) -> float:
    """Headroom schedule (2026-05-05 night) — user wants more breathing room
    above market than the morning's 1.10/1.07/1.05 schedule. Back to the
    original aggressive 1.15+3 / 1.10+10 / 1.08 — combined with multi-source
    max-of-sources, this lifts every card meaningfully above prior list."""
    if base < 200:
        return base * 1.15 + 3
    if base < 1000:
        return base * 1.10 + 10
    return base * 1.08


def snap_clean(price: float) -> int:
    if price <= 0:
        return 0
    base = int(round(price))
    candidates = [n for n in range(max(1, base - 6), base + 7) if n % 5 == 0]
    candidates.sort(key=lambda n: (abs(n - price), -n))
    return candidates[0]


# ─── helpers ──────────────────────────────────────────────────────────────
def normalize_grade(s: str) -> str:
    return "".join(c for c in (s or "").upper() if c.isalnum())


def normalize_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def name_tokens(s: str) -> set[str]:
    stops = {"the", "a", "an", "of", "and", "or", "in", "on", "with",
             "pokemon", "card"}
    toks = set(normalize_text(s).split())
    return {t for t in toks if len(t) > 1 and t not in stops}


# ─── 130point worker ───────────────────────────────────────────────────────
def query_130point(query: str, timeout: int = 30) -> float | None:
    """Returns the average price from 130point's sales for this query, or None."""
    try:
        url = f"{LOOKUP_URL}?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "sake-kitty-pricer/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        if not data.get("ok"):
            return None
        summary = data.get("summary") or {}
        avg = summary.get("avg")
        count = summary.get("count", 0)
        # Require a few sales for the avg to be meaningful
        if avg is None or count < 3:
            return None
        return float(avg)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None


# ─── PriceCharting via productId lookup ────────────────────────────────────
def build_fallback_index(entries: list) -> dict[tuple[str, str], int]:
    """Build (name_token_key, set_token_key) -> productId index for quick lookup.
    name_token_key is the alphabetized tuple of name tokens (excl. number)
    plus the number prefix; set_token_key is alphabetized set tokens."""
    idx: dict[tuple[str, str], int] = {}
    for entry in entries:
        if len(entry) < 3:
            continue
        name, set_, pid = entry[0], entry[1], entry[2]
        idx[(normalize_text(name), normalize_text(set_))] = pid
    return idx


def fuzzy_resolve_pid(
    cl_player: str, cl_set: str, cl_number: str, fallback: list
) -> int | None:
    """Resolve productId by token-overlap fuzzy match against fallback entries."""
    cl_player_toks = name_tokens(cl_player)
    cl_set_toks = name_tokens(cl_set)
    cl_num = (cl_number or "").strip()
    if not cl_player_toks or not cl_set_toks:
        return None

    best: tuple[int, int] | None = None  # (score, pid)
    for entry in fallback:
        if len(entry) < 3:
            continue
        fb_name, fb_set, pid = entry[0], entry[1], entry[2]
        fb_name_str = (fb_name or "").lower()
        # Number must match — fallback names are like "Pikachu #1"
        if cl_num and f"#{cl_num.lower()}" not in fb_name_str:
            continue
        fb_name_toks = name_tokens(fb_name)
        fb_set_toks = name_tokens(fb_set)
        # Score = name overlap + set overlap
        name_overlap = len(cl_player_toks & fb_name_toks)
        set_overlap = len(cl_set_toks & fb_set_toks)
        if name_overlap < 1 or set_overlap < 1:
            continue
        score = name_overlap * 10 + set_overlap
        if best is None or score > best[0]:
            best = (score, pid)
    return best[1] if best else None


def pc_graded_price(pid: int | None, grade: str, pc_data: dict) -> float | None:
    if pid is None:
        return None
    arr = pc_data.get(str(pid))
    if not arr:
        return None
    col = PC_GRADE_COL.get(normalize_grade(grade))
    if col is None or col >= len(arr):
        return None
    val = arr[col]
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ─── main ─────────────────────────────────────────────────────────────────
def main() -> None:
    if not CARD_LADDER_CSV.exists():
        print(f"[max] CL CSV not found at {CARD_LADDER_CSV}")
        return

    print("[max] loading PriceCharting + fallback indexes...")
    pc_data = json.loads(PC_GRADED_PATH.read_text(encoding="utf-8"))
    fallback = json.loads(ALL_CARDS_PATH.read_text(encoding="utf-8"))
    print(f"[max]   pc-graded.json: {len(pc_data):,} entries")
    print(f"[max]   all-cards-fallback.json: {len(fallback):,} entries")

    rows_in: list[dict] = list(csv.DictReader(
        CARD_LADDER_CSV.open("r", encoding="utf-8-sig", newline="")
    ))
    print(f"[max] {len(rows_in)} Card Ladder rows to price")

    out_rows = []
    for i, r in enumerate(rows_in, 1):
        try:
            cl_value = float((r.get("Current Value") or "0").replace(",", "").strip() or "0")
        except ValueError:
            cl_value = 0.0
        if cl_value <= 0:
            print(f"[max] skip row {i}: no CL value")
            continue

        player = (r.get("Player") or "").strip()
        year   = (r.get("Year") or "").strip()
        set_   = (r.get("Set") or "").strip()
        number = (r.get("Number") or "").strip()
        grade  = (r.get("Condition") or "").strip()

        # PriceCharting via productId lookup
        pid = fuzzy_resolve_pid(player, set_, number, fallback)
        pc_price = pc_graded_price(pid, grade, pc_data)

        # 130point via worker — query like "Year Player Number Grade"
        # Worker scrapes 130point.com so a tighter query helps
        query_parts = [year, player, f"#{number}" if number else "", grade]
        query = " ".join(p for p in query_parts if p).strip()
        tp_price = query_130point(query)

        # Pick the highest of the three sources
        sources: list[tuple[str, float]] = [("CL", cl_value)]
        if pc_price is not None:
            sources.append(("PC", pc_price))
        if tp_price is not None:
            sources.append(("130p", tp_price))
        winner_name, winner_val = max(sources, key=lambda x: x[1])

        marked = markup(winner_val)
        final = snap_clean(marked)

        out_rows.append({
            "sk_code":     (r.get("Notes") or "").strip(),
            "cert":        (r.get("Slab Serial #") or "").strip(),
            "card_name":   player,
            "card_full":   (r.get("Card") or "").strip(),
            "year":        year,
            "set":         set_,
            "variation":   (r.get("Variation") or "").strip(),
            "number":      number,
            "grade":       grade,
            "src_cl":      f"{cl_value:.2f}",
            "src_pc":      f"{pc_price:.2f}" if pc_price is not None else "",
            "src_130p":    f"{tp_price:.2f}" if tp_price is not None else "",
            "src_winner":  winner_name,
            "base_value":  f"{winner_val:.2f}",
            "marked_up":   f"{marked:.2f}",
            "final_price": str(final),
            "name_for_match": "|".join([
                normalize_text(player),
                year,
                normalize_text(set_),
                normalize_grade(grade),
            ]),
        })

        # Status line — strip Unicode for the Windows console (cp1252)
        pc_str = f"PC=${pc_price:.0f}" if pc_price is not None else "PC=--"
        tp_str = f"130p=${tp_price:.0f}" if tp_price is not None else "130p=--"
        safe_name = player[:30].encode("ascii", "replace").decode("ascii")
        print(
            f"[max] {i:>2}/{len(rows_in):>2} "
            f"CL=${cl_value:>6.0f}  {pc_str:<12} {tp_str:<14} "
            f"-> {winner_name:>4} ${winner_val:>6.0f}  ->  ${final:<5}  "
            f"{safe_name}"
        )
        # Be polite to the worker
        time.sleep(0.3)

    # Write output
    if out_rows:
        with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            writer.writeheader()
            for row in out_rows:
                writer.writerow(row)

    # Source winner breakdown
    winners: dict[str, int] = {}
    for r in out_rows:
        winners[r["src_winner"]] = winners.get(r["src_winner"], 0) + 1
    print()
    print("[max] === Summary ===")
    print(f"[max] {len(out_rows)} priced rows written to {OUT_PATH.name}")
    for w, n in sorted(winners.items(), key=lambda x: -x[1]):
        print(f"[max]   {w} won: {n} cards")

    # Tier breakdown of final base
    t1 = sum(1 for r in out_rows if float(r["base_value"]) < 200)
    t2 = sum(1 for r in out_rows if 200 <= float(r["base_value"]) < 1000)
    t3 = sum(1 for r in out_rows if float(r["base_value"]) >= 1000)
    print(f"[max]   tier 1 (<$200):    {t1:>4}")
    print(f"[max]   tier 2 ($200-999): {t2:>4}")
    print(f"[max]   tier 3 (>=$1000):  {t3:>4}")


if __name__ == "__main__":
    main()
