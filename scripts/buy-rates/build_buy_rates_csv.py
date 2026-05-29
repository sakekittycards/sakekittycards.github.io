"""
Build a self-calculating Buy-Rates CSV for Sake Kitty Cards.

Open the output in Excel or Google Sheets: type a Category + Market Value + Qty
and the Cash / Credit offers auto-fill, with per-category subtotals + grand total.

Rates mirror trade-in.html (RATES tiered % + BULK_RATES flat per-card). Re-run
this if those change. Single sheet (CSV), so the rate tables live to the right
of the data-entry columns (H+) and row formulas reference them with absolute refs.
"""
import csv, os

# ── rates (from trade-in.html) ───────────────────────────────────────────────
# Shared value tiers for Singles/Sealed/Graded: (min$, cash%, credit%)
# Cash bumped +5 percentage points per user request 2026-05-26 (site shows the
# lower 65/75/80/85; this internal buy tool offers 70/80/85/90 cash).
TIERS = [(0, 0.70, 0.80), (100, 0.80, 0.90), (500, 0.85, 0.95), (1000, 0.90, 1.00)]
PCT_CATS = ["Singles", "Sealed", "Graded"]
# Flat per-card (or per-lb) bulk categories: (name, cash, credit)
BULK = [
    ("Unsorted Bulk (by weight)", 1.50, 2.50),   # per LB — put pounds in Qty/Lbs
    ("Common / Uncommon", 0.01, 0.01),
    ("Rare (Non-Holo)", 0.02, 0.03),
    ("Reverse Holo", 0.03, 0.05),
    ("Holo Rare", 0.05, 0.10),
    ("Holo Promo", 0.10, 0.15),
    ("EX or V", 0.15, 0.25),
    ("Radiant", 0.20, 0.30),
    ("GX", 0.35, 0.50),
    ("VMAX / VSTAR", 0.45, 0.65),
    ("Full Art", 0.50, 0.75),
    ("Amazing Rare", 0.70, 1.05),
    ("BREAK", 0.75, 1.10),
]
DATA_ROWS = 510            # supports up to ~500 cards
FIRST, LAST = 2, 1 + DATA_ROWS   # data rows 2..511

cells = {}   # (row, col0idx) -> string ; col 0=A,1=B,...,7=H,8=I,9=J,10=K
def put(r, c, v): cells[(r, c)] = v

# ── data-entry headers (A..F) ────────────────────────────────────────────────
for c, h in enumerate(["Category", "Item / Description", "Market Value $",
                       "Qty / Lbs", "Cash Offer", "Credit Offer"]):
    put(1, c, h)

# ── example rows (delete these) ──────────────────────────────────────────────
examples = [
    ("Singles", "EXAMPLE — Charizard (delete row)", "120", "1"),
    ("Sealed", "EXAMPLE — Evolving Skies Booster Box", "450", "1"),
    ("Holo Rare", "EXAMPLE — bulk holo rares", "", "50"),
    ("Unsorted Bulk (by weight)", "EXAMPLE — unsorted pile (pounds in Qty)", "", "10"),
]
for i, (cat, item, val, qty) in enumerate(examples):
    put(FIRST + i, 0, cat); put(FIRST + i, 1, item)
    put(FIRST + i, 2, val); put(FIRST + i, 3, qty)

# ── per-row offer formulas (E=cash col4, F=credit col5) for every data row ────
def cash(r):
    return (f'=IF($A{r}="","",IFERROR(IF(VLOOKUP($A{r},$H$9:$K$24,2,FALSE)="PCT",'
            f'IF(AND(LOWER($A{r})="graded",$C{r}<100),"NOT ACCEPTED (<$100)",'
            f'ROUND($C{r}*VLOOKUP($C{r},$H$3:$J$6,2,TRUE)*IF($D{r}="",1,$D{r}),2)),'
            f'ROUND(VLOOKUP($A{r},$H$9:$K$24,3,FALSE)*IF($D{r}="",1,$D{r}),2)),"check category"))')
