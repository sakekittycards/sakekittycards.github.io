"""Unified SITE pricing review/engine (graded pass) — Sake Kitty.

Methodology (user 2026-06-11, see memory feedback_site_pricing_methodology):
  sell = comp x 1.03  (market or up to 3% above — minimal, covers the <=3% fee;
                       nets market). comp = the last-5-sold / recent market avg.
  Live listings ONLY RAISE: if QUALITY sellers (ignore 0%-feedback; Nick is 100%)
  list the SAME validated card higher than the sold-based price, bump up toward it
  (capped). Never lower, never undercut, never chase the lowest list.
  Margin floor from cost. Sources: graded -> CardLadder last-5-sold,
  raw+sealed -> tcgsearch max(market, recent-sold avg).

THIS FILE = the GRADED pass (data already in hand from the CardLadder export):
  - comp        = CL "Current Value" (CardLadder market, reflects recent sales;
                  cardladder.py last-5-sold can refine per-card later)
  - cost        = CL "Investment" -> MARGIN FLOOR (never price below cost)
  - live raise  = eBay lowest QUALIFYING list (quality seller + validated same
                  card) can only RAISE; loaded from _ebay_lowlist.json if present.

Read-only review: prints current Square price vs suggested for every graded slab.
Does NOT write to Square. (The live push goes through the gated reconcile.)

Guardrails:
  FEE_MARKUP      - 1.03: list 3% over comp so the <=3% fee nets you market
  MIN_MARGIN_PCT  - suggested never below cost*(1+margin) when cost is known
  MAX_RAISE       - a live listing can raise at most this multiple over comp
                    (so a wrong/crazy listing can't 10x the price)
"""
from __future__ import annotations
import csv, json, math, os, re, subprocess, sys, urllib.request
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
DOWN = Path.home() / "Downloads"
WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
INSPECT = f"{WORKER}/admin/inspect?types=ITEM"

FEE_MARKUP     = 1.03   # list 3% over comp; the <=3% fee nets Nick ~market.
                        # (shipping charged separately / free >$100; tax on top — not baked in)
MIN_MARGIN_PCT = 0.10   # keep >=10% over cost (margin protection)
MAX_RAISE      = 1.50   # a live listing can raise at most 1.5x comp ("don't get crazy")


def tok() -> str | None:
    t = os.environ.get("SK_ADMIN_TOKEN")
    if t: return t.strip()
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
            "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"],
            capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip() or None
    except Exception: return None


