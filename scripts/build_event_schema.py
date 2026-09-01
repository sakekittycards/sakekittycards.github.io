# -*- coding: utf-8 -*-
"""Emit a STATIC Event JSON-LD block into events.html from assets/events-data.js.

WHY
---
events.html builds its Event schema in JavaScript from window.SK_EVENTS. Google
renders JS so it sees them, but Bing and most non-Google crawlers do not — so 19
real, dated, named-venue shows are invisible to everything except Google. Card
shows are exactly the kind of thing that earns an Event rich result for
"pokemon card show <city>", and it is legitimate geographic authority because
the events are real and verifiable, unlike a per-city doorway page.

NO DUPLICATION
--------------
The runtime script still generates its own (always-current) block. To avoid two
competing Event graphs on one page, the runtime block now REMOVES this static
node before inserting its own. So:
    no JS  -> static block serves, accurate as of the last build
    JS     -> static removed, fresh block inserted, always accurate

IDEMPOTENT
----------
The block is written between HTML comment fences. Re-running replaces the fenced
region exactly; it can never nest or accumulate. (This is the lesson from
build_shop_snapshot.py, which duplicated a whole catalog 56 -> 110 -> 164
because it matched on a non-greedy div instead of a fence.)

Only future-dated events are emitted, and masked "secret shows" are emitted with
their teaser name until revealAt has passed — never the real venue early.

    python scripts/build_event_schema.py [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS_JS = ROOT / 'assets' / 'events-data.js'
TARGET = ROOT / 'events.html'
SITE = 'https://sakekittycards.com/'
OPEN_FENCE = '  <!--EVENTSCHEMA:start-->'
CLOSE_FENCE = '  <!--EVENTSCHEMA:end-->'


def field(rec: str, key: str):
    m = re.search(key + r"\s*:\s*'((?:[^'\\]|\\.)*)'", rec)
    return m.group(1).replace("\\'", "'") if m else ''


def parse_events():
    src = EVENTS_JS.read_text(encoding='utf-8')
    body = src.split('window.SK_EVENTS', 1)[1]
    out = []
    for rec in re.findall(r'\{\s*start:.*?\}(?=,\s*\n|\s*\];)', body, re.S):
        e = {k: field(rec, k) for k in
             ('start', 'end', 'name', 'loc', 'hours', 'type', 'revealAt', 'realName', 'realLoc')}
        if e['start']:
            out.append(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    today = dt.date.today().isoformat()
    events = parse_events()
    nodes = []
    for e in events:
        end = e['end'] or e['start']
        if end < today:
            continue
        # Respect the reveal gate: a masked show keeps its teaser identity until
        # revealAt. Leaking a venue early would be worse than omitting the event.
        revealed = bool(e['revealAt']) and e['revealAt'] <= today
        name = (e['realName'] or e['name']) if revealed else e['name']
        loc = (e['realLoc'] or e['loc']) if revealed else e['loc']
        if not name or not loc:
            continue

        online = e['type'] == 'whatnot' or loc.strip().lower().startswith('online')
        node = {
            '@type': 'Event',
            'name': name,
            'startDate': e['start'],
            'endDate': end,
            'eventStatus': 'https://schema.org/EventScheduled',
            'eventAttendanceMode': ('https://schema.org/OnlineEventAttendanceMode' if online
                                    else 'https://schema.org/OfflineEventAttendanceMode'),
            'url': SITE + 'events.html',
            'organizer': {'@id': SITE + '#organization'},
            'performer': {'@id': SITE + '#organization'},
            'description': ('Sake Kitty Cards is vending at %s. Buying and selling Pokemon '
                            'cards, sealed product and graded slabs at the booth.' % name),
        }
        if online:
            node['location'] = {'@type': 'VirtualLocation', 'url': 'https://whatnot.com/invite/sakekittycards'}
        else:
            venue, _, addr = loc.partition('·')
            place = {'@type': 'Place', 'name': (venue.strip() or loc.strip())}
            addr = addr.strip() or loc.strip()
            if addr:
                place['address'] = {'@type': 'PostalAddress', 'streetAddress': addr,
                                    'addressCountry': 'US'}
                st = re.search(r',\s*([A-Z]{2})\s+\d{5}', addr) or re.search(r',\s*(FL|GA|NC|NV|CA|OH)\b', addr)
                if st:
                    place['address']['addressRegion'] = st.group(1)
                city = re.search(r'([A-Za-z .]+),\s*[A-Z]{2}\b', addr)
                if city:
                    place['address']['addressLocality'] = city.group(1).strip()
            node['location'] = place
        nodes.append(node)

    nodes.sort(key=lambda n: n['startDate'])
    payload = {'@context': 'https://schema.org', '@graph': nodes}
    block = (OPEN_FENCE + '\n'
             '  <!-- STATIC Event schema, generated by scripts/build_event_schema.py.\n'
             '       Exists so non-JS crawlers see our real show calendar. The runtime\n'
             '       builder below removes this node before inserting its own, so the\n'
             '       page never carries two Event graphs. Regenerate after editing\n'
             '       assets/events-data.js. -->\n'
             '  <script type="application/ld+json" id="staticEventSchema">\n'
             + json.dumps(payload, indent=2, ensure_ascii=False) + '\n'
             '  </script>\n' + CLOSE_FENCE)

    html = TARGET.read_text(encoding='utf-8')
    if OPEN_FENCE in html:
        start = html.index(OPEN_FENCE)
        stop = html.index(CLOSE_FENCE) + len(CLOSE_FENCE)
        new = html[:start] + block + html[stop:]
    else:
        anchor = '</head>'
        assert html.count(anchor) == 1, 'events.html: cannot locate a single </head>'
        new = html.replace(anchor, block + '\n' + anchor, 1)

    # never write something that isn't parseable
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', new, re.S):
        json.loads(m.group(1))
    assert new.rstrip().endswith('</html>')
    assert new.count(OPEN_FENCE) == 1 and new.count(CLOSE_FENCE) == 1

    print('upcoming events: %d  (of %d total records)' % (len(nodes), len(events)))
    for n in nodes[:5]:
        loc = n['location'].get('name', 'Online')
        print('   %s  %-38s %s' % (n['startDate'], n['name'][:38], loc[:40]))
    if len(nodes) > 5:
        print('   … and %d more' % (len(nodes) - 5))

    if args.dry_run:
        print('(dry run — events.html not written)')
        return
    tmp = str(TARGET) + '.tmp'
    Path(tmp).write_text(new, encoding='utf-8', newline='')
    os.replace(tmp, TARGET)
    print('events.html updated (%d bytes)' % len(new))


if __name__ == '__main__':
    main()
