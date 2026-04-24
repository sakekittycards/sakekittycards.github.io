#!/usr/bin/env node
// Sake Kitty Cards — PSA status scraper
//
// v0.1: discovery mode only. Logs into Collectors.com using the creds in .env,
// navigates to the user's PSA submission dashboard, and saves a screenshot +
// the page HTML to ./discovery/. You send me the screenshot + HTML and I
// write v1 with accurate selectors that parse statuses and update Airtable.
//
// Usage:
//   npm install          (one-time)
//   npm run discover     (first run — saves page artifacts)
//   npm start            (future: full scrape + Airtable update)
//   npm run debug        (opens a visible browser so you can watch it drive)

import { chromium } from 'playwright';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DISCOVERY_DIR = resolve(__dirname, 'discovery');

// ─── .env parsing (tiny inline loader — no dotenv dependency) ─────────────
function loadEnv() {
  const envPath = resolve(__dirname, '.env');
  if (!existsSync(envPath)) {
    console.error('✗ .env not found. Copy .env.example to .env and fill in your credentials.');
    process.exit(1);
  }
  const lines = readFileSync(envPath, 'utf8').split(/\r?\n/);
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq < 0) continue;
    const key = line.slice(0, eq).trim();
    let val = line.slice(eq + 1).trim();
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (!process.env[key]) process.env[key] = val;
  }
}

loadEnv();

const args = process.argv.slice(2);
const MODE_DISCOVERY = args.includes('--discover');
const MODE_DEBUG     = args.includes('--debug') || process.env.HEADFUL === '1';

// ─── Checks ────────────────────────────────────────────────────────────────

function requireEnv(key) {
  const v = process.env[key];
  if (!v) {
    console.error(`✗ Missing env var: ${key}`);
    process.exit(1);
  }
  return v;
}

const PSA_EMAIL    = requireEnv('PSA_EMAIL');
const PSA_PASSWORD = requireEnv('PSA_PASSWORD');

// ─── Main ──────────────────────────────────────────────────────────────────

async function main() {
  console.log('Launching browser…');
  const browser = await chromium.launch({
    headless: !MODE_DEBUG,
    slowMo: MODE_DEBUG ? 200 : 0,
  });
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 900 },
  });
  const page = await context.newPage();

  try {
    // Step 1 — navigate to the PSA login entry point.
    //   https://www.psacard.com/myaccount 307s → Collectors.com signin.
    console.log('Opening login page…');
    await page.goto('https://www.psacard.com/myaccount', { waitUntil: 'domcontentloaded', timeout: 30_000 });

    // Wait for Collectors.com signin form to render. The page is Next.js so
    // the email input is the first thing that appears.
    await page.waitForSelector('input[type="email"], input[name="email"]', { timeout: 20_000 });
    console.log('Login form ready. Filling credentials…');

    await page.fill('input[type="email"], input[name="email"]', PSA_EMAIL);

    // Some Collectors flows are two-step (email → next → password). Try to
    // click a Next/Continue button if present, then wait for the password
    // field. If password field is already visible, skip this step.
    const passwordVisible = await page.locator('input[type="password"]').count();
    if (!passwordVisible) {
      const nextBtn = page.locator('button:has-text("Next"), button:has-text("Continue"), button[type="submit"]').first();
      if (await nextBtn.count()) {
        await nextBtn.click();
        await page.waitForSelector('input[type="password"]', { timeout: 20_000 });
      }
    }

    await page.fill('input[type="password"]', PSA_PASSWORD);

    // Submit. Try dedicated submit button, fall back to Enter key.
    const submitBtn = page.locator('button[type="submit"], button:has-text("Sign in"), button:has-text("Log in")').first();
    if (await submitBtn.count()) {
      await Promise.all([
        page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {}),
        submitBtn.click(),
      ]);
    } else {
      await page.keyboard.press('Enter');
      await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
    }

    // Heuristic: if we end up on a /signin page after submit, login failed.
    const postLoginUrl = page.url();
    if (/\/signin/.test(postLoginUrl) || /\/login/.test(postLoginUrl)) {
      // Could be 2FA prompt or bad credentials. Save the page so we can see.
      await saveArtifacts(page, 'login-stuck');
      throw new Error(`Login didn't leave the signin page. Ended up at: ${postLoginUrl}. See discovery/login-stuck-*.`);
    }

    console.log(`Login succeeded. Landed on: ${postLoginUrl}`);

    // Step 2 — try to find the PSA submission dashboard. Collectors likely
    // puts this under /dashboard, /orders, or /submissions. We'll try the
    // common paths and save whatever we land on.
    const candidates = [
      'https://www.psacard.com/myaccount/myorders',
      'https://www.psacard.com/myaccount',
      'https://app.collectors.com/dashboard',
      'https://app.collectors.com/orders',
    ];

    for (const url of candidates) {
      try {
        console.log(`Navigating to ${url}…`);
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20_000 });
        await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
        const slug = url.replace(/[^a-z0-9]/gi, '-').replace(/^-+|-+$/g, '');
        await saveArtifacts(page, slug);
      } catch (err) {
        console.error(`  ✗ ${url} failed: ${err.message}`);
      }
    }

    console.log('\nDone. Artifacts saved to ./discovery/');
    console.log('Send me everything in that folder and I\'ll write the real scraper.');
  } catch (err) {
    console.error('\nScraper failed:', err.message);
    try { await saveArtifacts(page, 'crash'); } catch {}
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

async function saveArtifacts(page, slug) {
  if (!existsSync(DISCOVERY_DIR)) mkdirSync(DISCOVERY_DIR, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const base = `${slug}-${ts}`;

  const pngPath  = resolve(DISCOVERY_DIR, `${base}.png`);
  const htmlPath = resolve(DISCOVERY_DIR, `${base}.html`);
  const urlPath  = resolve(DISCOVERY_DIR, `${base}.url.txt`);

  await page.screenshot({ path: pngPath, fullPage: true });
  const html = await page.content();
  writeFileSync(htmlPath, html, 'utf8');
  writeFileSync(urlPath, page.url(), 'utf8');

  console.log(`  → saved ${base} (png + html + url)`);
}

main();
