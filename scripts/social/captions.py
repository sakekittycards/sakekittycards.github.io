# -*- coding: utf-8 -*-
"""Caption generation.

Deterministic templates filled from structured event data. No language model
touches a caption, for the same reason no language model renders text onto a
graphic: a caption states a date, a venue and a booth number, and those have to
be right rather than plausible.

## The voice

The rule for every customer-facing Sake Kitty artifact is that it reads like
Nick talking to a collector he respects. Concretely, and enforced by
`self_check()` below:

  - useful information first: show, day, place, time. Not a greeting.
  - specifics instead of adjectives. "PSA 10 Charizard" beats "amazing cards".
  - no manufactured urgency, no "we're thrilled to announce", no emoji walls,
    no engagement bait, no exclamation stacks.
  - services mentioned only when they apply.
  - a small deliberate hashtag set, not thirty.

`self_check()` runs on every generated caption and returns findings that ride
along to the console as warnings. It is a lint, not a filter — a human still
reads the caption before it goes out — but it makes a drifting template loud.
"""
from __future__ import annotations

import re
from datetime import date, datetime

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Phrases that mark copy as generic marketing rather than a dealer talking.
# Every one of these has appeared in real automated captions somewhere.
SLOP = [
    "we're thrilled", "we are thrilled", "we're excited to announce", "excited to announce",
    "don't miss out", "dont miss out", "last chance", "act now", "hurry",
    "amazing deals", "incredible deals", "unbeatable", "must-see", "must see",
    "swipe up", "link in bio for more", "tag a friend who", "double tap if",
    "who else", "drop a", "comment below", "let us know in the comments",
    "stay tuned for more", "you won't believe", "you wont believe", "game changer",
    "one of a kind deals", "epic", "insane deals",
]


def _fmt_date(iso: str) -> tuple[str, str]:
    d = date.fromisoformat(iso)
    return DAYS[d.weekday()], f"{MONTHS[d.month - 1]} {d.day}"


def _date_line(ev: dict) -> str:
    """One human line for a single day or a multi-day run."""
    dow, md = _fmt_date(ev["event_date"])
    if not ev.get("end_date") or ev["end_date"] == ev["event_date"]:
        return f"{dow}, {md}"
    d1 = date.fromisoformat(ev["event_date"])
    d2 = date.fromisoformat(ev["end_date"])
    if d1.month == d2.month:
        return f"{MONTHS[d1.month - 1]} {d1.day}–{d2.day}"
    return f"{MONTHS[d1.month - 1]} {d1.day} – {MONTHS[d2.month - 1]} {d2.day}"


def place_line(ev: dict) -> str:
    """Venue and city, without repeating a city that is already in the venue."""
    venue = (ev.get("venue") or "").strip()
    city = (ev.get("city") or "").strip()
    state = (ev.get("state") or "").strip()
    where = f"{city}, {state}" if city and state else (city or state)
    if venue and where and city.lower() not in venue.lower():
        return f"{venue} · {where}"
    return venue or where


def _opening(kind: str, ev: dict) -> str:
    """The first line. It says what is happening and when, and nothing else."""
    title = ev["title"]
    dow, md = _fmt_date(ev["event_date"])
    multi = bool(ev.get("end_date")) and ev["end_date"] != ev["event_date"]

    if kind == "ANNOUNCEMENT":
        if multi:
            return f"We're set up at {title}, {_date_line(ev)}."
        return f"We're at {title} on {dow}, {md}."
    if kind == "UPCOMING":
        return f"{title} is a week out — we'll be there {_date_line(ev)}."
    if kind == "THIS_WEEKEND":
        if multi:
            return f"This weekend: {title}, {_date_line(ev)}."
        return f"{title} is this {dow}. We'll have a table."
    if kind == "DAY_OF":
        return f"Doors are open at {title} today."
    return f"We're at {title} on {dow}, {md}."


