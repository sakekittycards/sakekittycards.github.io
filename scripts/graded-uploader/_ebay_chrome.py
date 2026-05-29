"""eBay Sold Listings via a real Chrome browser (Playwright) — the eBay sold-comp
source for graded reprice. REPLACES the Apify actor (`_ebay_apify.py`).

Why we ditched Apify (2026-05-27): its 8-result / 60-day non-detailed search
returned wrong lows — e.g. Deoxys GG12 Crown Zenith PSA 10 came back $198 when
the real sold median is ~$300 (confirmed by scraping eBay directly) — and it
burns a metered monthly quota that 403s when exhausted.

eBay's *sold* search pages are public (no login) and load fine in a real Chrome
driven by Playwright with the same anti-automation launch flags that
`scripts/psa-scraper/scraper.mjs` uses to beat the much harder Cloudflare gate
on Collectors.com: a persistent profile, a real UA, headful, and
`--disable-blink-features=AutomationControlled`. No bot wall, full result set,
real per-listing sold dates.

Drop-in for `_ebay_apify`: exposes
  - fetch_or_cache(card_queries: {cert: keyword}) -> {cert: [item, ...]}
  - fetch_ebay(keywords) -> {keyword: [item, ...]}      (alias: fetch_apify)
  - average_last_5(items, grade) -> float | None
Each item carries the keys the downstream filter expects:
  {"title": str, "totalPrice": float, "endedAt": "YYYY-MM-DD"}
so _multisource_reprice.py only needs its import line changed.

Headful by default (matches psa-scraper; most reliable). Set EBAY_HEADLESS=1 to
run headless once you've confirmed eBay isn't challenging your IP.

PROXY REQUIRED: all scraping runs through a proxy (Nick 2026-05-27) so we never
hammer eBay from the bare residential IP. Configure EBAY_PROXY / SK_SCRAPE_PROXY
or ~/.claude/scrape_proxy.txt as scheme://[user:pass@]host:port. Runs abort if
no proxy is set unless ALLOW_NO_PROXY=1.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / "_ebay_chrome_profile"   # persistent Chrome profile (gitignored)
# Deliberately a NEW cache file — do not inherit _ebay_apify's cached numbers,
# some of which are the wrong lows that motivated this rewrite.
CACHE_FILE = HERE / "_ebay_chrome_cache.json"
CACHE_TTL_HOURS = 72                            # recent solds move quickly
RESULTS_PER_PAGE = 120                          # _ipg=120 — one page of sold comps
NAV_DELAY_SEC = 2.5                             # polite delay between navigations
PAGE_TIMEOUT_MS = 45_000

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Competing-slab noise that pollutes a grade average — kept for average_last_5
# parity with _ebay_apify (the reprice does its own strict filter on top).
_NOISE_TITLE_WORDS = ("BGS", "CGC", "SGC", "REGRADE", "RAW", "UNGRADED", "AUTHENTIC ONLY")


def sold_url(keyword: str) -> str:
    """eBay sold + completed listings URL (matches ebay_sold_url in the reprice)."""
    return (f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(keyword)}"
            f"&LH_Sold=1&LH_Complete=1&_ipg={RESULTS_PER_PAGE}")


# Proxy is REQUIRED (Nick 2026-05-27: "make sure youre doing all this behind a
# proxy") so we never hammer eBay from the bare residential IP. Configure via
# the EBAY_PROXY / SK_SCRAPE_PROXY env var or ~/.claude/scrape_proxy.txt, in the
# form scheme://[user:pass@]host:port (e.g. http://user:pass@gate.smartproxy.com:7000).
PROXY_FILE = Path.home() / ".claude" / "scrape_proxy.txt"


def _proxy_config() -> dict | None:
    """Resolve the scrape proxy into Playwright's proxy dict, or None if unset."""
    raw = (os.environ.get("EBAY_PROXY") or os.environ.get("SK_SCRAPE_PROXY") or "").strip()
    if not raw and PROXY_FILE.exists():
        raw = PROXY_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    u = urllib.parse.urlparse(raw if "://" in raw else "http://" + raw)
    if not u.hostname:
        return None
    server = f"{u.scheme}://{u.hostname}" + (f":{u.port}" if u.port else "")
    cfg = {"server": server}
    if u.username:
        cfg["username"] = urllib.parse.unquote(u.username)
    if u.password:
        cfg["password"] = urllib.parse.unquote(u.password)
    return cfg


# ─── cache (same shape + semantics as _ebay_apify) ──────────────────────────
def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _fresh(entry: dict) -> bool:
    return (time.time() - entry.get("fetched_at", 0)) / 3600 <= CACHE_TTL_HOURS


