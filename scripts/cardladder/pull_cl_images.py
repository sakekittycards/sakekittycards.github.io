"""
Pull card images from Card Ladder for the user's graded collection.

How it works:
  1. Launches Chromium with a persistent profile in `_profile/` so login
     survives between runs.
  2. First run: user logs into Card Ladder manually (script waits up to
     5 minutes). Subsequent runs reuse the saved session.
  3. Navigates to each cardId URL in turn, finds the main card image, and
     saves it as `images/<cert>.png` (front art) — uses the cert number
     from the SK pricing.csv to match cards to certs.

Usage:
  python scripts/cardladder/pull_cl_images.py                       # launch own browser, log in once
  python scripts/cardladder/pull_cl_images.py --attach 9222         # attach to already-running Edge/Chrome via CDP
  python scripts/cardladder/pull_cl_images.py --urls urls.txt       # explicit list of cardId URLs
  python scripts/cardladder/pull_cl_images.py --probe <URL>         # open one URL for selector discovery

To attach to your existing Edge session (keeps your CL login):
  1. Close all Edge windows.
  2. Launch Edge with the debug port:
       "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" --remote-debugging-port=9222
  3. Verify CL is still logged in (cookies persist in your default profile).
  4. Run this script with `--attach 9222`.

The collection page DOM isn't documented; the scraper uses a few resilient
heuristics. If they break, run with `--probe` and the script will print
the page structure to help update selectors.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / "_profile"
IMAGES_DIR = HERE / "images"
MAPPING_FILE = HERE / "cardId_to_cert.json"
PRICING_CSV = HERE.parent / "graded-uploader" / "pricing.csv"

LOGIN_URL = "https://app.cardladder.com/login"
COLLECTION_URL = "https://app.cardladder.com/collection"
CARD_DETAIL_TPL = "https://app.cardladder.com/collection?cardId={card_id}&profile=collection"


def load_owned_certs() -> set[str]:
    out: set[str] = set()
    if not PRICING_CSV.exists(): return out
    with PRICING_CSV.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            c = (row.get("cert") or "").strip()
            if c: out.add(c)
    return out


def wait_for_login(page) -> bool:
    """Open Card Ladder, wait until the URL leaves /login (=> user authed)."""
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    print("[cl] If a login screen is shown, complete the login in the browser.")
    print("[cl] Waiting up to 5 minutes for the URL to leave /login ...")
    try:
        page.wait_for_function(
            "() => !location.pathname.includes('/login')",
            timeout=5 * 60 * 1000,
        )
        print("[cl] Login detected.")
        return True
    except Exception as e:
        print(f"[cl] Login wait timed out: {e}")
        return False


def discover_collection_mapping(page) -> dict[str, str]:
    """Navigate to the collection list and try to scrape (cert -> cardId).

    Card Ladder's app is React-driven; the table rows usually carry the
    cardId as a query param on the row link, and the cert # appears as
    visible text. We grab anchors that match the cardId pattern, then for
    each one extract the nearest cert # (10-12 digit string) in surrounding
    text.
    """
    page.goto(COLLECTION_URL, wait_until="domcontentloaded")
    # Give the React-driven table time to fetch + render rows
    page.wait_for_timeout(6000)

    rows = page.eval_on_selector_all(
        "a[href*='cardId=']",
        """nodes => nodes.map(n => {
            const href = n.getAttribute('href') || '';
            const m = href.match(/cardId=([A-Za-z0-9_-]+)/);
            const cardId = m ? m[1] : null;
            // Look at the closest table-row ancestor (try several common patterns)
            let row = n.closest('tr') || n.closest('[role="row"]') || n.closest('li') || n.parentElement;
            const text = row ? row.innerText : n.innerText;
            return { cardId, text };
        })""",
    )

    mapping: dict[str, str] = {}
    cert_re = re.compile(r"\b(\d{8,12})\b")
    for row in rows:
        cid = row.get("cardId")
        if not cid: continue
        text = row.get("text") or ""
        for m in cert_re.finditer(text):
            cert = m.group(1)
            # Heuristic: if we haven't seen this cardId yet, take the first
            # plausible cert number found in the row.
            if cid not in mapping:
                mapping[cid] = cert
                break
    return mapping


def save_card_image(page, card_id: str, out_path: Path) -> bool:
    """Open the cardId detail URL and save the PSA slab image (preferred)
    or the largest card image as fallback."""
    url = CARD_DETAIL_TPL.format(card_id=card_id)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    # Strong preference: a PSA-hosted slab photo (cert-specific). Falls back
    # to the largest non-icon image on the page.
    src = page.evaluate(
        """() => {
            const imgs = [...document.querySelectorAll('img')];
            const scored = imgs
              .filter(i => i.complete && i.naturalWidth > 150)
              .map(i => {
                const s = (i.currentSrc || i.src || '').toLowerCase();
                let hint = 0;
                if (/psacard|psainstaservice|psaapi|images\\.psa/.test(s)) hint = 100;  // strongly prefer PSA
                else if (/(^|\\.)cgccards?\\.com|cgcimages|cgcapi/.test(s)) hint = 90;
                else if (/cardladder|cl-images|imgur/.test(s)) hint = 30;
                return {
                  src: i.currentSrc || i.src,
                  area: i.naturalWidth * i.naturalHeight,
                  hint,
                };
              })
              .sort((a, b) => (b.hint - a.hint) || (b.area - a.area));
            return scored.length ? scored[0].src : null;
        }"""
    )
    if not src:
        print(f"  [{card_id}] no image found")
        return False

    # Decide extension from URL
    ext = ".jpg" if re.search(r"\.jpe?g($|\?)", src, re.I) else ".png"
    out = out_path.with_suffix(ext)

    # Fetch via the same browser context so cookies/CDN-auth work
    resp = page.context.request.get(src)
    if not resp.ok:
        print(f"  [{card_id}] image fetch HTTP {resp.status}")
        return False
    out.write_bytes(resp.body())
    is_psa = bool(re.search(r"psacard|psainstaservice|psaapi", src, re.I))
    tag = "PSA" if is_psa else "img"
    print(f"  [{card_id}] {tag} -> {out.name} ({out.stat().st_size//1024} KB)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", metavar="URL", help="Open one URL and print page info; for selector debugging.")
    ap.add_argument("--urls", metavar="PATH", help="Text file with one cardId URL per line (overrides auto-scrape).")
    ap.add_argument("--limit", type=int, default=0, help="Only download the first N cards (0 = all).")
    ap.add_argument("--attach", type=int, metavar="PORT",
                    help="Attach to an existing Edge/Chrome started with --remote-debugging-port=PORT (default mode launches own Chromium).")
    args = ap.parse_args()

    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed yet. Run:")
        print("  pip install playwright && python -m playwright install chromium")
        return 1

    IMAGES_DIR.mkdir(exist_ok=True)
    PROFILE_DIR.mkdir(exist_ok=True)
    owned = load_owned_certs()

    with sync_playwright() as p:
        if args.attach:
            print(f"[cl] Attaching to existing browser at localhost:{args.attach} via CDP …")
            browser = p.chromium.connect_over_cdp(f"http://localhost:{args.attach}")
            # Use the existing default context (= the one with your login cookies)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        else:
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1400, "height": 950},
                args=["--no-default-browser-check"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if args.probe:
            page.goto(args.probe, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            info = page.evaluate(
                """() => ({
                    url: location.href,
                    title: document.title,
                    images: [...document.querySelectorAll('img')]
                      .filter(i => i.complete && i.naturalWidth > 100)
                      .slice(0, 8)
                      .map(i => ({src: i.currentSrc || i.src, w: i.naturalWidth, h: i.naturalHeight})),
                    cardLinks: [...document.querySelectorAll('a[href*=cardId]')].length,
                })"""
            )
            print(json.dumps(info, indent=2))
            input("Press Enter to close the browser…")
            ctx.close()
            return 0

        if args.attach:
            # Skip login dance — assume the attached browser is already authed
            page.goto(COLLECTION_URL, wait_until="domcontentloaded")
            if "/login" in page.url:
                print("[cl] Attached browser isn't logged into Card Ladder. Log in in that browser tab and re-run.")
                return 1
        else:
            if not wait_for_login(page):
                ctx.close()
                return 1

        # Mapping: cert -> cardId
        if args.urls:
            url_list = [u.strip() for u in Path(args.urls).read_text().splitlines() if u.strip()]
            cardids = [re.search(r"cardId=([A-Za-z0-9_-]+)", u).group(1) for u in url_list]
            mapping = {cid: cid for cid in cardids}  # use cardId as filename
        else:
            print("[cl] Scraping collection page for cardId <-> cert mapping...")
            mapping = discover_collection_mapping(page)
            print(f"[cl] Found {len(mapping)} cardId->cert mappings")
            MAPPING_FILE.write_text(json.dumps(mapping, indent=2))
            if owned:
                missing = owned - set(mapping.values())
                if missing:
                    print(f"[cl] Warning: {len(missing)} certs in pricing.csv had no CL match: "
                          f"{sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}")

        items = list(mapping.items())
        if args.limit: items = items[:args.limit]

        ok = fail = 0
        for i, (card_id, cert) in enumerate(items, 1):
            print(f"[{i}/{len(items)}] cardId={card_id}  cert={cert}")
            fname = f"{cert}.png" if cert and cert != card_id else f"cardId-{card_id}.png"
            out = IMAGES_DIR / fname
            try:
                if save_card_image(page, card_id, out):
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                print(f"  [{card_id}] error: {e}")
                fail += 1
            time.sleep(0.8)

        print(f"\n[cl] done — {ok} downloaded, {fail} failed -> {IMAGES_DIR}")
        ctx.close()
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
