"""Bake a static snapshot of the Square catalog into shop.html.

WHY THIS EXISTS
---------------
shop.html renders its entire catalog client-side: five empty <div> grids that
get filled from the Square worker after page load. That is fine for Googlebot,
which executes JavaScript — but GPTBot, ClaudeBot, PerplexityBot and most other
AI crawlers do NOT. They fetched 55KB of chrome and zero products, so asking an
answer engine "what does Sake Kitty have in stock" returned nothing.

This script writes a plain-HTML snapshot of the catalog into those grids, plus
an ItemList of Product schema, between marker comments.

HOW IT STAYS HONEST
-------------------
The snapshot is a FALLBACK, never the source of truth:

  * shop.html's own JS does `grid.innerHTML = live.map(renderCard)` on load, so
    for anyone with JavaScript the snapshot is replaced with live Square data
    within milliseconds of the fetch returning. Humans never transact on it.
  * The sections stay `hidden` for JS clients exactly as before; a <noscript>
    block reveals them for non-JS clients, who also get a plain-language note
    that the list is a snapshot with a link to the live storefront.
  * A build timestamp is written into the markup so staleness is visible.

STALENESS IS REAL, AND BOUNDED
------------------------------
GitHub Pages only rebuilds on push, so this snapshot is exactly as fresh as the
last deploy. That is acceptable because it only ever reaches clients that could
otherwise see NOTHING, and because prices/availability are deliberately kept
out of the human-visible fallback (see build_card). Re-run this before a deploy
if the catalog has moved:

    python scripts/build_shop_snapshot.py

Usage: python scripts/build_shop_snapshot.py [--offline]
  --offline  skip the network fetch and leave any existing snapshot in place
             (used so a failed/blocked fetch never silently empties the page)
"""
import argparse
import datetime as _dt
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# SKU -> static-page slug, written by scripts/build_product_pages.py. Absent or
# stale is fine: every lookup falls back to product.html?id=.
try:
    import json as _json, pathlib as _pl
    _SLUGS = _json.loads((_pl.Path(__file__).resolve().parent.parent /
                          "assets" / "product-slugs.json").read_text(encoding="utf-8"))
except Exception:
    _SLUGS = {}

ROOT = Path(__file__).resolve().parent.parent
SHOP = ROOT / "shop.html"
WORKER = "https://sakekitty-square.nwilliams23999.workers.dev/items"
SITE = "https://sakekittycards.com"

START = "<!-- SNAPSHOT:START -->"
END = "<!-- SNAPSHOT:END -->"
LD_START = "<!-- SNAPSHOT-LD:START -->"
LD_END = "<!-- SNAPSHOT-LD:END -->"

# Mirrors the classifiers in shop.html. If those change, change these — a
# snapshot that categorises differently from the live render is worse than none.
GRADER_RX = re.compile(r"^(PSA|BGS|CGC|SGC|HGA|AGS|TAG|GMA|ISA|CSG)\s", re.I)
SEALED_RX = re.compile(
    r"\b(booster|pack|etb|elite\s*trainer|tin|collection|bundle|deck|case|box)\b", re.I
)
YEAR_RX = re.compile(r"^(?:19|20)\d{2}\s")
JP_RX = re.compile(r"\b(japan|japanese|jp)\b", re.I)


def categorize(item):
    name = item.get("name") or ""
    desc = item.get("description") or ""
    if GRADER_RX.search(name):
        return "graded"
    if YEAR_RX.search(name):
        return "singles"
    if re.search(r"Card ID:", desc, re.I) and not SEALED_RX.search(name):
        return "singles"
    if SEALED_RX.search(name):
        return "sealed"
    return "merch"