def inspect_all(token: str) -> list[dict]:
    out, cursor = [], None
    while True:
        url = INSPECT + (f"&cursor={cursor}" if cursor else "")
        req = urllib.request.Request(url, headers={
            "X-Sake-Admin-Token": token, "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read())
        out.extend(d.get("objects", [])); cursor = d.get("cursor")
        if not cursor: break
    return out


def price_of(it: dict):
    for v in (it.get("item_data") or {}).get("variations", []):
        a = ((v.get("item_variation_data") or {}).get("price_money") or {}).get("amount")
        if a is not None: return a / 100
    return None


def cert_of(it: dict) -> str | None:
    desc = (it.get("item_data") or {}).get("description", "") or ""
    m = re.search(r"Cert #:\s*(\d+)", desc)
    return m.group(1) if m else None


def is_graded(it: dict) -> bool:
    data = it.get("item_data") or {}
    name = (data.get("name") or "").lower(); desc = (data.get("description") or "").lower()
    if "cert #" in desc: return True
    return any(k in name for k in (" psa ", " cgc ", " bgs ", " sgc ")) \
        or name.startswith(("psa ", "cgc ", "bgs ", "sgc "))


def newest_export() -> Path | None:
    fs = sorted(DOWN.glob("Collection - Card Ladder*.csv"),
                key=lambda p: p.stat().st_mtime, reverse=True)
    return fs[0] if fs else None


def load_held() -> set[str]:
    f = HERE / "_held_certs.txt"
    out = set()
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            ln = ln.split("#", 1)[0].strip()
            if ln: out.add(ln)
    return out


def load_ebay_lows() -> dict[str, float]:
    """Optional cert->eBay-lowest-list cache (built by a later eBay pass)."""
    f = HERE / "_ebay_lowlist.json"
    if f.exists():
        try: return {str(k): float(v) for k, v in json.loads(f.read_text()).items()}
        except Exception: return {}
    return {}


def suggest(market: float, cost: float, recent: float | None, live_quality_low: float | None):
    """sell = comp x1.03; live listings ONLY RAISE; margin floor. Returns (price, notes)."""
    notes = []
    comp = market
    if recent and recent > comp:
        comp = recent; notes.append(f"recent>{market:.0f}")
    px = comp * FEE_MARKUP   # market or 3% above (fee cover)
    # Live listing can only RAISE (quality seller + validated same card upstream).
    if live_quality_low and live_quality_low > px:
        target = min(live_quality_low, comp * MAX_RAISE)   # don't get crazy
        if target > px:
            notes.append(f"raised to live {live_quality_low:.0f}"
                         + (" (capped)" if target < live_quality_low else ""))
            px = target
    # margin floor — ONLY with REAL cost. $100/$0 in the export are placeholders
    # (would wrongly overprice cheap cards above market), and margins are huge
    # anyway, so skip those. Real cost essentially never binds; it's just a guard.
    if cost and cost not in (0, 100):
        floor = cost * (1 + MIN_MARGIN_PCT)
        if px < floor:
            px = floor; notes.append(f"margin floor (cost {cost:.0f})")
    return math.ceil(px), notes


def main() -> int:
    token = tok()
    if not token: print("SK_ADMIN_TOKEN not set"); return 1
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else newest_export()
    if not src or not src.exists(): print("no Sake export"); return 1

    held = load_held(); ebay = load_ebay_lows()
    # cert -> {name, market, cost} from export
    ex = {}
    for r in csv.DictReader(src.open("r", encoding="utf-8-sig")):
        cert = (r.get("Graded Cert #") or "").strip()
        if not cert: continue
        f = lambda k: float((r.get(k) or "0").replace(",", "") or 0)
        ex[cert] = {"name": (r.get("Card") or "").strip(), "market": f("Current Value"), "cost": f("Investment")}

    items = inspect_all(token)
    graded = [i for i in items if is_graded(i)]

    rows, up, down, same, no_market = [], 0, 0, 0, 0
    for it in graded:
        c = cert_of(it)
        if not c or c in held: continue
        cur = price_of(it)
        info = ex.get(c)
        if not info or info["market"] <= 0:
            no_market += 1; continue
        sug, notes = suggest(info["market"], info["cost"], None, ebay.get(c))
        delta = (sug - cur) if cur is not None else None
        rows.append((c, info["name"], cur, info["market"], info["cost"], sug, delta, notes))
        if delta is None: pass
        elif delta > 0.5: up += 1
        elif delta < -0.5: down += 1
        else: same += 1

    rows.sort(key=lambda r: abs(r[6] or 0), reverse=True)
    print(f"GRADED site-pricing review — {len(rows)} slabs "
          f"(comp=CL market; sell=comp x{FEE_MARKUP:.2f}; live-raise cached: {len(ebay)})")
    print(f"  vs current Square price:  RAISE {up}  /  LOWER {down}  /  ~same {same}  /  no-market {no_market}")
    print(f"  guardrails: >= cost x{1+MIN_MARGIN_PCT:.2f}; live listings only RAISE (cap {MAX_RAISE:.2f}x); "
          f"shipping/tax not baked in\n")
    print(f"  {'cert':<11} {'cur':>7} {'mkt':>7} {'cost':>6} {'NEW':>7} {'Δ':>7}  card / notes")
    for c, nm, cur, mkt, cost, sug, delta, notes in rows:
        cs = f"{cur:.0f}" if cur is not None else "—"
        ds = f"{delta:+.0f}" if delta is not None else "—"
        note = ("  · " + ", ".join(notes)) if notes else ""
        print(f"  {c:<11} {cs:>7} {mkt:>7.0f} {cost:>6.0f} {sug:>7} {ds:>7}  {nm[:46]}{note}")

    # write a review CSV for the user
    out = HERE / "_site_reprice_graded_review.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["cert", "card", "current", "market", "cost", "suggested", "delta", "notes"])
        for c, nm, cur, mkt, cost, sug, delta, notes in rows:
            w.writerow([c, nm, cur, mkt, cost, sug, delta, "; ".join(notes)])
    print(f"\n  review CSV -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
