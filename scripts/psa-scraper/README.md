# Sake Kitty Cards — PSA Status Scraper

Logs into Collectors.com with your PSA account, scrapes the status of every submission, and updates the Airtable `Submissions` table so customers' trackers on the site reflect the latest PSA progress.

Runs on your Windows desktop via a scheduled task. Requires your computer to be on for the scraper to update — if you turn off the machine for a weekend, updates pause until it's back on.

## What's here

```
scripts/psa-scraper/
  scraper.mjs      — main script (currently in discovery mode)
  package.json     — npm deps (just playwright)
  .env.example     — credential template
  .env             — YOUR ACTUAL CREDS (not committed — in .gitignore)
  discovery/       — screenshots + HTML saved during first run
```

## Status: v0.1 — discovery mode

Right now the script only logs in and saves screenshots + HTML of the pages it lands on. I need you to run it once and send me the output of `./discovery/` so I can see what Collectors.com's submission dashboard looks like for your account. Then I'll write v1 that actually parses statuses and updates Airtable.

## One-time setup

All commands are from inside `scripts/psa-scraper/`.

1. **Install Node.js 20 or later** (if not already installed):
   - https://nodejs.org/ → LTS installer
   - Restart your terminal after install

2. **Install dependencies** (this also installs a headless Chromium via Playwright — ~200 MB):
   ```
   npm install
   ```

3. **Create your `.env` file**:
   ```
   copy .env.example .env
   ```
   Then open `.env` in any text editor and fill in:
   - `PSA_EMAIL` — your Collectors.com login email
   - `PSA_PASSWORD` — your Collectors.com password
   - `AIRTABLE_TOKEN` — the pat... token from Airtable
   - `AIRTABLE_BASE_ID` — already filled in
   - `AIRTABLE_TABLE_ID` — already filled in

## Run it (discovery mode)

```
npm run discover
```

This will:
1. Launch a headless Chrome
2. Navigate to the PSA login flow
3. Log in with your credentials
4. Try to find your submissions dashboard
5. Save a screenshot + HTML of every page it lands on to `./discovery/`

Should take ~30–60 seconds. When it finishes, zip up the `./discovery/` folder and send it to me, or just send me the screenshots.

## Debug mode (visible browser)

If you want to watch the script drive a real Chrome window (useful if something breaks):

```
npm run debug
```

Same flow, but with a visible browser and slow motion so you can see each step.

## Scheduling it (future — after v1 is working)

Once v1 is complete, we'll register a Windows Scheduled Task to run `npm start` every 6 hours. I'll send you the PowerShell one-liner when we get there.

## Safety notes

- `.env` is in `.gitignore` and never committed
- Playwright only talks to the sites the script explicitly navigates to
- The scraper never touches anything outside the "My Submissions" pages — it does not have the ability to change your address, place orders, or modify your PSA account settings
- If Collectors.com ever prompts for 2FA mid-session, the scraper will fail and log the page HTML — it will not attempt to bypass 2FA
