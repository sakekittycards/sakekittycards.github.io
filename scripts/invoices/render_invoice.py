#!/usr/bin/env python
"""Sake Kitty Cards — invoice renderer.

Data (data/*.json) + layout (templates/invoice.html.j2) + styling
(templates/invoice.css) -> a print-ready Letter PDF.

Built on the same document system as sk-wholesale-terms.html, so retail
invoices and the wholesale term sheet read as one house style.

Every money figure in the PDF is computed here from the line items; nothing
is transcribed. Each data file carries an `expect` block and the renderer
REFUSES to emit a PDF when the computed figures disagree with it -- so a
hand-edited card list can never silently change a quoted total.

Usage
-----
    python render_invoice.py data/joe-carter.json
    python render_invoice.py --all
    python render_invoice.py data/zach-kessler.json --html   # keep the HTML too
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE_ROOT = HERE.parent.parent
TEMPLATES = HERE / "templates"
DATA_DIR = HERE / "data"
OUT_DIR = HERE / "out"

# The ORIGINAL Sake Kitty Cards logo (not the Wholesale mark). Single source of
# truth -- read from the repo root, never copied or altered.
LOGO_SRC = SITE_ROOT / "logo-transparent.png"
LOGO_RENDER_PX = 600  # plenty for an 84px mark at 300dpi; keeps the PDF small

CENTS = Decimal("0.01")


# ---------------------------------------------------------------- money ----
def D(x) -> Decimal:
    """Exact 2dp decimal from any JSON number/string."""
    return Decimal(str(x)).quantize(CENTS, rounding=ROUND_HALF_UP)


def money(x) -> str:
    return "${:,.2f}".format(D(x))


class VerificationError(RuntimeError):
    """Computed figures disagree with the data file's `expect` block."""


# ------------------------------------------------------------- assembly ----
def build_context(data: dict) -> dict:
    """Compute every figure from the line items and assemble template context."""
    errors: list[str] = []

    # --- services ---------------------------------------------------------
    svc_rows = []
    service_fees = Decimal("0.00")
    for r in data.get("services", {}).get("rows", []):
        qty = r.get("qty")
        unit = D(r.get("unit_price", 0))
        amount = (unit * Decimal(str(qty))).quantize(CENTS, rounding=ROUND_HALF_UP)
        service_fees += amount
        svc_rows.append(
            {
                **r,
                "qty_display": "" if qty in (None, "") else str(qty),
                "unit_display": r.get("unit_label") or ("—" if r.get("complimentary") else money(unit)),
                "amount_display": money(amount),
                "amount": amount,
            }
        )

    # --- grading cards ----------------------------------------------------
    cards = []
    psa_fees = Decimal("0.00")
    seen: dict[tuple, int] = {}
    for i, c in enumerate(data.get("grading", {}).get("cards", []), start=1):
        fee = D(c.get("fee", 0))
        psa_fees += fee
        key = (
            str(c.get("name", "")).strip().lower(),
            str(c.get("number", "")).strip().lower(),
            str(c.get("set", "")).strip().lower(),
        )
        if key in seen:
            errors.append(
                f"duplicate card: {c.get('name')} {c.get('number')} ({c.get('set')}) "
                f"appears at rows {seen[key]} and {i}"
            )
        seen[key] = i
        cards.append({**c, "fee": fee, "fee_display": money(fee)})

    # --- shipping + grand total ------------------------------------------
    ship = data.get("shipping", {}) or {}
    ship_amount = None if ship.get("amount") is None else D(ship["amount"])
    grand = service_fees + psa_fees + (ship_amount or Decimal("0.00"))

    # --- verify against the data file's stated expectations ----------------
    exp = data.get("expect", {}) or {}

    def check(label, computed, expected):
        if expected is None:
            return
        if D(computed) != D(expected):
            errors.append(f"{label}: computed {money(computed)} != expected {money(expected)}")

    check("service fees", service_fees, exp.get("service_fees"))
    check("PSA fees", psa_fees, exp.get("psa_fees"))
    check("grand total", grand, exp.get("total"))

    if exp.get("submitted_cards") is not None and len(cards) != exp["submitted_cards"]:
        errors.append(f"card count: listed {len(cards)} != expected {exp['submitted_cards']}")

    # internal consistency: a per-card service row's qty must match the card count
    for r in data.get("services", {}).get("rows", []):
        if r.get("ties_to") == "cards" and r.get("qty") != len(cards):
            errors.append(
                f"service row {r.get('description')!r} qty {r.get('qty')} "
                f"!= {len(cards)} cards listed"
            )
        if r.get("ties_to") == "evaluated" and exp.get("evaluated_cards") is not None \
                and r.get("qty") != exp["evaluated_cards"]:
            errors.append(
                f"service row {r.get('description')!r} qty {r.get('qty')} "
                f"!= {exp['evaluated_cards']} cards evaluated"
            )

    if errors:
        raise VerificationError("\n  - ".join(["financial verification FAILED:"] + errors))

    # --- summary lines ----------------------------------------------------
    lines = []
    for l in data.get("summary", {}).get("lines", []):
        src = l.get("source")
        if src == "service_fees":
            val, tbd = money(service_fees), False
        elif src == "psa_fees":
            val, tbd = money(psa_fees), False
        elif src == "shipping":
            val = money(ship_amount) if ship_amount is not None else (ship.get("tbd_text") or "TBD")
            tbd = ship_amount is None
        else:
            val, tbd = l.get("value", ""), bool(l.get("tbd"))
        lines.append({**l, "value": val, "tbd": tbd})

    ctx = dict(data)
    ctx["services"] = {**data.get("services", {}), "rows": svc_rows}
    ctx["grading"] = {**data.get("grading", {}), "cards": cards}
    ctx["summary"] = {**data.get("summary", {}), "lines": lines}
    ctx["totals"] = {
        "service_fees": service_fees,
        "psa_fees": psa_fees,
        "shipping": ship_amount,
        "grand": grand,
        "service_fees_display": money(service_fees),
        "psa_fees_display": money(psa_fees),
        "grand_display": money(grand),
    }
    return ctx


