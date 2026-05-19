"""Re-fetch eBay sold listings for the 6 flagged certs from the 2026-05-18
reprice run, using an IMPROVED keyword builder + stricter post-filter.

v2 keyword format pulls all the disambiguators a real eBay search would use:
  {year} {subject_clean} {variation_clean} #{number_short} {set_clean} {grade}

Stricter post-filter requires:
  - grade in title
  - card subject token in title (e.g. PIDGEOTTO)
  - card number in title

Outputs side-by-side comparison of v1 (today's run) vs v2 results.
"""
from __future__ import annotations
import csv, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
CL_CSV = Path(r"C:\Users\lunar\Downloads\Collection - Card Ladder (19).csv")
REPORT = HERE / "_multisource_report_2026-05-18.csv"

# Flagged certs from today's run (the raises with weak/contradictory eBay signal)
FLAGGED = [
    "107496657",  # FA Rayquaza VMAX Vmax Climax JP
    "112214360",  # Pidgeotto IR Obsidian Flames
    "99211118",   # FA Espeon VMAX Fusion Strike (eBay outlier-rejected last run)
    "3914522049", # Feraligatr Neo Genesis CGC 8.5
    "4321131035", # Blastoise SAR 151 JP CGC Pristine
    "4322429002", # Eevee Yu Nagaba CGC Pristine
    # Bonus — pushed big this run, worth validating
    "128159429",  # Pikachu 172 Simp Chinese
    "84566703",   # Moltres Vending
    "110772487",  # Charizard V Alt Art Brilliant Stars
]

# ----- keyword builders -----

# CL set-prefix slugs that don't appear in eBay titles
CL_SET_PREFIXES = re.compile(
    r"\b(?:Obf|Wht|Sv\d+(?:pt\d+|[a-z]+)?|Pre|Meg|Asc|Blk|Paf|Svp|Sv\da?|Wsv|Bsv)"
    r"\s+(?:En|Jp|Sc)\s*-\s*", re.I
)


def clean_set(s: str) -> str:
    s = re.sub(r"^Pokemon\s+(Japanese\s+)?", "", s, flags=re.I)
    s = CL_SET_PREFIXES.sub("", s)
    s = s.replace(":", " ").replace("&", "and")
    return " ".join(s.split())


def clean_subject(s: str) -> str:
    # Strip leading "Fa /", "FA /" etc — eBay sellers say "Full Art" not "Fa"
    s = re.sub(r"^(FA|Fa|Full\s*Art)\s*/\s*", "", s)
    # Strip CL's "-Holo", "-Rev.foil", "-Reverse", "-Secret"
    s = re.sub(r"-(Holo|Rev\.?\s*foil|Reverse|Secret)\b", "", s, flags=re.I)
    s = s.replace("/", " ").replace(":", "")
    return " ".join(s.split())


def clean_variation(v: str) -> str:
    if not v:
        return ""
    # CL sometimes duplicates set name in variation (e.g. "Vmax Climax" for a Vmax Climax set)
    # Strip pure set name dupes; keep meaningful variation markers
    v = v.replace(":", " ").replace("&", "and")
    # If variation is the same as part of the set name, drop it
    if re.match(r"^(Vmax|Sword|Shield|Scarlet|Violet|Sun|Moon)\s*", v, re.I):
        if any(t in v for t in ("Climax", "Voltage", "Skies", "Strike", "Bolt", "Flare")):
            return ""  # set-name duplicate
    return " ".join(v.split())


def short_number(n: str) -> str:
    """For '202/165' -> '202'; '062/SV-P' -> '062'; '5/111' -> '5'."""
    n = (n or "").strip().lstrip("#")
    if "/" in n:
        n = n.split("/", 1)[0]
    return n


def grade_for_query(g: str) -> str:
    g = (g or "").strip()
    # Collapse "CGC 10  Pristine" -> "CGC Pristine 10" (eBay seller style)
    if re.match(r"^CGC\s*10\s*Pristine$", g, re.I):
        return "CGC Pristine 10"
    return g


