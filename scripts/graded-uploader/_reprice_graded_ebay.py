"""GRADED reprice — eBay last-solds, STRICT exact-card comps, last-5 no-outlier.

cardladder's fuzzy text-search mismatched cards (averaged wrong variants/sets), so
graded is priced off eBay SOLD listings with strict, conservative comp selection:
the EXACT card (grader + grade + number + name), then a tight price cluster. If the
comps are ambiguous (mixed variants -> wide spread) or too few, we PARK -> Make Offer.
Never a guessed number. (user 2026-06-12: "make certain its the right card... if
something feels off just put make offer".)

Price = last-5 no-outlier of the clustered comps x 1.03. Push update-graded-price
for confident cards, clear-graded-price (Make Offer) for the rest.

Usage: python _reprice_graded_ebay.py [export.csv] [--live]
"""
from __future__ import annotations
import csv, json, math, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
DOWN = Path.home() / "Downloads"
WORKER = "https://sakekitty-square.nwilliams23999.workers.dev"
UPDATE = f"{WORKER}/admin/update-graded-price"
CLEAR = f"{WORKER}/admin/clear-graded-price"
UA = "Mozilla/5.0"
FEE = 1.03
LIVE = "--live" in sys.argv
MIN_COMPS = 3          # need >=3 qualifying comps
RECENT = 7             # consider the most-recent N qualifying sales
TRIM = 0.40            # within last-N, drop sales >+/-40% off the median (outliers)
MAX_SPREAD = 1.55      # the kept (trimmed) recent sales must agree this tightly, else PARK

# Variant qualifiers that denote a DIFFERENT product. A comp whose title contains one
# of these is rejected UNLESS that word is in the target card's own name/set (so a
# real "Dark Charizard" keeps Dark comps, but a base Neo Typhlosion drops Premium-File
# / Dark / Neo-Destiny comps). This is what number+name+grade matching can't catch.
VARIANT_WORDS = ["premium file", "premium", "dark", "light ", "shining", "shadowless",
                 "1st edition", "1st ed", "first edition", "staff", "prerelease",
                 "pre-release", "jumbo", "oversized", "error", "miscut", "misprint",
                 "crystal", "gold star", "shadow", "trophy", "no rarity", "no symbol"]


def tok():
    return (os.environ.get("SK_ADMIN_TOKEN") or subprocess.run(["powershell", "-NoProfile", "-Command",
        "[Environment]::GetEnvironmentVariable('SK_ADMIN_TOKEN','User')"], capture_output=True, text=True).stdout).strip()


def newest_export():
    fs = sorted(DOWN.glob("Collection - Card Ladder*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return fs[0] if fs else None


def held():
    f = HERE / "_held_certs.txt"; out = set()
    if f.exists():
        for ln in f.read_text().splitlines():
            ln = ln.split("#", 1)[0].strip()
            if ln: out.add(ln)
    return out


def parse_grade(cond):
    g = re.match(r"\s*([A-Za-z]+)", cond or ""); n = re.search(r"(\d+(?:\.\d+)?)", cond or "")
    return (g.group(1).upper() if g else "PSA"), (n.group(1) if n else "10")


def _num_re(number):
    """A regex matching the card number in an eBay title across formats:
    '157', '#157', '157/111', '07'->'7', 'GG70', 'SM211', 'RC29', 'TG17', 'SV107'."""
    bare = str(number).split("/")[0].strip()
    if bare.isdigit():
        core = str(int(bare))                    # '07' -> '7'
        return re.compile(rf"(?<!\d)0*{core}(?![\d])")  # matches 07 or 7, not 157->57
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(bare)}(?![A-Za-z0-9])", re.I)


def _wrong_variant(title, name, set_name):
    """True if the title carries a variant qualifier that is NOT part of THIS card."""
    t = title.lower(); own = f"{name} {set_name}".lower()
    for w in VARIANT_WORDS:
        if w in t and w.strip() not in own:
            return True
    return False


def qualifies(title, name, number, grader, grade, numrx, set_name=""):
    """Title must name the EXACT card: grader+grade, the number, a name word, and it
    must NOT carry a foreign variant qualifier (Premium File / Dark / Shadowless...)."""
    t = title.lower()
    gx = re.compile(rf"\b{re.escape(grader.lower())}\b[a-z .\-#]{{0,16}}\b{re.escape(str(grade))}\b(?![\d.])")
    if not gx.search(t): return False
    if not numrx.search(title): return False
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
             if w not in ("fa", "full", "art", "the", "of", "and", "&") and len(w) >= 3]
    if words and not any(w in t for w in words): return False
    if _wrong_variant(title, name, set_name): return False
    return True