# ─── parsing ────────────────────────────────────────────────────────────────
def _parse_sold_date(s: str) -> str:
    """'Sold  May 25, 2026' -> '2026-05-25'. Returns '' if unparseable."""
    m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})", s or "")
    if not m:
        return ""
    try:
        dt = datetime.datetime.strptime(f"{m.group(1)} {int(m.group(2))} {m.group(3)}", "%b %d %Y")
        return dt.date().isoformat()
    except ValueError:
        return ""


def _parse_price(s: str) -> float | None:
    """'$299.00' or '$290.00 to $315.00' -> 299.0 / 290.0 (first number)."""
    m = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", s or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


# In-page extractor: pull (title, price, sold-caption) per result row and
# de-dupe (eBay renders each listing in two stacked containers). Returns raw
# strings — Python side parses prices/dates so the logic stays testable.
_EXTRACT_JS = r"""() => {
  const rows = [...document.querySelectorAll('li.s-item, li.s-card')];
  const seen = new Set();
  const out = [];
  for (const el of rows) {
    const a = el.querySelector('a.s-item__link, a.su-link, a[href*="/itm/"]');
    const href = a ? a.href.split('?')[0] : '';
    let title = (el.querySelector('.s-item__title, [role="heading"], .su-styled-text.primary')?.textContent || '').trim();
    title = title.replace(/^New Listing/i, '').replace(/Opens in a new window or tab.*$/i, '').trim();
    const price = (el.querySelector('.s-item__price, .s-card__price')?.textContent || '').trim();
    const sold  = (el.querySelector('.s-item__caption, .s-card__caption, .POSITIVE')?.textContent || '').trim();
    if (!title || !price || /Shop on eBay/i.test(title)) continue;
    // Best Offer sales render "Best offer accepted" / "or Best Offer" in the
    // card text, and the price shown is the ASK (not the accepted amount) — so
    // they read high. Flag them; the reprice drops them (Nick: clean comps,
    // don't consider Best Offer).
    const itxt = (el.innerText || '').toLowerCase();
    const bestOffer = /best offer|obo\b/.test(itxt);
    const key = href || (title + '|' + price + '|' + sold);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ title, price, sold, bestOffer });
  }
  return out;
}"""


