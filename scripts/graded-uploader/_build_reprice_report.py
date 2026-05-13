"""Build a before/after/CL CSV from the most recent reprice run."""
from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
BEFORE = HERE / "pricing.csv.bak.20260511-222115"  # snapshot pre-reprice
AFTER = HERE / "pricing.csv"
CL_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder (10).csv")
OUT = HERE / "_reprice_report_20260512.csv"


def parse_price(raw: str) -> float | None:
    if not raw: return None
    s = raw.strip()
    if s.startswith("[uploaded]"): s = s[len("[uploaded]"):]
    s = s.lstrip("$").replace(",", "").strip()
    try: return float(s) if s else None
    except ValueError: return None


def load_pricing(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists(): return out
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            cert = (row.get("cert") or "").strip()
            if cert: out[cert] = row
    return out


def main() -> None:
    before = load_pricing(BEFORE)
    after = load_pricing(AFTER)

    cl: dict[str, tuple[float, float, str, str]] = {}
    with CL_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cert = (row.get("Graded Cert #") or "").strip()
            if not cert: continue
            try: cv = float((row.get("Current Value") or "0").replace(",", "").strip() or "0")
            except ValueError: cv = 0.0
            try: inv = float((row.get("Investment") or "0").replace(",", "").strip() or "0")
            except ValueError: inv = 0.0
            cl[cert] = (cv, inv,
                        (row.get("Card") or "").strip(),
                        (row.get("Condition") or "").strip())

    rows_out = []
    for cert, after_row in after.items():
        cv, inv, cl_name, cl_grade = cl.get(cert, (0.0, 0.0, "", ""))
        before_price = parse_price(before.get(cert, {}).get("your_price", "")) if cert in before else None
        after_price = parse_price(after_row.get("your_price", ""))
        delta = (after_price - before_price) if (before_price is not None and after_price is not None) else None
        delta_pct = (delta / before_price * 100) if (delta is not None and before_price) else None
        is_new = cert not in before
        rows_out.append({
            "cert": cert,
            "card": cl_name or f"{after_row.get('year','')} {after_row.get('set','')} {after_row.get('name','')} #{after_row.get('number','')}".strip(),
            "grade": cl_grade or after_row.get("grade", ""),
            "cl_current_value": f"{cv:.2f}" if cv else "",
            "cl_investment": f"{inv:.2f}" if inv else "",
            "price_before": f"{before_price:.0f}" if before_price is not None else ("NEW" if is_new else ""),
            "price_after":  f"{after_price:.0f}"  if after_price  is not None else "",
            "delta_dollars": f"{delta:+.0f}" if delta is not None else ("" if not is_new else ""),
            "delta_pct":     f"{delta_pct:+.1f}%" if delta_pct is not None else "",
            "is_new":        "yes" if is_new else "",
        })

    # Sort: new cards first, then by abs(delta) descending
    def sort_key(r):
        if r["is_new"] == "yes": return (0, 0)
        try: d = abs(float(r["delta_dollars"].replace("+","").replace(",","") or 0))
        except ValueError: d = 0
        return (1, -d)
    rows_out.sort(key=sort_key)

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    print(f"Wrote {len(rows_out)} rows -> {OUT}")


if __name__ == "__main__":
    main()
