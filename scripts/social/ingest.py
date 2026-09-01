# -*- coding: utf-8 -*-
"""Read the website's event calendar and hand it to the social engine.

`assets/events-data.js` stays the source of truth. Nick adds a show by editing
that file, exactly as he does today; nothing here ever writes back to it.

The file is JavaScript, not data, so it is parsed rather than imported: a
`window.SK_EVENTS = [ ... ];` array of object literals with unquoted keys. A
regex over the whole file would be fragile, so this walks the array
bracket-by-bracket and then parses each object literal properly.

The interesting work is splitting the site's single `loc` string:

    "The Flagler · 201 SW Flagler Ave, Stuart, FL 34994"
     ^venue        ^address          ^city  ^state

into the fields a graphic needs. The site is free-form on purpose — it renders
`loc` as one line — so this is a best-effort parse whose failures are visible
(the `--check` mode prints every row it could not fully split) rather than
silent.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime

# Windows consoles default to cp1252, and several show names carry emoji or an
# en dash. Without this the script dies on its own progress output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
EVENTS_JS = os.path.join(REPO, "assets", "events-data.js")

# The site writes hours as free text: "10am–5pm", "Sat 10am–6pm · Sun 10am–5pm",
# "10am–4pm (VIP early access 9am)". Only a leading simple range is safe to turn
# into machine times; anything else stays as display text and no start/end is
# claimed. Guessing here would put a wrong time on a graphic.
_SIMPLE_HOURS = re.compile(
    r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*[–\-—]\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*$",
    re.I,
)

_STATE = re.compile(r"\b([A-Z]{2})\b(?:\s+\d{5}(?:-\d{4})?)?\s*$")


def extract_array(js_text: str) -> str:
    """Return the bracketed array literal assigned to window.SK_EVENTS."""
    start = js_text.index("window.SK_EVENTS")
    start = js_text.index("[", start)
    depth = 0
    in_str = None
    i = start
    while i < len(js_text):
        ch = js_text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in "'\"":
            in_str = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return js_text[start:i + 1]
        i += 1
    raise ValueError("events-data.js: unterminated SK_EVENTS array")


def split_objects(array_src: str) -> list[str]:
    """Split the array body into top-level `{...}` object literals."""
    out, depth, buf, in_str = [], 0, [], None
    for i, ch in enumerate(array_src[1:-1]):
        if in_str:
            buf.append(ch)
            if ch == in_str and array_src[i] != "\\":
                in_str = None
            continue
        if ch in "'\"":
            in_str = ch
            buf.append(ch)
            continue
        if ch == "{":
            depth += 1
        if depth:
            buf.append(ch)
        if ch == "}":
            depth -= 1
            if depth == 0:
                out.append("".join(buf))
                buf = []
    return out


_KEY = re.compile(r"([{,]\s*)([A-Za-z_$][\w$]*)\s*:")


def parse_object(src: str) -> dict:
    """Turn a JS object literal into a dict: quote the keys, then use json."""
    j = _KEY.sub(lambda m: f'{m.group(1)}"{m.group(2)}":', src)
    j = re.sub(r",\s*}", "}", j)
    # Single-quoted JS strings -> double-quoted JSON. Escape any inner quote
    # first so a venue like "The Flagler" survives.
    def requote(m):
        body = m.group(1).replace('\\"', '"').replace('"', '\\"').replace("\\'", "'")
        return f'"{body}"'
    j = re.sub(r"'((?:[^'\\]|\\.)*)'", requote, j)
    return json.loads(j)


def parse_hours(text: str) -> tuple[str | None, str | None]:
    m = _SIMPLE_HOURS.match(text or "")
    if not m:
        return None, None
    h1, m1, ap1, h2, m2, ap2 = m.groups()
    return _to24(h1, m1, ap1), _to24(h2, m2, ap2)


def _to24(h, mm, ap):
    h = int(h) % 12
    if ap.lower() == "pm":
        h += 12
    return f"{h:02d}:{int(mm or 0):02d}"


def split_loc(loc: str) -> dict:
    """Best-effort venue / address / city / state from the site's `loc` string."""
    loc = (loc or "").strip()
    out = {"venue": "", "address": "", "city": "", "state": ""}
    if not loc:
        return out
    if loc.lower() in ("online", "location revealed soon"):
        out["venue"] = loc
        return out

    # "Venue · rest" is the site's own convention; the middle dot is reliable.
    if "·" in loc:
        venue, rest = loc.split("·", 1)
        out["venue"] = venue.strip()
    else:
        venue, rest = "", loc

    rest = rest.strip()
    m = _STATE.search(rest)
    if m:
        out["state"] = m.group(1)
        rest = rest[:m.start()].rstrip().rstrip(",")

    parts = [p.strip() for p in rest.split(",") if p.strip()]
    if not out["venue"] and parts:
        # No middle dot: either "Venue, City" or just "City".
        if len(parts) >= 2:
            out["venue"] = parts[0]
            out["city"] = parts[-1]
            out["address"] = ", ".join(parts[1:-1])
        else:
            out["city"] = parts[0]
    elif parts:
        out["city"] = parts[-1]
        out["address"] = ", ".join(parts[:-1])
    return out