def build_v2(cl_row: dict) -> str:
    """v2 keyword: {year} {subject_clean} {variation_clean} #{num_short} {set_clean} {grade}"""
    year = (cl_row.get("Year") or "").strip()
    subject = clean_subject(cl_row.get("Subject") or "")
    variation = clean_variation(cl_row.get("Variation") or "")
    number = short_number(cl_row.get("Number") or "")
    set_clean = clean_set(cl_row.get("Set") or "")
    grade = grade_for_query(cl_row.get("Condition") or "")

    parts = []
    if year: parts.append(year)
    if subject: parts.append(subject)
    if variation: parts.append(variation)
    if number: parts.append(f"#{number}")
    if set_clean: parts.append(set_clean)
    if grade: parts.append(grade)
    return " ".join(parts)


def build_v1(cl_row: dict, grade: str) -> str:
    """Mirror of the live builder in _multisource_reprice.py."""
    subject = (cl_row.get("Subject") or "").strip()
    subject = re.sub(r"-(Holo|Rev\.?\s*foil|Reverse|Secret)\b", "", subject, flags=re.I).strip()
    number = (cl_row.get("Number") or "").strip()
    set_field = (cl_row.get("Set") or "").strip()
    set_clean = re.sub(r"^Pokemon\s+(Japanese\s+)?", "", set_field, flags=re.I).strip()
    set_short = " ".join(set_clean.split()[:3])
    parts = [grade, subject]
    if number:
        parts.append(f"#{number}" if not number.startswith("#") else number)
    if set_short:
        parts.append(set_short)
    return " ".join(p for p in parts if p)


# ----- post-filter -----

def title_passes_v2(title: str, subject: str, number: str, grade: str) -> bool:
    t = title.upper().replace(".", "").replace("-", " ")
    # Grade
    g = grade.upper().replace(".", "").replace(" ", "")
    grade_ok = (
        g in t.replace(" ", "") or
        (g == "PSA10" and ("GEMMT10" in t.replace(" ", "") or "GEMMINT10" in t.replace(" ", ""))) or
        (g.startswith("CGCPRISTINE") and "PRISTINE" in t and "10" in t)
    )
    if not grade_ok:
        return False
    # Subject — first word of cleaned subject must appear
    subj_word = (clean_subject(subject).split() or [""])[0].upper()
    # Drop short subj words to avoid false positives ("V", "Ex" etc)
    if len(subj_word) >= 4 and subj_word not in t:
        return False
    # Number — short number must appear (as #N or just N) — only enforce if 3+ digits
    n_short = short_number(number)
    if n_short and len(n_short) >= 2 and n_short not in t:
        return False
    return True


# ----- apify caller -----

def get_apify_token() -> str:
    t = os.environ.get("APIFY_API_TOKEN", "").strip()
    if t: return t
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Environment]::GetEnvironmentVariable('APIFY_API_TOKEN','User')"],
        capture_output=True, text=True, timeout=10, check=True,
    )
    return r.stdout.strip()


