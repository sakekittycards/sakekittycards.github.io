# scripts/social — the local content agent

Renders the graphics, probes the videos, writes the captions, and files drafts
with the [`sakekitty-social`](../../workers/social/README.md) worker.

**This half decides nothing.** It never approves, never schedules and never
publishes — the worker owns all three. That split is why the machine being
switched off delays content instead of losing it, and why running any of these
twice produces the same drafts rather than duplicates.

## Setup

The admin token is read from a file, never a command-line argument (an argument
lands in shell history and the process table):

```sh
# 1st choice
echo "<the worker's ADMIN_TOKEN>" > ~/.claude/sk_social_admin_token.txt
# or, per-shell
export SK_SOCIAL_TOKEN=...
export SK_SOCIAL_BASE=http://127.0.0.1:8799   # to talk to a local wrangler dev
```

Fonts (Bangers + Inter) are vendored in `fonts/` so a render is reproducible on
any machine. Needs Pillow and numpy; `video.py` needs ffprobe.

## Daily use

```sh
python run.py                    # ingest + render + draft, one pass
python run.py --dry-run          # render and print captions, upload nothing
python run.py --flyers           # try the organizer's own artwork first
python run.py --canvas story     # 1080x1920 instead of 1080x1350
```

Then open `social.html` and approve what you want to go out.

## Events

```sh
python ingest.py --check         # parse only; reports every row it could not fully split
python ingest.py --json          # print the normalized payload
python ingest.py                 # send it to the worker
```

`assets/events-data.js` stays the source of truth — this only reads it. The
parser walks the `window.SK_EVENTS` array literal and splits the site's free-form
`loc` string ("The Flagler · 201 SW Flagler Ave, Stuart, FL 34994") into venue /
address / city / state. `--check` prints anything it could not split so a bad
graphic is caught before it is rendered, not after.

## Video

```sh
python video.py scan             # probe + SHA-256 + register everything
python video.py scan --dry-run   # see what it would find, no token needed
python video.py list --state REVIEW
python video.py show <id>        # probe, compatibility, full approval history
python video.py approve <id> --by nick --note "upload ready"
python video.py reject  <id> --by nick --reason "no turn"
python video.py deliver <id>     # upload the approved bytes for Instagram to fetch
```

**`scan` never approves anything.** Not for any folder, not for any filename, not
for a render that finished cleanly. Everything lands in `REVIEW`.

That is not caution for its own sake. Until 2026-08-31 the pipeline had a
`_staging/` folder meaning "awaiting Nick" and a root meaning "shipped"; on 8/31
the staging step was removed and builds started landing directly in the root. So
`SHORT FORM FINAL/` now holds approved, unreviewed and killed shorts together,
and anything reading approval off the path would have been wrong from that day.

`_archive/` and `_rejected_qc/` are skipped entirely — those record a decision,
and it was "no".

`approve` sends the hash of the bytes it just displayed. If the file changed
between the print and the call, the worker refuses rather than approving
different bytes. Re-rendering an approved short drops its approval automatically
on the next `scan` and pulls any queued post off the calendar.

## Design

```sh
python preview.py                # contact sheet, 4:5
python preview.py --canvas story --out ./out
```

`preview.py` deliberately samples the hard cases from the real calendar — the
longest show name, a cross-month multi-day run, an online stream, a show with no
venue — because those are where a layout breaks, not the easy one.

- `sk_brand.py` — palette sampled from the mascot, glyph-by-glyph tracking
  (Pillow has no letter-spacing), full-canvas glows, mascot placement rules.
- `templates.py` — `banner` (default), `flyer` (organizer artwork as hero, never
  cropped into), `photo` (booth shot as hero).
- `captions.py` — deterministic templates plus `self_check()`, which lints every
  caption against the house voice and rides the findings along to the console as
  warnings.

No generative model renders text on a graphic and none is asked what an event is
called. A show name, a date and a venue are facts; a model that is 90% right
about a venue is 100% wrong on the one post that matters.

## Flyers

`flyer.py` is a resolver chain, not a scraper: an attached `flyer_url`, then our
own stored copy, then the event page's own OpenGraph image, then the organizer
site's. Every source requires a URL that came from the event itself.

There is deliberately **no image-search step**. Reposting a search result means
reposting whatever a stranger uploaded, including other dealers' photos and
licensed art. Returning nothing is a good outcome — it means we generate our own
graphic, which we know is ours. Validation (https only, no off-host redirect,
declared image type, size floor) and provenance recording happen worker-side.
