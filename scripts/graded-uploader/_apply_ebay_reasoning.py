"""Reason over eBay sold-listings data per card and produce a final list price.

Reads:
  - _ebay_data_dump.json  (per-cert eBay sold items from caffein.dev/ebay-sold-listings)
  - _card_ladder_prices.csv  (the formula-derived prices)

For each card with eBay data, runs a structured analysis:
  1. Filter items: title must contain the correct grade (PSA 10, PSA 9, BGS 8.5, etc).
     Drops ungraded comps and wrong-grade comps.
  2. Drop outliers: keep prices in [0.5×median, 2×median].
  3. Trend detection: split items into "recent" (≤30 days) vs "older". If recent
     median is >10% above older median, mark trending UP. If >10% below, trending
     DOWN. Else STABLE.
  4. Recommend list price:
     - Trending UP:    target = max recent total × 1.10  (capture momentum)
     - STABLE:         target = recent median × 1.15     (15% above market)
     - Trending DOWN:  target = recent median × 1.10     (10% above; conservative)
  5. Snap to nearest $5.
  6. Final price = max(formula_price, recommendation). Never go below formula.

Outputs:
  - _card_ladder_prices.csv overwritten with new final_price values
  - _ebay_reasoning_report.txt for review
"""
from __future__ import annotations

import csv
import json
import re
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
DUMP = HERE / "_ebay_data_dump.json"
PRICES_CSV = HERE / "_card_ladder_prices.csv"
REPORT = HERE / "_ebay_reasoning_report.txt"

NOW = datetime.now(timezone.utc)
RECENT_WINDOW_DAYS = 30


def normalize_grade(s: str) -> str:
    return "".join(c for c in (s or "").upper() if c.isalnum())


def grade_matches_title(title: str, grade: str) -> bool:
    """Loose grade match — accept the equivalent labels eBay listers use."""
    t = title.upper().replace(".", "").replace("-", " ")
    t_compact = t.replace(" ", "")
    g_norm = normalize_grade(grade)

    if g_norm in t_compact:
        return True

    # Equivalents
    if g_norm == "PSA10" and ("GEM MT 10" in t or "GEM MINT 10" in t or
                               "GEMMINT 10" in t or "GEMMT10" in t_compact):
        return True
    if g_norm == "CGC10" or g_norm == "CGC10PRISTINE":
        if "CGC PRISTINE 10" in t or "CGCPRISTINE10" in t_compact \
                or "CGC GEM MINT 10" in t or "CGC 10" in t:
            return True
    if g_norm == "BGS85" and ("BGS 85" in t.replace(".", "") or "BGS85" in t_compact):
        return True
    return False


def title_matches_card(title: str, card_name: str, card_set: str,
                        card_number: str, year: str) -> bool:
    """Verify the eBay listing is the SAME card we're pricing.

    Checks:
      1. Card number (most discriminating) — must appear in title
      2. At least one significant player-name token must appear in title
      3. Either the year OR a set-name token must appear in title
    Stop-words and very common terms are filtered out.
    """
    t = title.upper().replace(".", " ").replace("-", " ")
    t_compact = t.replace(" ", "")

    # 1. Card number must be in the title (most discriminating signal).
    #    Numbers can appear as "#11", "11/108", "No. 11", or just "11" near other tokens.
    num = (card_number or "").strip().upper().lstrip("0")
    if num:
        # Try exact match in compact title
        if num not in t_compact:
            # Also try with leading zeros (e.g., "085" vs "85")
            if card_number.upper() not in t_compact:
                return False

    # 2. Player-name token check — at least one significant token in title
    stop = {"FA", "HOLO", "FOIL", "EX", "GX", "V", "VMAX", "VSTAR", "AR",
            "SAR", "SIR", "IR", "UR", "PROMO", "FULL", "ART", "REVERSE",
            "REV", "RAINBOW", "GOLD", "SECRET", "SHINY"}
    name_toks = {tok for tok in re.split(r"[^A-Z0-9]+", card_name.upper())
                  if len(tok) >= 3 and tok not in stop}
    if name_toks and not any(tok in t for tok in name_toks):
        return False

    # 3. Year OR set keyword
    if year and year in t:
        return True
    set_stop = {"POKEMON", "ENGLISH", "JAPANESE", "EN", "JP", "PSA",
                "CGC", "BGS", "SGC", "CARD", "CARDS", "COLLECTION"}
    set_toks = {tok for tok in re.split(r"[^A-Z0-9]+", card_set.upper())
                 if len(tok) >= 4 and tok not in set_stop}
    if not set_toks:
        return True  # too few set tokens to gate on
    return any(tok in t for tok in set_toks)