def fetch_items():
    req = urllib.request.Request(WORKER, headers={"User-Agent": "sakekitty-snapshot/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("worker returned no items array")
    return items


def thumb(url):
    """Same wsrv.nl proxy shop.html uses for grid thumbnails.

    Without this the snapshot would point at full-size Square/Printful CDN
    images, which is both slow and visually broken in the no-JS view.
    """
    if not url:
        return ""
    return (
        "https://wsrv.nl/?url=" + urllib.parse.quote(url, safe="")
        + "&w=320&h=512&fit=contain&cbg=000000&output=webp&q=78"
    )


def build_card(item, cat):
    """One snapshot card, matching renderCard()'s markup in shop.html.

    The class names and nesting have to match or the CSS doesn't apply and the
    no-JS view renders as giant unstyled blocks.

    Name + image only — no price, no stock badge. Those move faster than the
    deploy cadence, and a stale price shown to a human is worse than no price.
    Live prices arrive with the JS render; schema carries price separately,
    where a timestamped snapshot is the normal convention.
    """
    e = html.escape
    name = e(item.get("name") or "Untitled")
    # Prefer the static per-SKU page so the no-JS snapshot and the live
    # renderer point at the same canonical URL. Falls back to the shell for a
    # SKU that postdates the last build_product_pages.py run.
    _slug = _SLUGS.get(item.get("id") or "")
    href = ("p/%s.html" % _slug) if _slug else (
        "product.html?id=" + urllib.parse.quote(item.get("id") or "", safe=""))
    raw = (item.get("imageUrl") or "") or ((item.get("imageUrls") or [None])[0] or "")
    src = thumb(raw)
    img = (
        f'<img src="{e(src, quote=True)}" alt="{name}" class="product-img-real"'
        f' loading="lazy" decoding="async" width="320" height="512" />'
        if src
        else '<div class="product-img">\U0001F4E6</div>'
    )
    classes = "product-card" + (f" {cat}" if cat in ("graded", "sealed", "singles") else "")
    return (
        f'<a href="{href}" class="{classes}" style="position:relative;color:inherit;text-decoration:none">'
        f"{img}"
        f'<div class="product-info"><div class="product-name">{name}</div></div>'
        f"</a>"
    )


def build_schema(buckets):
    elements = []
    pos = 0
    for it in [x for b in buckets.values() for x in b]:
        if it.get("inStock") is False:
            continue
        pos += 1
        _s = _SLUGS.get(it.get("id") or "")
        url = f"{SITE}/p/{_s}.html" if _s else f"{SITE}/product.html?id={it.get('id')}"
        offer = {
            "@type": "Offer",
            "url": url,
            "availability": "https://schema.org/InStock",
            "seller": {"@id": f"{SITE}/#organization"},
        }
        price = it.get("price")
        if isinstance(price, (int, float)) and price > 0:
            offer["price"] = f"{float(price):.2f}"
            offer["priceCurrency"] = it.get("currency") or "USD"
        product = {
            "@type": "Product",
            "name": it.get("name") or "Untitled",
            "sku": it.get("id"),
            "category": categorize(it),
            "url": url,
            "offers": offer,
        }
        img = (it.get("imageUrl") or "") or ((it.get("imageUrls") or [None])[0] or "")
        if img:
            product["image"] = img
        desc = (it.get("description") or "").strip()
        if desc:
            product["description"] = " ".join(desc.split())[:300]
        elements.append({"@type": "ListItem", "position": pos, "item": product})

    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": "Sake Kitty Cards — Shop",
            "numberOfItems": len(elements),
            "itemListElement": elements,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


GRID_IDS = {
    "graded": "shopGridGraded",
    "sealedEn": "shopGridSealedEn",
    "sealedJp": "shopGridSealedJp",
    "singles": "shopGridSingles",
    "merch": "shopGridMerch",
}


FLAG_RX = {
    "SK_INVENTORY_PAUSED": re.compile(r"const\s+SK_INVENTORY_PAUSED\s*=\s*(true|false)"),
    "SEALED_PAUSED": re.compile(r"const\s+SEALED_PAUSED\s*=\s*(true|false)"),
    "SINGLES_PAUSED": re.compile(r"const\s+SINGLES_PAUSED\s*=\s*(true|false)"),
    "GRADED_AT_SHOW": re.compile(r"const\s+GRADED_AT_SHOW\s*=\s*(true|false)"),
}


def read_flags(src):
    """Read the live pause flags straight out of shop.html.

    THIS IS NOT OPTIONAL. shop.html zeroes whole buckets when these are set —
    sealed and raw singles are currently paused because Nick pulled them off the
    site (2026-08-06), and CLAUDE.md records "no direct-sale singles on the site"
    as a locked business rule.

    A snapshot that ignored them would bake deliberately-withdrawn inventory into
    the raw HTML, where Google and every AI crawler would read it, while the live
    page showed nothing. Parsing the flags from source instead of duplicating them
    means they cannot drift apart.
    """
    flags = {}
    for name, rx in FLAG_RX.items():
        m = rx.search(src)
        if not m:
            raise SystemExit(
                f"could not find {name} in shop.html — refusing to build a snapshot "
                "that might publish paused inventory"
            )
        flags[name] = m.group(1) == "true"
    return flags


def apply_gates(buckets, flags):
    """Mirror shop.html's bucket-zeroing exactly."""
    dropped = {}
    if flags["GRADED_AT_SHOW"]:
        dropped["graded (at show)"] = len(buckets["graded"]); buckets["graded"] = []
    if flags["SK_INVENTORY_PAUSED"]:
        for k in ("graded", "sealedEn", "sealedJp", "singles"):
            if buckets[k]:
                dropped[f"{k} (inventory paused)"] = len(buckets[k]); buckets[k] = []
    if flags["SEALED_PAUSED"]:
        for k in ("sealedEn", "sealedJp"):
            if buckets[k]:
                dropped[f"{k} (sealed paused)"] = len(buckets[k]); buckets[k] = []
    if flags["SINGLES_PAUSED"]:
        if buckets["singles"]:
            dropped["singles (singles paused)"] = len(buckets["singles"]); buckets["singles"] = []
    return buckets, dropped


def build_snapshot(items, stamp, flags):
    buckets = {k: [] for k in GRID_IDS}
    for it in items:
        c = categorize(it)
        if c == "sealed":
            key = "sealedJp" if JP_RX.search(it.get("name") or "") else "sealedEn"
        else:
            key = c
        buckets[key].append(it)

    # Respect the live pause flags before anything is rendered.
    buckets, dropped = apply_gates(buckets, flags)
    for label, n in dropped.items():
        print(f"  gated out: {n} {label}")

    parts = [
        "",
        f"      <!-- Catalog snapshot generated {stamp} by scripts/build_shop_snapshot.py.",
        "           DO NOT HAND-EDIT: regenerated on every run. This exists only so",
        "           crawlers that don't execute JavaScript can see the catalog; page JS",
        "           overwrites every grid below with live Square data on load. -->",
        '      <noscript>',
        "        <style>",
        "          #shopStatus{display:none!important}",
        "          #shopSections{display:block!important}",
        "          #shopSections .shop-section[hidden],",
        "          #shopSections .shop-subsection[hidden]{display:block!important}",
        "        </style>",
        '        <p class="shop-snapshot-note">This is a saved snapshot of our catalog from '
        f"{stamp[:10]}. Turn on JavaScript for live stock and pricing, or browse our "
        '<a href="https://www.tcgplayer.com/sellers/Sake-Kitty-Cards/cb1bc211" rel="noopener">TCGplayer store</a>.</p>',
        "      </noscript>",
    ]
    parts.append("")
    return "\n".join(parts), buckets



def fill_grids(src, buckets):
    """Write the snapshot cards straight into the real grid divs.

    NOT a <template>: template content never renders, so non-JS humans would
    still see an empty shop. These go into the live grids, which shop.html's own
    JS overwrites via innerHTML the moment the Square fetch resolves — so this
    markup is only ever seen by something that didn't run the script.

    Card markup contains nested <div>s (product-info > product-name), so a
    non-greedy match up to the first </div> would stop INSIDE the first card on
    a re-run and duplicate the whole grid. (It did: 56 cards became 110.) The
    snapshot region is therefore fenced by explicit comment markers, which can't
    nest and make the rewrite idempotent.
    """
    filled = 0
    for key, gid in GRID_IDS.items():
        rows = buckets.get(key) or []
        cat = "sealed" if key.startswith("sealed") else key
        cards = "".join(build_card(i, cat) for i in rows)
        fence_open, fence_close = f"<!--SNAP:{gid}-->", f"<!--/SNAP:{gid}-->"
        payload = fence_open + cards + fence_close

        fenced = re.compile(re.escape(fence_open) + ".*?" + re.escape(fence_close), re.S)
        if fenced.search(src):
            # Re-run: replace only what's between our own fences.
            src = fenced.sub(lambda _m: payload, src, count=1)
        else:
            # First run: the grid is empty in the committed source.
            empty = f'<div class="product-grid" id="{gid}"></div>'
            if empty not in src:
                raise SystemExit(
                    f"grid #{gid} is neither empty nor fenced — refusing to guess. "
                    "Revert shop.html to a clean state and re-run."
                )
            src = src.replace(empty, f'<div class="product-grid" id="{gid}">{payload}</div>', 1)
        filled += 1
    return src, filled


FLAG_RX = {
    "SK_INVENTORY_PAUSED": re.compile(r"const\s+SK_INVENTORY_PAUSED\s*=\s*(true|false)"),
    "SEALED_PAUSED": re.compile(r"const\s+SEALED_PAUSED\s*=\s*(true|false)"),
    "SINGLES_PAUSED": re.compile(r"const\s+SINGLES_PAUSED\s*=\s*(true|false)"),
    "GRADED_AT_SHOW": re.compile(r"const\s+GRADED_AT_SHOW\s*=\s*(true|false)"),
}


def read_flags(src):
    """Read the live pause flags straight out of shop.html.

    THIS IS NOT OPTIONAL. shop.html zeroes whole buckets when these are set —
    sealed and raw singles are currently paused because Nick pulled them off the
    site (2026-08-06), and CLAUDE.md records "no direct-sale singles on the site"
    as a locked business rule.

    A snapshot that ignored them would bake deliberately-withdrawn inventory into
    the raw HTML, where Google and every AI crawler would read it, while the live
    page showed nothing. Parsing the flags from source instead of duplicating them
    means they cannot drift apart.
    """
    flags = {}
    for name, rx in FLAG_RX.items():
        m = rx.search(src)
        if not m:
            raise SystemExit(
                f"could not find {name} in shop.html — refusing to build a snapshot "
                "that might publish paused inventory"
            )
        flags[name] = m.group(1) == "true"
    return flags


def apply_gates(buckets, flags):
    """Mirror shop.html's bucket-zeroing exactly."""
    dropped = {}
    if flags["GRADED_AT_SHOW"]:
        dropped["graded (at show)"] = len(buckets["graded"]); buckets["graded"] = []
    if flags["SK_INVENTORY_PAUSED"]:
        for k in ("graded", "sealedEn", "sealedJp", "singles"):
            if buckets[k]:
                dropped[f"{k} (inventory paused)"] = len(buckets[k]); buckets[k] = []
    if flags["SEALED_PAUSED"]:
        for k in ("sealedEn", "sealedJp"):
            if buckets[k]:
                dropped[f"{k} (sealed paused)"] = len(buckets[k]); buckets[k] = []
    if flags["SINGLES_PAUSED"]:
        if buckets["singles"]:
            dropped["singles (singles paused)"] = len(buckets["singles"]); buckets["singles"] = []
    return buckets, dropped


def build_snapshot(items, stamp, flags):
    buckets = {k: [] for k in GRID_IDS}
    for it in items:
        c = categorize(it)
        if c == "sealed":
            key = "sealedJp" if JP_RX.search(it.get("name") or "") else "sealedEn"
        else:
            key = c
        buckets[key].append(it)

    # Respect the live pause flags before anything is rendered.
    buckets, dropped = apply_gates(buckets, flags)
    for label, n in dropped.items():
        print(f"  gated out: {n} {label}")

    parts = [
        "",
        f"      <!-- Catalog snapshot generated {stamp} by scripts/build_shop_snapshot.py.",
        "           DO NOT HAND-EDIT: regenerated on every run. This exists only so",
        "           crawlers that don't execute JavaScript can see the catalog; page JS",
        "           overwrites every grid below with live Square data on load. -->",
        '      <noscript>',
        "        <style>",
        "          #shopStatus{display:none!important}",
        "          #shopSections{display:block!important}",
        "          #shopSections .shop-section[hidden],",
        "          #shopSections .shop-subsection[hidden]{display:block!important}",
        "        </style>",
        '        <p class="shop-snapshot-note">This is a saved snapshot of our catalog from '
        f"{stamp[:10]}. Turn on JavaScript for live stock and pricing, or browse our "
        '<a href="https://www.tcgplayer.com/sellers/Sake-Kitty-Cards/cb1bc211" rel="noopener">TCGplayer store</a>.</p>',
        "      </noscript>",
    ]
    parts.append("")
    return "\n".join(parts), buckets


def replace_block(src, start, end, payload, label):
    if start not in src or end not in src:
        raise SystemExit(
            f"marker {label} missing from shop.html — add {start} / {end} first"
        )
    a = src.index(start) + len(start)
    b = src.index(end)
    return src[:a] + payload + src[b:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    src = SHOP.read_text(encoding="utf-8")

    if args.offline:
        print("--offline: leaving existing snapshot untouched")
        return

    try:
        items = fetch_items()
    except Exception as exc:  # noqa: BLE001
        # Fail loud, change nothing. An empty snapshot silently shipped is the
        # exact failure mode this script exists to prevent.
        print(f"ERROR: could not fetch catalog ({exc}). shop.html left unchanged.", file=sys.stderr)
        raise SystemExit(1)

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    live = [i for i in items if i.get("inStock") is not False]

    flags = read_flags(src)
    block, buckets = build_snapshot(live, stamp, flags)
    src = replace_block(src, START, END, chr(10) + block + "      ", "SNAPSHOT")
    src, filled = fill_grids(src, buckets)
    src = replace_block(
        src, LD_START, LD_END,
        '\n  <script type="application/ld+json">\n' + build_schema(buckets) + "\n  </script>\n  ",
        "SNAPSHOT-LD",
    )
    SHOP.write_text(src, encoding="utf-8")

    counts = {}
    for i in live:
        counts[categorize(i)] = counts.get(categorize(i), 0) + 1
    shipped = sum(len(v) for v in buckets.values())
    print(f"shop.html snapshot written: {shipped} items into {filled} grids ({stamp})")
    for k, v in buckets.items():
        if v:
            print(f"  {k:<9} {len(v)}")
    if shipped != len(live):
        print(f"  ({len(live) - shipped} of {len(live)} in-stock items withheld by pause flags)")


if __name__ == "__main__":
    main()
