# Sake Kitty Cards — invoice system

Generates branded, print-ready customer invoices for card evaluation, preparation
and PSA grading services.

Built on the **same document system as `sk-wholesale-terms.html`** (the Sake Kitty
Wholesale term sheet): Spectral / Public Sans / JetBrains Mono, warm paper, editorial
hairline rules, mono eyebrows, left-bordered notes. What changes on the retail side is
the accent layer — the Sake Kitty **Cards** palette (gold, burnt orange, magenta,
cobalt, azure) in place of the wholesale teal — and the masthead carries the original
Cards logo. Put the two documents side by side and they read as one house style.

## Run it

```bash
python scripts/invoices/render_invoice.py scripts/invoices/data/joe-carter.json
python scripts/invoices/render_invoice.py --all          # every data/*.json
python scripts/invoices/render_invoice.py data/x.json --html   # keep the HTML too
```

PDFs land in `out/`. Needs `jinja2`, `playwright` (chromium), `pillow`, `pypdf` —
all already present in this environment.

## New invoice

1. Copy `data/_template.json` to `data/<customer>.json`.
2. Fill in customer, service quantities, the card list and `expect`.
3. Render. Fix whatever it complains about. Done.

Everything a new customer needs is in that one JSON file — name, email, date, invoice
number, card list, quantities, PSA fees, evaluation and preparation charges, shipping,
notes, and whether the document is still preliminary. Layout and styling never move.

## How it is put together

| File | Owns |
|---|---|
| `data/*.json` | one invoice's **content** — nothing else |
| `templates/invoice.html.j2` | **layout** — block macros, page composition |
| `templates/invoice.css` | **styling** — the shared design system |
| `render_invoice.py` | computes the money, renders, and verifies |

**Page composition is data-driven.** `layout.pages` is a list of pages, each naming
the blocks it carries:

```json
"pages": [
  { "blocks": ["masthead", "docline", "services", "summary", "submission_notes"] },
  { "blocks": ["conthead", "grading", "terms"] }
]
```

Available blocks: `masthead`, `conthead` (compact header for later pages), `docline`
(billed-to / prepared-by / invoice meta), `services`, `grading`, `summary`,
`submission_notes`, `terms`. Move a block between pages by editing that list — no
template edits.

## The money is computed, never transcribed

`render_invoice.py` adds up the line items itself. Each data file also carries an
`expect` block, and **the renderer refuses to emit a PDF when the two disagree**:

```json
"expect": { "service_fees": 140.00, "psa_fees": 1249.00, "total": 1389.00,
            "evaluated_cards": 25, "submitted_cards": 13 }
```

So editing a card's fee without updating the quoted total is a hard error, not a
silently wrong invoice. It also checks that a per-card service row's quantity matches
the number of cards actually listed, and rejects duplicate cards.

Four gates run on every render:

1. **Math** — computed figures vs `expect`.
2. **Duplicates** — no card listed twice (name + number + set).
3. **Overflow** — `.sheet` clips its overflow, so a page one row too long would
   silently lose content. The renderer measures the last element's bottom edge against
   the page's content box and refuses to produce a clipped PDF. If it complains, move a
   block to the next page rather than shrinking type.
4. **PDF text** — the finished PDF is read back and checked: page count matches the
   declared layout, every card appears exactly once, and the three key figures are
   present on the page.

## Conventions worth keeping

- **Pass-through is stated plainly.** Sake Kitty's own revenue and the PSA charge are
  separated in the summary — coloured dots, an uppercase attribution under each line,
  and a sentence naming both figures. Do not merge them into one number.
- **"Estimated total" is before shipping.** `shipping.amount: null` renders `TBD` and
  stays out of the total. Put a number there for the final invoice and it is added in.
- Card Prep is **penny sleeve + card saver**, never top loaders.
- Do not claim an insurance policy, PSA-authorized dealer status, a specific insured
  amount, that anything has shipped, or any grading outcome. The stock Customer notes
  are written to stay on the right side of all of that.
- Customer-facing contact is always `nick@sakekittycards.com`.
- The logo is read from the repo root (`logo-transparent.png`), downscaled in memory
  and never modified. Square aspect is preserved. Do not substitute the Wholesale mark.

## Fonts and the network

The template links Google Fonts, exactly as `sk-wholesale-terms.html` does. Rendering
offline still works but falls back to Georgia / Segoe UI, which changes the look —
render with a connection.

## Privacy

**This repo is public** — GitHub Pages serves everything committed to it. `.gitignore`
in this folder keeps `data/*.json` (customer names and emails) and `out/` (the PDFs)
out of git. The tool itself is committed; the customer data is not. Leave that alone.