def parse_price(it: dict) -> float | None:
    for key in ("totalPrice", "soldPrice"):
        v = it.get(key)
        if v is None:
            continue
        try:
            f = float(v)
            if f > 0:
                return f
        except (TypeError, ValueError):
            pass
    return None


def parse_date(it: dict) -> datetime | None:
    s = it.get("endedAt")
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def snap5(price: float) -> int:
    if price <= 0:
        return 0
    base = int(round(price))
    candidates = [n for n in range(max(1, base - 6), base + 7) if n % 5 == 0]
    candidates.sort(key=lambda n: (abs(n - price), -n))
    return candidates[0]


def analyze_card(items: list[dict], grade: str, formula_price: int,
                 cl_value: float | None = None,
                 card_name: str = "", card_set: str = "",
                 card_number: str = "", year: str = "") -> dict:
    """Returns analysis dict with reasoning for one card."""
    # Filter by grade AND card identity in title
    grade_items = []
    rejected_grade = 0
    rejected_identity = 0
    for it in items:
        title = it.get("title", "")
        if not grade_matches_title(title, grade):
            rejected_grade += 1
            continue
        if not title_matches_card(title, card_name, card_set, card_number, year):
            rejected_identity += 1
            continue
        p = parse_price(it)
        if p is None:
            continue
        d = parse_date(it)
        grade_items.append({"price": p, "date": d, "title": title})

    if not grade_items:
        return {
            "n_items_total": len(items),
            "n_items_graded": 0,
            "rejected_grade": rejected_grade,
            "rejected_identity": rejected_identity,
            "trend": "no-data",
            "recommendation": None,
            "rationale": (f"no items matching grade '{grade}' AND card identity in "
                          f"{len(items)} comps "
                          f"(rejected: {rejected_grade} on grade, {rejected_identity} on identity)"),
        }

    # Drop outliers
    raw_prices = [g["price"] for g in grade_items]
    med = statistics.median(raw_prices)
    kept = [g for g in grade_items if 0.5 * med <= g["price"] <= 2.0 * med]
    n_outliers = len(grade_items) - len(kept)

    if not kept:
        kept = grade_items  # safety: shouldn't happen if median is sane

    # Trend
    cutoff = NOW - timedelta(days=RECENT_WINDOW_DAYS)
    recent = [g for g in kept if g["date"] and g["date"] >= cutoff]
    older = [g for g in kept if g["date"] and g["date"] < cutoff]

    if not recent:
        # Fall back to all data if nothing in recent window
        recent = kept
        older = []

    recent_prices = [g["price"] for g in recent]
    recent_med = statistics.median(recent_prices)
    recent_max = max(recent_prices)

    if older:
        older_med = statistics.median([g["price"] for g in older])
        if recent_med > older_med * 1.10:
            trend = "up"
        elif recent_med < older_med * 0.90:
            trend = "down"
        else:
            trend = "stable"
    else:
        older_med = None
        trend = "stable-norecent"

    # Recommendation
    if trend == "up":
        target = recent_max * 1.10
        rationale = f"trending up (recent={recent_med:.0f} vs older={older_med:.0f}); target=max recent × 1.10"
    elif trend == "down":
        target = recent_med * 1.10
        rationale = f"trending down (recent={recent_med:.0f} vs older={older_med:.0f}); target=median × 1.10"
    else:  # stable / stable-norecent
        target = recent_med * 1.15
        rationale = f"stable (recent_med={recent_med:.0f}); target=median × 1.15"

    recommendation = snap5(target)

    # SANITY GUARD: if recommendation is >2x Card Ladder value, the eBay search
    # almost certainly matched a different card variant (e.g., Umbreon Gold
    # Star POP 5 matching Celebrations reprint, or 1st Edition matching
    # Unlimited). Reject the eBay recommendation in that case.
    rejected_as_outlier = False
    if cl_value and cl_value > 0 and recommendation > cl_value * 2.0:
        rejected_as_outlier = True
        rationale = (f"REJECTED: ebay rec ${recommendation} > 2x CL ${cl_value:.0f} "
                     f"-- likely matched wrong card variant. Original: {rationale}")
        recommendation = None

    return {
        "n_items_total": len(items),
        "n_items_graded": len(grade_items),
        "n_outliers": n_outliers,
        "n_recent": len(recent),
        "n_older": len(older),
        "recent_median": round(recent_med, 2),
        "recent_max": round(recent_max, 2),
        "older_median": round(older_med, 2) if older_med else None,
        "trend": trend,
        "rationale": rationale,
        "recommendation": recommendation,
        "rejected_as_outlier": rejected_as_outlier,
    }