def credit(r):
    return (f'=IF($A{r}="","",IFERROR(IF(VLOOKUP($A{r},$H$9:$K$24,2,FALSE)="PCT",'
            f'IF(AND(LOWER($A{r})="graded",$C{r}<100),"NOT ACCEPTED (<$100)",'
            f'ROUND($C{r}*VLOOKUP($C{r},$H$3:$J$6,3,TRUE)*IF($D{r}="",1,$D{r}),2)),'
            f'ROUND(VLOOKUP($A{r},$H$9:$K$24,4,FALSE)*IF($D{r}="",1,$D{r}),2)),"check category"))')
for r in range(FIRST, LAST + 1):
    put(r, 4, cash(r)); put(r, 5, credit(r))

# ── TIER RATES table (H1.. ; data H3:J6) ─────────────────────────────────────
put(1, 7, "◄ TIER RATES — Singles / Sealed / Graded (edit %s here)")
put(2, 7, "Min $"); put(2, 8, "Cash %"); put(2, 9, "Credit %")
for i, (mn, ca, cr) in enumerate(TIERS):
    put(3 + i, 7, mn); put(3 + i, 8, ca); put(3 + i, 9, cr)

# ── CATEGORY table (H8 header ; data H9:K24) ─────────────────────────────────
put(8, 7, "CATEGORY (type exactly)"); put(8, 8, "Type")
put(8, 9, "Flat Cash $"); put(8, 10, "Flat Credit $")
catrow = 9
for name in PCT_CATS:
    put(catrow, 7, name); put(catrow, 8, "PCT"); catrow += 1
for name, ca, cr in BULK:
    put(catrow, 7, name); put(catrow, 8, "FLAT")
    put(catrow, 9, ca); put(catrow, 10, cr); catrow += 1   # ends at 24

# ── SUMMARY (per-category subtotals + grand total) ───────────────────────────
put(27, 7, "SUMMARY — per category")
put(28, 7, "Category"); put(28, 8, "Cash Total"); put(28, 9, "Credit Total"); put(28, 10, "Lines")
all_cats = PCT_CATS + [b[0] for b in BULK]
srow = 29
for name in all_cats:
    put(srow, 7, name)
    put(srow, 8, f'=ROUND(SUMIF($A$2:$A$511,$H{srow},$E$2:$E$511),2)')
    put(srow, 9, f'=ROUND(SUMIF($A$2:$A$511,$H{srow},$F$2:$F$511),2)')
    put(srow, 10, f'=COUNTIF($A$2:$A$511,$H{srow})')
    srow += 1
put(srow, 7, "GRAND TOTAL")
put(srow, 8, '=ROUND(SUM($E$2:$E$511),2)')
put(srow, 9, '=ROUND(SUM($F$2:$F$511),2)')
put(srow, 10, '=COUNTA($A$2:$A$511)')

# ── HOW TO USE notes ─────────────────────────────────────────────────────────
notes = [
    "HOW TO USE",
    "1. Category: type one EXACTLY as listed above (case doesn't matter). In Google",
    "   Sheets you can add a dropdown: select column A > Data > Data validation >",
    "   list from range H9:H24.",
    "2. Singles / Sealed / Graded: enter Market Value $ in column C. Qty in D (blank = 1).",
    "3. Bulk categories: leave Value blank, put the # of cards in Qty (column D).",
    "4. Unsorted Bulk (by weight): put POUNDS in the Qty/Lbs column.",
    "5. Cash & Credit auto-fill. Graded under $100 shows NOT ACCEPTED.",
    "6. Edit any number in the TIER or CATEGORY tables and everything recalculates.",
]
nrow = srow + 2
for i, line in enumerate(notes):
    put(nrow + i, 7, line)

# ── emit ─────────────────────────────────────────────────────────────────────
max_row = max(r for r, _ in cells)
max_col = max(c for _, c in cells)
out = os.environ.get("OUT", r"C:\Users\lunar\OneDrive\Desktop\Buy_Rates_Calculator.csv")
with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    for r in range(1, max_row + 1):
        w.writerow([cells.get((r, c), "") for c in range(max_col + 1)])
print("wrote", out, f"({max_row} rows x {max_col+1} cols)")