def price_from_comps(items, name, number, grader, grade, set_name=""):
    """(price|None, note). EXACT-card + variant-guard comps -> most-recent N -> drop
    statistical outliers -> last-5 no-outlier. The user's rule literally: 'right
    variant, grade, grading company, last 5 sold excluding outliers'. PARK if the
    clean recent sales are too few or still don't agree (genuinely ambiguous)."""
    numrx = _num_re(number)
    q = [(float(it["totalPrice"]), it.get("endedAt", "")) for it in items
         if it.get("totalPrice") and qualifies(it.get("title", ""), name, number, grader, grade, numrx, set_name)]
    if len(q) < MIN_COMPS:
        return None, f"only {len(q)} exact-card comps"
    q.sort(key=lambda x: x[1], reverse=True)               # most-recent first
    recent = q[:RECENT]
    rp = sorted(p for p, _ in recent)
    med = rp[len(rp) // 2]
    kept = [p for p in rp if med * (1 - TRIM) <= p <= med * (1 + TRIM)]  # drop outliers
    if len(kept) < MIN_COMPS:
        return None, f"only {len(kept)} clean recent (of {len(q)})"
    if max(kept) / max(min(kept), 0.01) > MAX_SPREAD:
        return None, f"ambiguous (recent spread {max(kept)/min(kept):.2f}, {len(q)} comps)"
    five = kept[:5]
    if len(five) >= 5: five = five[1:-1]                   # last-5 drop high+low
    return round(sum(five) / len(five), 2), f"{len(q)} comps, {len(kept)} clean recent, last5-no-outlier"


def main():
    from _ebay_chrome import fetch_or_cache
    src = next((Path(a) for a in sys.argv[1:] if not a.startswith("-")), None) or newest_export()
    if not src or not src.exists(): print("no export"); return 1
    HELD = held()
    cards = []
    for r in csv.DictReader(src.open(encoding="utf-8-sig")):
        cert = (r.get("Graded Cert #") or "").strip()
        if not cert or cert in HELD: continue
        grader, grade = parse_grade(r.get("Condition"))
        name = (r.get("Subject") or "").strip()
        cards.append({"cert": cert, "name": name, "set": (r.get("Set") or "").strip(),
                      "number": (r.get("Number") or "").strip(), "year": (r.get("Year") or "").strip(),
                      "grader": grader, "grade": grade})
    print(f"GRADED via eBay strict comps — {len(cards)} cards")
    queries = {c["cert"]: f"{c['year']} {c['name']} {c['number']} {c['set']} {c['grader']} {c['grade']}".strip()
               for c in cards}
    grouped = fetch_or_cache(queries, force_fresh=("--cached" not in sys.argv))

    rows = []
    for c in cards:
        items = grouped.get(c["cert"]) or grouped.get(queries[c["cert"]]) or []
        price, note = price_from_comps(items, c["name"], c["number"], c["grader"], c["grade"], c["set"])
        if price:
            rows.append({**c, "price": price, "sell": math.ceil(price * FEE), "park": False, "note": note, "raw": len(items)})
        else:
            rows.append({**c, "price": None, "sell": None, "park": True, "note": note, "raw": len(items)})
    priced = [r for r in rows if not r["park"]]
    parked = [r for r in rows if r["park"]]
    print(f"  PRICED {len(priced)} | PARKED(make-offer) {len(parked)}")
    for r in sorted(priced, key=lambda x: -x["sell"]):
        print(f"    ${r['sell']:<6} (last5 ${r['price']})  {r['grader']} {r['grade']} {r['name'][:30]} #{r['number']}  [{r['note']}]")
    print("  --- PARKED ---")
    for r in parked:
        print(f"    {r['grader']} {r['grade']} {r['name'][:30]} #{r['number']}  [{r['note']}; {r['raw']} raw]")
    with (HERE / "_graded_ebay_review.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["cert", "grader", "grade", "name", "number", "set", "last5", "suggested", "parked", "note"])
        for r in rows: w.writerow([r["cert"], r["grader"], r["grade"], r["name"], r["number"], r["set"], r["price"], r["sell"], r["park"], r["note"]])
    print("  CSV -> _graded_ebay_review.csv")

    if not LIVE:
        print("  [dry-run] pass --live to push"); return 0
    T = tok(); ok = pk = fail = 0
    for r in rows:
        try:
            if not r["park"]:
                req = urllib.request.Request(UPDATE, method="POST",
                    data=json.dumps({"cert": r["cert"], "price_cents": int(r["sell"] * 100)}).encode(),
                    headers={"content-type": "application/json", "X-Sake-Admin-Token": T, "user-agent": UA})
            else:
                req = urllib.request.Request(CLEAR, method="POST",
                    data=json.dumps({"cert": r["cert"]}).encode(),
                    headers={"content-type": "application/json", "X-Sake-Admin-Token": T, "user-agent": UA})
            d = json.loads(urllib.request.urlopen(req, timeout=60).read())
            if d.get("ok"): (ok if not r["park"] else pk) and None; ok += (0 if r["park"] else 1); pk += (1 if r["park"] else 0)
        except urllib.error.HTTPError as e:
            if e.code == 404: pass
            else: fail += 1; print(f"  ERR {r['cert']}: {e.code}")
        except Exception as e:
            fail += 1; print(f"  ERR {r['cert']}: {str(e)[:80]}")
        time.sleep(0.25)
    print(f"  graded: {ok} priced, {pk} parked->Make Offer (fail {fail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