def _scrape_once(page, keyword: str) -> list[dict]:
    page.goto(sold_url(keyword), wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    try:
        page.wait_for_selector("li.s-item, li.s-card, .srp-save-null-search",
                               timeout=15_000)
    except Exception:
        pass  # no-results pages never show the list; fall through to extract
    page.wait_for_timeout(800)  # let the SRP finish painting result rows
    raw = page.evaluate(_EXTRACT_JS)
    items: list[dict] = []
    for r in raw:
        price = _parse_price(r.get("price", ""))
        if price is None or price <= 1:
            continue
        items.append({
            "title": r.get("title", ""),
            "totalPrice": price,
            "endedAt": _parse_sold_date(r.get("sold", "")),
        })
    return items


def _scrape(page, keyword: str) -> list[dict]:
    """Scrape one keyword, with a single retry. A 0-result first pass is almost
    always an interstitial/late render rather than a genuinely empty search, so
    re-navigate once before believing it."""
    items = _scrape_once(page, keyword)
    if not items:
        page.wait_for_timeout(1500)
        items = _scrape_once(page, keyword)
    return items


def _warmup(page) -> None:
    """First navigation on a fresh profile can land on an eBay consent/splash
    interstitial that swallows the SRP. Hit the homepage once, dismiss any
    consent button, so the actual sold-page navigations return results."""
    try:
        page.goto("https://www.ebay.com/", wait_until="domcontentloaded",
                  timeout=PAGE_TIMEOUT_MS)
        page.wait_for_timeout(1500)
        for sel in ('button#gdpr-banner-accept',
                    'button[aria-label="Accept all"]',
                    'button:has-text("Accept all")'):
            try:
                btn = page.query_selector(sel)
                if btn:
                    btn.click()
                    page.wait_for_timeout(800)
                    break
            except Exception:
                pass
    except Exception as e:
        print(f"[ebay-chrome] warmup nav failed (continuing): {e}")


def fetch_ebay(keywords: list[str]) -> dict[str, list[dict]]:
    """Open one persistent-profile Chrome and scrape every keyword's sold page.
    Returns {keyword: [item, ...]}. Never raises — a per-keyword failure yields
    an empty list for that keyword so the reprice falls back to PC."""
    grouped: dict[str, list[dict]] = {}
    if not keywords:
        return grouped
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    headless = os.environ.get("EBAY_HEADLESS") == "1"
    proxy = _proxy_config()
    if proxy is None and os.environ.get("ALLOW_NO_PROXY") != "1":
        raise SystemExit(
            "[ebay-chrome] No proxy configured — refusing to scrape from the bare IP.\n"
            "  Set EBAY_PROXY=scheme://user:pass@host:port (or write it to\n"
            f"  {PROXY_FILE}), or pass ALLOW_NO_PROXY=1 to override.")
    where = proxy["server"] if proxy else "NO PROXY (override)"
    print(f"[ebay-chrome] scraping {len(keywords)} keyword(s) "
          f"({'headless' if headless else 'headful'}) via {where} ...")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=headless,
            proxy=proxy,
            args=["--disable-blink-features=AutomationControlled", "--disable-infobars"],
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _warmup(page)
            for i, kw in enumerate(keywords, 1):
                try:
                    items = _scrape(page, kw)
                except Exception as e:
                    print(f"[ebay-chrome] {i:>2}/{len(keywords)} ERR  {kw[:55]}: {e}")
                    items = []
                grouped[kw] = items
                print(f"[ebay-chrome] {i:>2}/{len(keywords)} {len(items):>3} comps  {kw[:60]}")
                if i < len(keywords):
                    time.sleep(NAV_DELAY_SEC)
        finally:
            ctx.close()
    return grouped


# Legacy alias: _apply_max_price_formula.py imports `fetch_apify`-style helpers.
fetch_apify = fetch_ebay


def fetch_or_cache(card_queries: dict[str, str]) -> dict[str, list[dict]]:
    """card_queries: {cert: keyword}. Returns {cert: [items]}.
    Reads cache first; only scrapes un-cached or stale keywords (72h TTL)."""
    cache = _load_cache()
    out: dict[str, list[dict]] = {}
    to_fetch: dict[str, str] = {}
    for cert, kw in card_queries.items():
        entry = cache.get(kw)
        if entry and _fresh(entry):
            out[cert] = entry["items"]
        else:
            to_fetch[cert] = kw

    if to_fetch:
        print(f"[ebay-chrome] {len(out)} cached, {len(to_fetch)} need scrape")
        keywords = list(set(to_fetch.values()))
        grouped = fetch_ebay(keywords)
        for kw, items in grouped.items():
            cache[kw] = {"fetched_at": time.time(), "items": items}
        _save_cache(cache)
        for cert, kw in to_fetch.items():
            out[cert] = grouped.get(kw, [])
    else:
        print(f"[ebay-chrome] all {len(out)} certs satisfied from cache")
    return out


# ─── average helper (parity with _ebay_apify for any legacy caller) ─────────
def _grade_in_title(title: str, grade: str) -> bool:
    t = (title or "").upper()
    for noise in _NOISE_TITLE_WORDS:
        if noise in t:
            return False
    g = grade.upper().replace(" ", "").replace(".", "")
    if g in t.replace(" ", "").replace(".", ""):
        return True
    if "PSA10" in g and ("GEM MT 10" in t or "GEM MINT 10" in t):
        return True
    if "PSA9" in g and "PSA 9" in t:
        return True
    return False


def average_last_5(items: list[dict], grade: str) -> float | None:
    """Median of the last-5 sold (by endedAt desc) whose title matches the grade.
    Median (not mean) drops one Best-Offer low outlier — same rationale as the
    Apify version it replaces."""
    if not items:
        return None
    filtered = [it for it in items if _grade_in_title(it.get("title", ""), grade)]
    if not filtered:
        return None
    filtered.sort(key=lambda it: it.get("endedAt", ""), reverse=True)
    prices = []
    for it in filtered[:5]:
        try:
            p = float(it.get("totalPrice") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            prices.append(p)
    if not prices:
        return None
    prices.sort()
    n = len(prices)
    if n % 2 == 1:
        return round(prices[n // 2], 2)
    return round((prices[n // 2 - 1] + prices[n // 2]) / 2, 2)


if __name__ == "__main__":
    # Smoke test: scrape a few hand cards and print the parsed last-5.
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    tests = [
        "2023 Deoxys GG12 Crown Zenith PSA 10",
        "2025 Reshiram Ex Black White Rare #173 White Flare PSA 10",
        "2022 Full Art Pikachu #205 Sword & Shield Vstar Universe PSA 10",
    ]
    grouped = fetch_ebay(tests)
    for kw in tests:
        items = grouped.get(kw, [])
        items.sort(key=lambda it: it.get("endedAt", ""), reverse=True)
        last5 = [(it["endedAt"], it["totalPrice"], it["title"][:55]) for it in items[:5]]
        print(f"\n=== {kw}")
        print(f"    {len(items)} comps; median-last-5 = {average_last_5(items, 'PSA 10')}")
        for d, p, t in last5:
            print(f"      {d}  ${p:<8}  {t}")
