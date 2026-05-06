"""eBay Sold Listings Search via Apify — last-5-sold average per card.

Wraps the caffein.dev/ebay-sold-listings actor (actor id oTtB3VgfuE9GtxQt2).
Strategy:
  - One async run with all keywords batched.
  - Poll until SUCCEEDED.
  - Fetch dataset, group items by `keyword`, sort by `endedAt` desc,
    take last 5 sold prices (using `totalPrice`, which includes shipping —
    apples-to-apples with our free-shipping list price).
  - Filter to items whose title contains the expected grade
    (e.g., "PSA 10") to drop ungraded comps.
  - Cache per-keyword results in _ebay_cache.json (3-day TTL — recent solds
    move quickly).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ACTOR_ID = "oTtB3VgfuE9GtxQt2"  # caffein.dev/ebay-sold-listings
API_BASE = "https://api.apify.com/v2"
CACHE_FILE = Path(__file__).parent / "_ebay_cache.json"
CACHE_TTL_HOURS = 72  # 3 days
PRICE_PER_KEYWORD = 8  # how many results to request per keyword


def get_token() -> str | None:
    t = os.environ.get("APIFY_API_TOKEN")
    if t:
        return t.strip()
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('APIFY_API_TOKEN','User')"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


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
    age_hours = (time.time() - entry.get("fetched_at", 0)) / 3600
    return age_hours <= CACHE_TTL_HOURS


def _grade_in_title(title: str, grade: str) -> bool:
    """Loose grade check — title should mention the grade."""
    t = title.upper()
    g = grade.upper().replace(" ", "").replace(".", "")
    # Normalize common variants: "PSA10" matches "PSA 10" / "GEM MT 10" / "PSA10"
    if g in t.replace(" ", "").replace(".", ""):
        return True
    # PSA 10 = GEM MT 10 / GEM MINT 10 fallback
    if "PSA10" in g and ("GEM MT 10" in t or "GEM MINT 10" in t):
        return True
    if "PSA9" in g and "PSA 9" in t:
        return True
    return False


def average_last_5(items: list[dict], grade: str) -> float | None:
    """Sort items by endedAt desc, filter by grade, average last 5 totalPrice."""
    if not items:
        return None
    # Filter to items with the right grade
    filtered = [
        it for it in items
        if _grade_in_title(it.get("title", ""), grade)
    ]
    if not filtered:
        # Fall back to unfiltered if grade filter wipes everything (rare)
        filtered = items
    # Sort by endedAt desc
    def key(it: dict):
        return it.get("endedAt", "")
    filtered.sort(key=key, reverse=True)
    # Take up to 5 most recent
    sample = filtered[:5]
    prices = []
    for it in sample:
        try:
            p = float(it.get("totalPrice") or it.get("soldPrice") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            prices.append(p)
    if not prices:
        return None
    return round(sum(prices) / len(prices), 2)


MAX_KEYWORDS_PER_RUN = 6  # Apify input schema cap


def _start_run(keywords: list[str], token: str) -> dict | None:
    body = json.dumps({
        "keywords": keywords,
        "daysToScrape": 60,
        "count": PRICE_PER_KEYWORD,
        "categoryId": "0",
        "ebaySite": "ebay.com",
        "sortOrder": "endedRecently",
        "itemLocation": "default",
        "itemCondition": "any",
        "detailedSearch": False,
    }).encode("utf-8")
    start_url = f"{API_BASE}/acts/{ACTOR_ID}/runs?token={token}"
    req = urllib.request.Request(
        start_url, method="POST", data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()).get("data", {})
    except urllib.error.HTTPError as e:
        print(f"[ebay] start failed HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")
        return None
    except Exception as e:
        print(f"[ebay] start failed: {e}")
        return None


def _fetch_dataset(dataset_id: str, token: str) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        ds_url = f"{API_BASE}/datasets/{dataset_id}/items?token={token}&offset={offset}&limit=1000"
        try:
            with urllib.request.urlopen(ds_url, timeout=60) as r:
                batch = json.loads(r.read())
        except Exception as e:
            print(f"[ebay] dataset fetch failed at offset={offset}: {e}")
            break
        if not batch:
            break
        items.extend(batch)
        offset += len(batch)
        if len(batch) < 1000:
            break
    return items


def fetch_apify(keywords: list[str], poll_interval: int = 15,
                max_wait: int = 1800) -> dict:
    """Chunks keywords into batches of <= 6 (actor input cap), starts all runs
    in parallel, then waits for each to finish and aggregates datasets.
    Returns {keyword: [item, ...]}. Returns {} on total failure."""
    token = get_token()
    if not token:
        print("[ebay] no APIFY_API_TOKEN")
        return {}

    # Chunk into batches of 6
    chunks: list[list[str]] = [
        keywords[i:i + MAX_KEYWORDS_PER_RUN]
        for i in range(0, len(keywords), MAX_KEYWORDS_PER_RUN)
    ]
    print(f"[ebay] {len(keywords)} keywords -> {len(chunks)} parallel runs (max {MAX_KEYWORDS_PER_RUN}/run)")

    # Start all runs
    runs: list[dict] = []
    for i, chunk in enumerate(chunks):
        run = _start_run(chunk, token)
        if run is None:
            print(f"[ebay] chunk {i+1} failed to start; skipping")
            continue
        runs.append({
            "id": run.get("id"),
            "dataset_id": run.get("defaultDatasetId"),
            "status": run.get("status", ""),
            "keywords": chunk,
            "chunk_idx": i,
        })
        print(f"[ebay] started run {i+1}/{len(chunks)} ({run.get('id')}) with {len(chunk)} kw")

    if not runs:
        print("[ebay] no runs started successfully")
        return {}

    # Poll each run; consider all done when all are in terminal state
    waited = 0
    pending = list(runs)
    while pending and waited < max_wait:
        time.sleep(poll_interval)
        waited += poll_interval
        still_pending = []
        for r in pending:
            try:
                status_url = f"{API_BASE}/actor-runs/{r['id']}?token={token}"
                with urllib.request.urlopen(status_url, timeout=30) as resp:
                    rd = json.loads(resp.read()).get("data", {})
                r["status"] = rd.get("status", "")
                if r["status"] not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                    still_pending.append(r)
            except Exception as e:
                print(f"[ebay] poll err for {r['id']}: {e}")
                still_pending.append(r)
        pending = still_pending
        n_done = len(runs) - len(pending)
        print(f"[ebay] {waited}s: {n_done}/{len(runs)} runs done")

    # Aggregate
    grouped: dict[str, list[dict]] = {}
    for r in runs:
        if r["status"] != "SUCCEEDED":
            print(f"[ebay] run {r['id']} ended status={r['status']} (chunk {r['chunk_idx']+1})")
            continue
        items = _fetch_dataset(r["dataset_id"], token)
        for it in items:
            kw = it.get("keyword", "")
            grouped.setdefault(kw, []).append(it)
    print(f"[ebay] aggregated dataset items across all runs: {sum(len(v) for v in grouped.values())}")
    return grouped


def fetch_or_cache(card_queries: dict[str, str]) -> dict[str, list[dict]]:
    """card_queries: {cert: keyword}. Returns {cert: [items]}.
    Reads cache first; only hits Apify for un-cached or stale entries."""
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
        print(f"[ebay] {len(out)} cached, {len(to_fetch)} need fetch")
        keywords = list(set(to_fetch.values()))
        grouped = fetch_apify(keywords)
        # Update cache
        for kw, items in grouped.items():
            cache[kw] = {"fetched_at": time.time(), "items": items}
        _save_cache(cache)
        # Map back to certs
        for cert, kw in to_fetch.items():
            out[cert] = grouped.get(kw, [])
    else:
        print(f"[ebay] all {len(out)} certs satisfied from cache")

    return out