def run_apify(keywords: list[str], token: str, category_id: str = "183454") -> dict:
    """Single run with up to 6 keywords. Returns {keyword: [items]}.
    category_id 183454 = Pokemon TCG Singles. '0' = all categories.
    """
    body = json.dumps({
        "keywords": keywords,
        "daysToScrape": 60,
        "count": 8,
        "categoryId": category_id,
        "ebaySite": "ebay.com",
        "sortOrder": "endedRecently",
        "itemLocation": "default",
        "itemCondition": "any",
        "detailedSearch": False,
    }).encode()
    url = f"https://api.apify.com/v2/acts/oTtB3VgfuE9GtxQt2/runs?token={token}"
    req = urllib.request.Request(url, method="POST", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())["data"]
    except urllib.error.HTTPError as e:
        print(f"  [apify] HTTP {e.code}: {e.read()[:500].decode('utf-8','replace')}")
        raise
    run_id, dataset_id = data["id"], data["defaultDatasetId"]
    print(f"  [apify] run {run_id} started ({len(keywords)} kw)")
    # Poll
    waited = 0
    while waited < 300:
        time.sleep(10); waited += 10
        with urllib.request.urlopen(
            f"https://api.apify.com/v2/actor-runs/{run_id}?token={token}", timeout=30
        ) as r:
            status = json.loads(r.read())["data"]["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
    print(f"  [apify] run finished status={status} after {waited}s")
    # Fetch dataset
    items = []
    offset = 0
    while True:
        with urllib.request.urlopen(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={token}&offset={offset}&limit=1000",
            timeout=60,
        ) as r:
            batch = json.loads(r.read())
        if not batch: break
        items.extend(batch); offset += len(batch)
        if len(batch) < 1000: break
    grouped: dict[str, list[dict]] = {}
    for it in items:
        kw = it.get("keyword", "")
        grouped.setdefault(kw, []).append(it)
    return grouped


# ----- main -----

def main():
    # Load CL rows for flagged certs
    cl_map = {}
    with CL_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            cert = r.get("Graded Cert #", "").strip()
            if cert: cl_map[cert] = r

    # Build v2 keywords
    queries = {}
    for cert in FLAGGED:
        cl = cl_map.get(cert)
        if not cl:
            print(f"!! cert {cert} not in CL")
            continue
        v1 = build_v1(cl, grade_for_query(cl.get("Condition", "")))
        v2 = build_v2(cl)
        queries[cert] = {"cl": cl, "v1": v1, "v2": v2}
        print(f"cert {cert}")
        print(f"  v1: {v1}")
        print(f"  v2: {v2}")
        print()

    # Re-fetch v2 in batches of 6
    token = get_apify_token()
    if not token:
        print("APIFY_API_TOKEN missing"); return 1

    v2_kws = [q["v2"] for q in queries.values()]
    batches = [v2_kws[i:i+6] for i in range(0, len(v2_kws), 6)]
    grouped_all = {}
    for i, batch in enumerate(batches, 1):
        print(f"\n[batch {i}/{len(batches)}] fetching {len(batch)} kw (categoryId=0 all)")
        try:
            g = run_apify(batch, token, category_id="0")
        except Exception as e:
            print(f"  [apify] error: {e}")
            continue
        grouped_all.update(g)

    # Print results per cert with stricter post-filter
    print()
    print("=" * 100)
    for cert, q in queries.items():
        items = grouped_all.get(q["v2"], [])
        subj = q["cl"].get("Subject", "")
        num = q["cl"].get("Number", "")
        grade = q["cl"].get("Condition", "")

        # Pre-filter (just grade, like v1 does)
        loose = [it for it in items if grade.split()[0].upper() in it.get("title","").upper()]
        # Strict filter (grade + subject + number)
        strict = [it for it in items if title_passes_v2(it.get("title",""), subj, num, grade)]

        def avg(lst):
            ps = []
            for it in lst:
                try:
                    p = float(it.get("totalPrice") or it.get("soldPrice") or 0)
                    if 1 < p < 100000: ps.append(p)
                except: pass
            return (sum(ps)/len(ps), len(ps)) if ps else (None, 0)

        loose_avg, loose_n = avg(loose)
        strict_avg, strict_n = avg(strict)

        print(f"\ncert {cert}  ({subj} #{num} {grade})")
        print(f"  v2 query: {q['v2']}")
        print(f"  raw items: {len(items)}  | loose-grade-filter: {loose_n} avg=${loose_avg or 0:.2f}  | STRICT: {strict_n} avg=${strict_avg or 0:.2f}")
        print(f"  TOP STRICT-MATCH LISTINGS:")
        for it in strict[:6]:
            t = it.get("title", "")[:100]
            p = it.get("totalPrice") or it.get("soldPrice") or 0
            d = (it.get("endedAt", "") or "")[:10]
            try: p = float(p)
            except: p = 0
            print(f"    ${p:>7.2f} {d} | {t}")
        if strict_n == 0 and loose_n:
            print(f"  ⚠️  No strict matches; here are loose grade-only matches that fell through filter:")
            for it in loose[:5]:
                t = it.get("title", "")[:100]
                p = it.get("totalPrice") or it.get("soldPrice") or 0
                try: p = float(p)
                except: p = 0
                print(f"    ${p:>7.2f}  | {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