def _services(policy_services: dict, ev: dict) -> list[str]:
    """What people can actually do with us at this show.

    Grading prep is deliberately omitted from online streams — the service is a
    hand-off of physical cards, and offering it on a Whatnot post would be a
    promise we cannot keep.
    """
    s = policy_services or {}
    online = ev.get("kind") == "online"
    lines = []
    if s.get("buy") or s.get("sell") or s.get("trade"):
        lines.append("Bring cards to sell or trade — singles, sealed and slabs."
                     if not online else "Buying and trading in chat all stream.")
    if s.get("collections") and not online:
        lines.append("Whole collections welcome; bring them and we'll go through them with you.")
    if s.get("grading_prep") and not online:
        lines.append("We also screen cards for PSA, CGC and Beckett submissions.")
    return lines


def build(ev: dict, kind: str, policy: dict | None = None,
          booth: str | None = None) -> dict:
    """Return {caption, hashtags, warnings} for one event opportunity."""
    policy = policy or {}
    lines: list[str] = [_opening(kind, ev)]

    facts = []
    place = place_line(ev)
    if place:
        facts.append(f"📍 {place}")
    facts.append(f"🗓 {_date_line(ev)}")
    if ev.get("hours_text"):
        facts.append(f"🕙 {ev['hours_text']}")
    booth = booth or ev.get("booth")
    if booth:
        facts.append(f"🎪 {booth}")
    lines.append("")
    lines.extend(facts)

    svc = _services(policy.get("services", {}), ev)
    if svc:
        lines.append("")
        lines.extend(svc)

    if kind in ("THIS_WEEKEND", "DAY_OF") and not booth:
        lines.append("")
        lines.append("Come say hi — we're easy to find, look for the cat.")

    tags = list((policy.get("hashtags", {}) or {}).get("event", []))
    city = (ev.get("city") or "").strip()
    if city:
        # One geo tag, from the actual city. It is the only tag worth adding
        # per-post: someone searching a city tag is nearby and can walk over.
        tags.append("#" + re.sub(r"[^a-z0-9]", "", city.lower()))
    cap = (policy.get("hashtags", {}) or {}).get("max", 6)
    tags = tags[:cap]

    caption = "\n".join(lines).strip()
    return {"caption": caption, "hashtags": tags, "warnings": self_check(caption, tags)}


def build_reel(video_title: str, note: str | None = None,
               policy: dict | None = None) -> dict:
    """A starting caption for an approved short.

    Deliberately thin. The video carries the story; a caption that narrates it
    reads as a description of a joke. What the draft supplies is the plain title
    and the standing context, and a human writes the rest — which is why the
    console opens the caption field for reels rather than presenting it as done.
    """
    policy = policy or {}
    lines = [video_title.strip()]
    if note:
        lines += ["", note.strip()]
    lines += ["", "Florida card shows most weekends — buying, selling and trading at the booth."]
    tags = list((policy.get("hashtags", {}) or {}).get("reel", []))
    caption = "\n".join(lines).strip()
    return {"caption": caption, "hashtags": tags, "warnings": self_check(caption, tags)}


def self_check(caption: str, hashtags: list[str]) -> list[str]:
    """Lint a caption against the house voice. Returns human-readable findings."""
    out: list[str] = []
    low = caption.lower()

    for phrase in SLOP:
        if phrase in low:
            out.append(f'reads as marketing copy: "{phrase}"')

    if caption.count("!") > 1:
        out.append(f"{caption.count('!')} exclamation marks — one is plenty")

    emoji = len(re.findall(
        r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]", caption))
    if emoji > 5:
        out.append(f"{emoji} emoji — the fact lines want one each, not a wall")

    if len(hashtags) > 8:
        out.append(f"{len(hashtags)} hashtags — keep it under 8")

    if re.search(r"\?\s*$", caption.strip()) and "?" in caption:
        out.append("ends on a question — engagement bait reads as a bot")

    first = caption.strip().split("\n")[0].lower()
    if first.startswith(("hey ", "hi ", "hello", "attention", "guess what")):
        out.append("opens with a greeting instead of the news")

    if len(caption) > 2200:
        out.append(f"{len(caption)} characters — over Instagram's 2200 limit")

    # A caption for an event that states no date is the failure that matters.
    if not re.search(r"\b(" + "|".join(MONTHS) + r")\b", caption) \
            and not re.search(r"\btoday\b", low):
        out.append("no date in the caption")

    return out