# ------------------------------------------------------------- rendering ---
def logo_b64() -> str:
    """Original logo, downscaled and flattened to RGBA. Never alters the source."""
    from PIL import Image

    im = Image.open(LOGO_SRC).convert("RGBA")
    if im.width > LOGO_RENDER_PX:
        im = im.resize((LOGO_RENDER_PX, LOGO_RENDER_PX), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def render_html(ctx: dict) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("invoice.html.j2")
    return tpl.render(
        **ctx,
        css=(TEMPLATES / "invoice.css").read_text(encoding="utf-8"),
        logo=logo_b64(),
    )


def html_to_pdf(html: str, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.wait_for_function("document.fonts.ready.then(() => true)")
        page.emulate_media(media="print")

        # Hard gate: .sheet clips its overflow, so a page that is one row too
        # long would silently lose content. Refuse to produce such a PDF.
        # Measured off the LAST child's bottom edge against the sheet's content
        # box, so collapsing margins and margin-top:auto are all accounted for.
        over = page.evaluate(
            """() => [...document.querySelectorAll('.sheet')].map((s, i) => {
                 const cs = getComputedStyle(s);
                 const box = s.getBoundingClientRect();
                 const limit = box.bottom - parseFloat(cs.paddingBottom);
                 const last = s.lastElementChild.getBoundingClientRect().bottom;
                 return { page: i + 1, over: Math.round(last - limit) };
               }).filter(x => x.over > 0)"""
        )
        if over:
            browser.close()
            raise VerificationError(
                "page overflow — content would be clipped:\n  - "
                + "\n  - ".join(f"page {o['page']} overflows by {o['over']}px" for o in over)
            )

        page.pdf(
            path=str(pdf_path),
            width="8.5in",
            height="11in",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            prefer_css_page_size=True,
        )
        browser.close()


# ---------------------------------------------------------- post-checks ----
def verify_pdf(pdf_path: Path, ctx: dict) -> list[str]:
    """Read the rendered PDF back and confirm what has to be on the page."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
    flat = " ".join(text.split())
    problems = []

    expected_pages = len(ctx["layout"]["pages"])
    if len(reader.pages) != expected_pages:
        problems.append(f"page count: PDF has {len(reader.pages)}, layout declares {expected_pages}")

    # Name alone is ambiguous ("Charizard" is inside "Blaine's Charizard"), so
    # identify each row by name + card number, which the template renders adjacent.
    for c in ctx["grading"]["cards"]:
        needle = " ".join(x for x in (c.get("name"), c.get("number")) if x)
        n = flat.count(needle)
        if n != 1:
            problems.append(f"card {needle!r} appears {n}x in the PDF text (want 1)")

    for label, s in (
        ("service fees", ctx["totals"]["service_fees_display"]),
        ("PSA subtotal", ctx["totals"]["psa_fees_display"]),
        ("grand total", ctx["totals"]["grand_display"]),
    ):
        if s not in flat:
            problems.append(f"{label} {s} not found in the PDF text")

    return problems


# -------------------------------------------------------------- driver -----
def render_one(data_path: Path, out_dir: Path, keep_html: bool) -> Path:
    data = json.loads(data_path.read_text(encoding="utf-8"))
    ctx = build_context(data)

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / data["output_filename"]
    html = render_html(ctx)
    if keep_html:
        (out_dir / (pdf_path.stem + ".html")).write_text(html, encoding="utf-8")
    html_to_pdf(html, pdf_path)

    t = ctx["totals"]
    print(f"\n{data_path.name}  ->  {pdf_path}")
    print(f"  service fees      {t['service_fees_display']}")
    print(f"  PSA fees          {t['psa_fees_display']}")
    print(f"  shipping          {money(t['shipping']) if t['shipping'] is not None else 'TBD'}")
    print(f"  ESTIMATED TOTAL   {t['grand_display']}")
    print(f"  cards listed      {len(ctx['grading']['cards'])}")

    problems = verify_pdf(pdf_path, ctx)
    if problems:
        print("  PDF CHECK FAILED:")
        for p in problems:
            print(f"    - {p}")
        raise VerificationError(f"{pdf_path.name}: {len(problems)} post-render problem(s)")
    print("  checks            math verified · no duplicate cards · PDF text verified")
    return pdf_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a Sake Kitty Cards invoice PDF.")
    ap.add_argument("data", nargs="*", help="invoice data JSON file(s)")
    ap.add_argument("--all", action="store_true", help="render every data/*.json (skips _*.json)")
    ap.add_argument("--out", default=str(OUT_DIR), help="output directory")
    ap.add_argument("--html", action="store_true", help="also write the intermediate HTML")
    args = ap.parse_args()

    paths = [Path(p) for p in args.data]
    if args.all:
        paths = sorted(p for p in DATA_DIR.glob("*.json") if not p.name.startswith("_"))
    if not paths:
        ap.error("give a data file, or --all")

    failures = 0
    for p in paths:
        try:
            render_one(p, Path(args.out), args.html)
        except VerificationError as e:
            failures += 1
            print(f"\n!! {p.name}: {e}", file=sys.stderr)
    print()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
