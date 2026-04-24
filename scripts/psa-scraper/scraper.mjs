#!/usr/bin/env node
// Sake Kitty Cards — PSA status scraper
//
// Collectors.com uses Cloudflare bot detection, which shadow-rejects
// automated logins (returns "Invalid password" to bots even when the
// password is correct). The workaround: log in manually once in a
// visible browser, save the session state, and reuse it for scrapes.
//
// Flow:
//   1. `npm run bootstrap` — opens a visible Chrome. You log in manually.
//      Script saves the session to ./auth.json. Repeat monthly-ish when
//      the session expires.
//   2. `npm run discover` — uses ./auth.json to navigate the authenticated
//      site and save screenshots + HTML for me to build v1 against.
//   3. `npm start` (future) — full scrape + Airtable update, runs on cron.

import { chromium } from 'playwright';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import readline from 'node:readline';

const __dirname      = dirname(fileURLToPath(import.meta.url));
const DISCOVERY_DIR  = resolve(__dirname, 'discovery');
const AUTH_STATE     = resolve(__dirname, 'auth.json');

// ─── .env loader ──────────────────────────────────────────────────────────
function loadEnv() {
  const envPath = resolve(__dirname, '.env');
  if (!existsSync(envPath)) return;  // .env is optional for bootstrap mode
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

// Bootstrap: open a visible browser, let the user log in manually, save state.
// Auto-detects successful login by watching for the URL to land on an
// authenticated path (not /signin). Saves and closes automatically.
async function bootstrap() {
  console.log('Opening a visible Chrome window so you can log in manually…');
  console.log('(Complete the Cloudflare challenge, enter your email + password, get to the dashboard.)\n');

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
  });
  const page = await context.newPage();
  await page.goto('https://www.psacard.com/myaccount', { waitUntil: 'domcontentloaded' });

  console.log('Chrome is open. Log in as you normally would (Cloudflare → email → password).');
  console.log('Once you reach the PSA dashboard, this script will auto-detect and save your session.\n');

  // Poll every 2s for a URL that indicates we're past login.
  const TIMEOUT_MS = 10 * 60 * 1000;  // 10 minutes to log in
  const POLL_MS    = 2000;
  const deadline   = Date.now() + TIMEOUT_MS;

  let loggedIn = false;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, POLL_MS));
    let currentUrl = '';
    try { currentUrl = page.url(); } catch { break; /* page closed */ }
    if (!currentUrl) continue;
    // Success: we're on psacard.com/myaccount (not the redirect target) or
    // any other non-signin page under psacard.com or app.collectors.com.
    const onSignin = /\/signin|\/login/i.test(currentUrl);
    const onAuthedDomain = /psacard\.com\/myaccount|app\.collectors\.com\/(?!signin|login)/.test(currentUrl);
    if (!onSignin && onAuthedDomain) {
      loggedIn = true;
      break;
    }
  }

  if (!loggedIn) {
    await browser.close();
    console.error('\n✗ Timed out waiting for login. Re-run `npm run bootstrap` when you have a few minutes.');
    process.exit(1);
  }

  // Let the auth cookies settle for a couple seconds before saving.
  await new Promise(r => setTimeout(r, 2000));
  await context.storageState({ path: AUTH_STATE });
  await browser.close();
  console.log(`\n✓ Saved session to ${AUTH_STATE}`);
  console.log('  Now run: npm run discover');
}

// Discover: use saved auth state to walk the dashboard and save artifacts.
async function discover() {
  if (!existsSync(AUTH_STATE)) {
    console.error('✗ No auth.json found. Run `npm run bootstrap` first to log in manually.');
    process.exit(1);
  }

  console.log('Launching browser with saved session…');
  const browser = await chromium.launch({ headless: !MODE_DEBUG, slowMo: MODE_DEBUG ? 200 : 0 });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    storageState: AUTH_STATE,
  });
  const page = await context.newPage();

  try {
    const candidates = [
      'https://www.psacard.com/myaccount',
      'https://www.psacard.com/myaccount/myorders',
      'https://www.psacard.com/myaccount/customerrequestcenter',
      'https://app.collectors.com/dashboard',
      'https://app.collectors.com/orders',
      'https://app.collectors.com/psa/orders',
    ];

    for (const url of candidates) {
      try {
        console.log(`Navigating to ${url}…`);
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20_000 });
        await page.waitForLoadState('networkidle', { timeout: 12_000 }).catch(() => {});
        const slug = url.replace(/[^a-z0-9]/gi, '-').replace(/^-+|-+$/g, '');
        await saveArtifacts(page, slug);

        // If the page kicked us back to signin, the session is expired.
        if (/\/signin/.test(page.url())) {
          console.error('\n✗ Session expired — the saved auth state is no longer valid.');
          console.error('  Run `npm run bootstrap` to log in again.');
          break;
        }
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

function waitForEnter() {
  return new Promise(resolve => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question('Press ENTER when you have reached the PSA dashboard…', () => {
      rl.close();
      resolve();
    });
  });
}

main();