def main() -> None:
    if not DUMP.exists():
        print(f"[reason] {DUMP.name} not found — run _run_ebay_fetch.py first")
        return

    dump = json.loads(DUMP.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(PRICES_CSV.open("r", encoding="utf-8")))
    fieldnames = list(rows[0].keys()) if rows else []

    # Add columns for eBay analysis if not present
    new_cols = ["ebay_n_graded", "ebay_recent_median", "ebay_trend",
                "ebay_recommendation", "src_winner_v2", "final_price_v2"]
    for c in new_cols:
        if c not in fieldnames:
            fieldnames.append(c)

    report_lines = []
    report_lines.append("=" * 110)
    report_lines.append(f"eBay reasoning report — {NOW.isoformat()}")
    report_lines.append("=" * 110)
    report_lines.append("")

    bumps = 0
    held = 0
    no_data = 0

    for row in rows:
        cert = (row.get("cert") or "").strip()
        formula_price = int(row.get("final_price") or "0")
        grade = (row.get("grade") or "").strip()
        name = (row.get("card_name") or "").strip()
        year = (row.get("year") or "").strip()

        entry = dump.get(cert, {})
        items = entry.get("items", [])

        try:
            cl_value = float((row.get("src_cl") or "0").replace(",", "").strip() or "0")
        except ValueError:
            cl_value = 0.0
        card_set = (row.get("set") or "").strip()
        card_number = (row.get("number") or "").strip()
        analysis = analyze_card(
            items, grade, formula_price, cl_value=cl_value,
            card_name=name, card_set=card_set, card_number=card_number, year=year,
        ) if items else {
            "n_items_total": 0, "n_items_graded": 0, "trend": "no-ebay-data",
            "recommendation": None,
            "rationale": "no eBay results returned for this query"
        }

        rec = analysis.get("recommendation")
        if rec is None:
            final = formula_price
            winner = "formula"
            no_data += 1
        elif rec > formula_price:
            final = rec
            winner = "ebay"
            bumps += 1
        else:
            final = formula_price
            winner = "formula"
            held += 1

        # Update row
        row["ebay_n_graded"] = str(analysis.get("n_items_graded", 0))
        row["ebay_recent_median"] = str(analysis.get("recent_median", "") or "")
        row["ebay_trend"] = analysis.get("trend", "")
        row["ebay_recommendation"] = str(rec) if rec else ""
        row["src_winner_v2"] = winner
        row["final_price_v2"] = str(final)

        # Report
        rec_str = f"${rec}" if rec else "--"
        report_lines.append(
            f"cert {cert:>12}  {grade:<14}  {year} {name[:30]:30}  "
            f"formula=${formula_price:>5}  ebay={rec_str:>6}  trend={analysis.get('trend','?'):14}  "
            f"-> ${final:<5} ({winner})"
        )
        if items and analysis.get("n_items_graded", 0) == 0:
            report_lines.append(
                f"    ! {len(items)} items returned but none matched grade '{grade}' "
                f"({analysis.get('rejected_grade',0)} rejected)"
            )
        elif analysis.get("n_items_graded", 0) > 0:
            recent_med = analysis.get("recent_median", "?")
            recent_n = analysis.get("n_recent", 0)
            older_n = analysis.get("n_older", 0)
            report_lines.append(
                f"    n_graded={analysis['n_items_graded']} "
                f"(outliers={analysis.get('n_outliers',0)}, recent={recent_n}, older={older_n}) "
                f"recent_med=${recent_med}  | {analysis.get('rationale','')}"
            )

    report_lines.append("")
    report_lines.append("=" * 110)
    report_lines.append(f"SUMMARY: {bumps} cards bumped above formula, "
                        f"{held} held at formula, {no_data} had no eBay data")
    report_lines.append("=" * 110)

    REPORT.write_text("\n".join(report_lines), encoding="utf-8")

    # Rewrite pricing CSV so the next match step picks up final_price_v2 — we
    # also overwrite the canonical "final_price" column so the existing match
    # script (which reads "final_price") gets the new value with no changes.
    for row in rows:
        v2 = row.get("final_price_v2")
        if v2:
            row["final_price"] = v2

    with PRICES_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[reason] {bumps} bumped, {held} held, {no_data} no-data")
    print(f"[reason] report -> {REPORT.name}")
    print(f"[reason] _card_ladder_prices.csv updated with eBay-reasoned final_price")


if __name__ == "__main__":
    main()
