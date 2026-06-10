r"""
Build the top-50 "Make Offer" singles dataset for singles.html.

1. Reads the TCGplayer MyPricing export, ranks in-stock cards by TCG Market
   Price, takes the top 50.
2. For each, resolves the TCGplayer productId via tcgsearch.com's rendered
   search UI (Playwright) and downloads the stock card image from the
   TCGplayer CDN into assets/singles/<pid>.jpg.
3. Writes assets/singles/singles_data.json (no prices — Make Offer model).

Run with the py launcher (Playwright lives on Python 3.14 here):
    py -3 scripts/build_singles.py [--limit N]
"""
from __future__ import annotations
import argparse, csv, json, re, sys, time, urllib.request, urllib.parse
from pathlib import Path

CSV = r"C:\Users\lunar\Downloads\TCGplayer__MyPricing_20260610_045020.csv"
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "singles"
OUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_JSON = OUT_DIR / "singles_data.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def fnum(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0


def top_cards(n=50):
    rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig")))
    ins = [r for r in rows if fnum(r.get("Total Quantity")) > 0 and fnum(r.get("TCG Market Price")) > 0]
    ins.sort(key=lambda r: fnum(r.get("TCG Market Price")), reverse=True)
    out = []
    for r in ins[:n]:
        name = (r.get("Product Name") or "").strip()
        number = (r.get("Number") or "").strip()
        # Product Name often carries a trailing " - 276/217"; drop it for the query
        clean = re.sub(r"\s*-\s*[0-9A-Za-z]+/[0-9A-Za-z]+\s*$", "", name).strip()
        out.append({
            "name": clean, "raw_name": name, "set": (r.get("Set Name") or "").strip(),
            "number": number, "rarity": (r.get("Rarity") or "").strip(),
            "condition": (r.get("Condition") or "").strip(),
            "qty": int(fnum(r.get("Total Quantity"))),
            "lang": "Japanese" if "Japanese" in (r.get("Product Name") or "") else "English",
        })
    return out


def search_pid(page, card):
    """Resolve a TCGplayer productId from tcgsearch's rendered search results."""
    q = f'{card["name"]} {card["number"]}'.strip()
    url = f"https://www.tcgsearch.com/search?q={urllib.parse.quote(q)}&language=all&type=card&tcg=pokemon"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        return None
    # results render client-side; wait for the first card link
    pid = None
    for _ in range(16):
        page.wait_for_timeout(500)
        pid = page.evaluate("""() => {
            const a = document.querySelector('a[href*="/card/"]');
            if (!a) return null;
            const m = a.getAttribute('href').match(/\\/card\\/(\\d+)/);
            return m ? m[1] : null;
        }""")
        if pid:
            break
    return pid


def download_img(pid):
    for size in ("_400w.jpg", "_in_1000x1000.jpg", "_200w.jpg"):
        u = f"https://tcgplayer-cdn.tcgplayer.com/product/{pid}{size}"
        try:
            data = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=20).read()
            if len(data) > 2000:
                (OUT_DIR / f"{pid}.jpg").write_bytes(data)
                return f"assets/singles/{pid}.jpg"
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    cards = top_cards(50)[: args.limit]
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(user_agent=UA)
        # warm up so the SPA boots
        try:
            page.goto("https://www.tcgsearch.com/", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
        except Exception:
            pass
        for i, c in enumerate(cards, 1):
            pid = search_pid(page, c)
            img = download_img(pid) if pid else None
            c["pid"] = pid
            c["img"] = img
            results.append(c)
            print(f"{i:2}. pid={pid or '----':>7}  img={'OK ' if img else 'MISS'}  {c['raw_name']} | {c['set']} #{c['number']}", flush=True)
            time.sleep(0.4)
        b.close()

    DATA_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    miss = [r for r in results if not r["img"]]
    print(f"\nDONE: {len(results)-len(miss)}/{len(results)} images. data -> {DATA_JSON}")
    if miss:
        print("MISSING:", [f"{m['raw_name']} #{m['number']}" for m in miss])


if __name__ == "__main__":
    main()
