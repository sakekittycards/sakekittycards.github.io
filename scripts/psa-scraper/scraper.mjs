#!/usr/bin/env node
// Sake Kitty Cards — PSA status scraper
//
// Collectors.com is fronted by Cloudflare's aggressive bot detection.
// Even with saved cookies, Cloudflare fingerprints a fresh Playwright
// browser and re-challenges. Solution: use a PERSISTENT Chrome profile
// saved to ./chrome-profile/. The profile persists cookies, cache,
// fingerprint markers, etc., so Cloudflare sees the same browser every
// time and stops challenging after the first manual pass.
//
// Flow:
//   1. `npm run bootstrap` — opens Chrome (visible). You log in manually
//      and click through any Cloudflare challenges. Profile auto-saves
//      to disk as you interact. When you reach the dashboard, we visit
//      a few pages to seed clearance, then close.
//   2. `npm run discover` — reopens the same profile (off-screen), navs
//      the dashboard, saves screenshots + HTML of pages we find.
//   3. `npm start` (future) — full scrape + Airtable update on cron.

import { chromium } from 'playwright';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname      = dirname(fileURLToPath(import.meta.url));
const DISCOVERY_DIR  = resolve(__dirname, 'discovery');
const PROFILE_DIR    = resolve(__dirname, 'chrome-profile');

// ─── .env loader (Airtable only now) ──────────────────────────────────────
function loadEnv() {
  const envPath = resolve(__dirname, '.env');
  if (!existsSync(envPath)) return;
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
const MODE_BOOTSTRAP = args.includes('--bootstrap');
const MODE_DISCOVERY = args.includes('--discover');
const MODE_DEBUG     = args.includes('--debug') || process.env.HEADFUL === '1';

// ─── Main ──────────────────────────────────────────────────────────────────

async function main() {
  if (MODE_BOOTSTRAP) return bootstrap();
  if (MODE_DISCOVERY) return discover();
  console.error('Usage: npm run bootstrap  OR  npm run discover');
  process.exit(1);
}

// Common launch options that help Playwright avoid bot fingerprint triggers.
// - AutomationControlled blink feature is disabled (removes the biggest tell).
// - Visible browser always — Cloudflare blocks true headless reliably.
// - Window positioned off-screen during discover so the user doesn't see it.
function launchOpts({ offScreen }) {
  const args = [
    '--disable-blink-features=AutomationControlled',
    '--disable-infobars',
  ];
  if (offScreen) {
    args.push('--window-position=-2000,-2000');
    args.push('--window-size=1280,900');
  }
  return {
    headless: false,
    args,
    viewport: { width: 1280, height: 900 },
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    // Allow persisted profile to load everything.
    ignoreHTTPSErrors: false,
    acceptDownloads: false,
  };
}

// Launch a persistent-context browser. Reuses the same Chrome profile every
// run so Cloudflare sees a consistent browser identity.
async function openPersistent({ offScreen }) {
  if (!existsSync(PROFILE_DIR)) mkdirSync(PROFILE_DIR, { recursive: true });
  const opts = launchOpts({ offScreen });
  return chromium.launchPersistentContext(PROFILE_DIR, opts);
}

// Bootstrap: opens a visible browser, lets user log in, then warms up the
// pages we care about so Cloudflare issues clearance cookies for them.
async function bootstrap() {
  console.log('Opening a visible Chrome window so you can log in manually…');
  console.log('(Cloudflare challenge → email → password → dashboard.)\n');

  const context = await openPersistent({ offScreen: false });
  const page = context.pages()[0] || await context.newPage();
  await page.goto('https://www.psacard.com/myaccount', { waitUntil: 'domcontentloaded' });

  console.log('Chrome is open. Complete the login flow normally.');
  console.log('This script will auto-detect when you reach your dashboard.\n');

  const TIMEOUT_MS = 10 * 60 * 1000;
  const deadline   = Date.now() + TIMEOUT_MS;
  let loggedIn = false;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 2000));
    let url = '';
    try { url = page.url(); } catch { break; }
    if (!url) continue;
    const onSignin = /\/signin|\/login/i.test(url);
    const onAuthedDomain = /psacard\.com\/myaccount|app\.collectors\.com\/(?!signin|login)/.test(url);
    if (!onSignin && onAuthedDomain) { loggedIn = true; break; }
  }

  if (!loggedIn) {
    await context.close();
    console.error('\n✗ Timed out waiting for login. Try again when you have a few minutes.');
    process.exit(1);
  }

  // Warm up the pages where our submissions live. If Cloudflare challenges
  // any of them, user clicks through — profile persists the clearance.
  console.log('\nWarming up PSA pages (click through any Cloudflare challenges if prompted)…');
  const warmupUrls = [
    'https://www.psacard.com/myaccount/myorders',
    'https://www.psacard.com/myaccount/customerrequestcenter',
  ];
  for (const url of warmupUrls) {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 });
      // Wait up to 60s for a non-challenge title.
      for (let i = 0; i < 30; i++) {
        await new Promise(r => setTimeout(r, 2000));
        const t = await page.title().catch(() => '');
        if (t && !/just a moment/i.test(t)) break;
      }
      console.log(`  ✓ ${url}`);
    } catch (err) {
      console.error(`  ⚠ ${url} (${err.message})`);
    }
  }

  await new Promise(r => setTimeout(r, 2000));
  await context.close();
  console.log(`\n✓ Profile saved to ${PROFILE_DIR}`);
  console.log('  Now run: npm run discover');
}

// Discover: re-open the saved profile, walk dashboard pages, save artifacts.
async function discover() {
  if (!existsSync(PROFILE_DIR)) {
    console.error('✗ No chrome-profile/ found. Run `npm run bootstrap` first.');
    process.exit(1);
  }

  console.log('Launching browser with saved profile…');
  const context = await openPersistent({ offScreen: !MODE_DEBUG });
  const page = context.pages()[0] || await context.newPage();

  try {
    const candidates = [
      'https://www.psacard.com/submissions/dashboard',
      'https://www.psacard.com/myaccount',
      'https://www.psacard.com/myaccount/myorders',
      'https://www.psacard.com/myaccount/customerrequestcenter',
    ];

    for (const url of candidates) {
      try {
        console.log(`Navigating to ${url}…`);
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 });
        // Wait a beat for Turnstile to auto-pass if applicable.
        for (let i = 0; i < 10; i++) {
          await new Promise(r => setTimeout(r, 1500));
          const t = await page.title().catch(() => '');
          if (t && !/just a moment/i.test(t)) break;
        }
        const slug = url.replace(/[^a-z0-9]/gi, '-').replace(/^-+|-+$/g, '');
        await saveArtifacts(page, slug);

        if (/\/signin/.test(page.url())) {
          console.error('\n✗ Session expired — run `npm run bootstrap` to log in again.');
          break;
        }
      } catch (err) {
        console.error(`  ✗ ${url} failed: ${err.message}`);
      }
    }

    console.log('\nDone. Artifacts saved to ./discovery/');
  } catch (err) {
    console.error('\nScraper failed:', err.message);
    try { await saveArtifacts(page, 'crash'); } catch {}
    process.exitCode = 1;
  } finally {
    await context.close();
  }
}

// ─── Helpers ───────────────────────────────────────────────────────────────

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