def is_online(ev: dict) -> bool:
    return ev.get("type") == "whatnot" or (ev.get("loc") or "").strip().lower().startswith("online")


def normalize(raw: dict) -> dict:
    """One site event -> the engine's normalized shape.

    Masked events keep the TEASER name and location. The reveal is the website's
    decision; the engine records the mask and refuses to promote until the site
    itself would have shown the real name.
    """
    masked = bool(raw.get("revealAt"))
    loc = split_loc(raw.get("loc", ""))
    hours = raw.get("hours") or ""
    start_t, end_t = parse_hours(hours)

    return {
        "title": raw.get("name", "").strip(),
        "venue": loc["venue"],
        "address": loc["address"],
        "city": loc["city"],
        "state": loc["state"],
        "event_date": raw.get("start", ""),
        "end_date": raw.get("end") or None,
        "start_time": start_t,
        "end_time": end_t,
        "hours_text": hours or None,
        "kind": "online" if is_online(raw) else "show",
        "masked": masked,
        "reveal_at": raw.get("revealAt"),
        "status": "scheduled",
        "website_url": "https://sakekittycards.com/events",
    }


def load_events(path: str = EVENTS_JS) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return [parse_object(o) for o in split_objects(extract_array(text))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="parse and report only; do not contact the worker")
    ap.add_argument("--json", action="store_true", help="print the normalized payload")
    ap.add_argument("--upcoming-only", action="store_true",
                    help="send only events that have not finished yet")
    args = ap.parse_args()

    raws = load_events()
    normalized = [normalize(r) for r in raws]

    if args.upcoming_only:
        today = date.today().isoformat()
        normalized = [e for e in normalized
                      if (e["end_date"] or e["event_date"]) >= today]

    if args.json:
        print(json.dumps(normalized, indent=2, ensure_ascii=False))
        return 0

    print(f"parsed {len(raws)} events from {os.path.relpath(EVENTS_JS, REPO)}")

    gaps = [e for e in normalized if not e["city"] and e["kind"] == "show"]
    if gaps:
        print(f"\n{len(gaps)} event(s) with no city parsed from `loc` — a graphic for these")
        print("will show the venue line only:")
        for e in gaps:
            print(f"  {e['event_date']}  {e['title']!r}  venue={e['venue']!r}")

    masked = [e for e in normalized if e["masked"]]
    if masked:
        print(f"\n{len(masked)} masked teaser event(s) — not promotable until their reveal date:")
        for e in masked:
            print(f"  {e['event_date']}  {e['title']}  reveals {e['reveal_at']}")

    if args.check:
        return 0

    from client import Client
    c = Client()
    res = c.post("/events/ingest", {"events": normalized})
    ev = res["events"]
    print(f"\ningested: {len(ev['added'])} new · {len(ev['updated'])} updated "
          f"({len(ev['material'])} materially) · {len(ev.get('renamed', []))} renamed "
          f"· {len(ev['cancelled'])} cancelled · {ev['unchanged']} unchanged")
    for rn in ev.get('renamed', []):
        print(f"  ~ RENAMED: {rn['from']!r} -> {rn['to']!r} (kept its history)")
    for eid in ev["added"]:
        print(f"  + {eid}")
    for m in ev["material"]:
        fields = ", ".join(c["field"] for c in m["changed"])
        print(f"  ~ {m['id']} changed: {fields}")
    for eid in ev["cancelled"]:
        print(f"  ! {eid} CANCELLED")
    opp = res["opportunities"]
    print(f"opportunities: +{opp['created']} created · {opp['retired']} retired "
          f"· {opp['expired']} expired · {opp['skipped']} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
