// ── Lucide icon sprite ──
// Injected once on every page via main.js. Pages reference icons via:
//   <svg class="lc"><use href="#lc-shield-check"/></svg>
// Lucide v0.x stroke-style, 24x24 viewBox, stroke-width 2. Stroke color
// inherits via currentColor — set color: var(--orange) etc on the parent.
// (Lucide is ISC-licensed; embedded paths only, no runtime dep.)
(function injectLucideSprite() {
  if (document.getElementById('lc-sprite')) return;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'lc-sprite';
  svg.setAttribute('style', 'position:absolute;width:0;height:0;overflow:hidden');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = `
    <defs>
      <symbol id="lc-shield-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>
        <path d="m9 12 2 2 4-4"/>
      </symbol>
      <symbol id="lc-badge-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/>
        <path d="m9 12 2 2 4-4"/>
      </symbol>
      <symbol id="lc-package" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M16.5 9.4 7.55 4.24"/>
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
        <polyline points="3.29 7 12 12 20.71 7"/>
        <line x1="12" y1="22" x2="12" y2="12"/>
      </symbol>
      <symbol id="lc-headphones" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H4a1 1 0 0 1-1-1v-6a9 9 0 0 1 18 0v6a1 1 0 0 1-1 1h-2a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"/>
      </symbol>
      <symbol id="lc-message-square" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </symbol>
      <symbol id="lc-mail" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect width="20" height="16" x="2" y="4" rx="2"/>
        <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>
      </symbol>
      <symbol id="lc-truck" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/>
        <path d="M15 18H9"/>
        <path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/>
        <circle cx="17" cy="18" r="2"/>
        <circle cx="7" cy="18" r="2"/>
      </symbol>
      <symbol id="lc-calendar" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect width="18" height="18" x="3" y="4" rx="2" ry="2"/>
        <line x1="16" x2="16" y1="2" y2="6"/>
        <line x1="8" x2="8" y1="2" y2="6"/>
        <line x1="3" x2="21" y1="10" y2="10"/>
      </symbol>
      <symbol id="lc-star" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
      </symbol>
      <symbol id="lc-sparkles" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z"/>
        <path d="M5 3v4"/><path d="M3 5h4"/>
        <path d="M19 17v4"/><path d="M17 19h4"/>
      </symbol>
      <symbol id="lc-gem" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6 3h12l4 6-10 13L2 9z"/>
        <path d="M11 3 8 9l4 13 4-13-3-6"/>
        <path d="M2 9h20"/>
      </symbol>
      <symbol id="lc-store" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7"/>
        <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>
        <path d="M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4"/>
        <path d="M2 7h20"/>
        <path d="M22 7v3a2 2 0 0 1-2 2v0a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 16 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 12 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 8 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 4 12v0a2 2 0 0 1-2-2V7"/>
      </symbol>
      <symbol id="lc-heart-handshake" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>
        <path d="M12 5 9.04 7.96a2.17 2.17 0 0 0 0 3.08c.82.82 2.13.85 3 .07l2.07-1.9a2.82 2.82 0 0 1 3.79 0l2.96 2.66"/>
        <path d="m18 15-2-2"/>
        <path d="m15 18-2-2"/>
      </symbol>
      <symbol id="lc-credit-card" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect width="20" height="14" x="2" y="5" rx="2"/>
        <line x1="2" x2="22" y1="10" y2="10"/>
      </symbol>
      <symbol id="lc-clock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <polyline points="12 6 12 12 16 14"/>
      </symbol>
      <symbol id="lc-map-pin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/>
        <circle cx="12" cy="10" r="3"/>
      </symbol>
      <symbol id="lc-search" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"/>
        <path d="m21 21-4.3-4.3"/>
      </symbol>
      <symbol id="lc-filter" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
      </symbol>
      <symbol id="lc-zap" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
      </symbol>
      <symbol id="lc-flame" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>
      </symbol>
      <symbol id="lc-chevron-right" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 18 15 12 9 6"/>
      </symbol>
      <symbol id="lc-circus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 11h18l-2 9H5z"/>
        <path d="M3 11l9-9 9 9"/>
        <path d="M9 11v9"/>
        <path d="M15 11v9"/>
      </symbol>
    </defs>
  `;
  document.body.prepend(svg);
})();

// ── Lava-lamp nav effect ──
// Inject the SVG gooey filter once, and populate the nav with colored blobs.
(function injectLavaLamp() {
  // SVG filter — creates the liquid-merging effect between blurred shapes
  if (!document.getElementById('nav-goo')) {
    const svgNs = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNs, 'svg');
    svg.setAttribute('style', 'position:absolute;width:0;height:0;overflow:hidden');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = `
      <defs>
        <filter id="nav-goo">
          <feGaussianBlur in="SourceGraphic" stdDeviation="14" result="blur" />
          <feColorMatrix in="blur" mode="matrix"
            values="1 0 0 0 0   0 1 0 0 0   0 0 1 0 0   0 0 0 22 -10"
            result="goo" />
          <feComposite in="SourceGraphic" in2="goo" operator="atop"/>
        </filter>
      </defs>
    `;
    document.body.prepend(svg);
  }

  // Inject blob container into the nav
  const nav = document.querySelector('.site-nav');
  if (nav && !nav.querySelector('.nav-lava')) {
    const lava = document.createElement('div');
    lava.className = 'nav-lava';
    for (let i = 0; i < 5; i++) {
      const blob = document.createElement('div');
      blob.className = 'nav-lava-blob';
      lava.appendChild(blob);
    }
    nav.insertBefore(lava, nav.firstChild);
  }
})();

// Nav hamburger — keeps aria-expanded in sync so screen readers announce
// the menu state correctly.
const toggle = document.getElementById('navToggle');
const links  = document.getElementById('navLinks');
const syncNavExpanded = () => toggle?.setAttribute('aria-expanded', String(links?.classList.contains('open') || false));
toggle?.addEventListener('click', () => { links.classList.toggle('open'); syncNavExpanded(); });
links?.querySelectorAll('a').forEach(a => a.addEventListener('click', () => { links.classList.remove('open'); syncNavExpanded(); }));
syncNavExpanded();

// Active nav link
document.querySelectorAll('.nav-links a').forEach(a => {
  const href = a.getAttribute('href');
  const path = window.location.pathname.replace(/\/$/, '') || '/';
  const page = href.replace('.html', '');
  if (href === 'index.html' || href === '/') {
    if (path === '/' || path === '/index.html' || path === '') a.classList.add('active');
  } else if (path.endsWith(page) || path.endsWith(href)) {
    a.classList.add('active');
  }
});

// FAQ accordion — items are native <details>/<summary> now (faq.html).
// Single-open behavior: closing the others when one opens, so the page
// doesn't sprawl after a few clicks.
document.querySelectorAll('details.faq-item').forEach(item => {
  item.addEventListener('toggle', () => {
    if (item.open) {
      document.querySelectorAll('details.faq-item').forEach(i => { if (i !== item) i.open = false; });
    }
  });
});

// Generic notify/contact form success
document.querySelectorAll('form[data-success]').forEach(form => {
  form.addEventListener('submit', e => {
    e.preventDefault();
    const msg = form.getAttribute('data-success');
    form.innerHTML = `<p style="color:rgba(255,255,255,.7);padding:12px 0">${msg}</p>`;
  });
});

// ── Subtle ring flash on button click (replaces paint splatter) ──
function clickFlash(btn) {
  const rect = btn.getBoundingClientRect();
  const ring = document.createElement('div');
  ring.className = 'click-ring';
  ring.style.left   = (rect.left + rect.width  / 2) + 'px';
  ring.style.top    = (rect.top  + rect.height / 2) + 'px';
  ring.style.width  = Math.max(rect.width,  40) + 'px';
  ring.style.height = Math.max(rect.height, 40) + 'px';
  // Match the border-radius so the ring hugs rounded/pill buttons
  ring.style.borderRadius = getComputedStyle(btn).borderRadius || '100px';
  document.body.appendChild(ring);
  setTimeout(() => ring.remove(), 550);
}

document.addEventListener('click', (e) => {
  if (e.target.closest('.site-nav')) return;
  const target = e.target.closest(
    '.btn-primary, .btn-venmo, .btn-paypal, .btn-paylater, .btn-tcg, .btn-outline, .qty-btn'
  );
  if (!target) return;
  clickFlash(target);
});

// Make the in-nav lava blobs clickable — click to "catch" one (pause + glow).
// Hidden easter egg: click the same blob 5 times → unlock the page-wide drip.
const blobClickCounts = new WeakMap();
const UNLOCK_AT = 5;

document.querySelectorAll('.nav-lava-blob').forEach(blob => {
  blob.addEventListener('click', (e) => {
    e.stopPropagation();
    blob.classList.add('caught');
    setTimeout(() => blob.classList.remove('caught'), 650);

    const count = (blobClickCounts.get(blob) || 0) + 1;
    blobClickCounts.set(blob, count);
    // Every 5th click on the same blob spawns one fresh drip
    if (count % UNLOCK_AT === 0) {
      if (!document.body.classList.contains('drip-unlocked')) {
        unlockPageDrip(); // first time: unlock + one drip
      } else {
        spawnSingleDrip();  // subsequent: just one more drip
      }
    }
  });
});

function unlockPageDrip() {
  document.body.classList.add('drip-unlocked');
  ensureDripContainer();
  spawnSingleDrip(); // fire one immediately on unlock
}

function ensureDripContainer() {
  if (document.querySelector('.page-drip-bg')) return;
  const container = document.createElement('div');
  container.className = 'page-drip-bg';
  document.body.appendChild(container);
}

function spawnSingleDrip() {
  const container = document.querySelector('.page-drip-bg');
  if (!container) return;

  const COLORS = ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff', '#ff4e00'];
  const color   = COLORS[Math.floor(Math.random() * COLORS.length)];
  const x       = 6 + Math.random() * 88;
  const size    = 55 + Math.random() * 50;
  const docH    = document.documentElement.scrollHeight;
  const fallDur = Math.max(16, docH / 80);

  const blob = document.createElement('div');
  blob.className = 'page-drip-blob';
  blob.style.left   = x + 'vw';
  blob.style.width  = size + 'px';
  blob.style.height = size + 'px';
  blob.style.backgroundColor = color;
  blob.style.boxShadow = `0 0 22px ${color}`;
  blob.style.animationDuration = fallDur + 's';
  blob.style.setProperty('--fall-end', (docH - 40) + 'px');

  const r1 = 40 + Math.random() * 35;
  const r2 = 50 + Math.random() * 30;
  const r3 = 45 + Math.random() * 35;
  const r4 = 55 + Math.random() * 25;
  blob.style.borderRadius = `${r1}% ${r2}% ${r3}% ${r4}% / ${r4}% ${r3}% ${r2}% ${r1}%`;

  container.appendChild(blob);
  setTimeout(() => blob.remove(), (fallDur + 1) * 1000);
}

// ── Easter egg: 69 clicks on Andrew & Grace's vendor photo summons a dancing beaver ──
(function initBeaverEgg() {
  const photo = document.querySelector('img.vendor-avatar[src*="andrew-grace"]');
  if (!photo) return;
  const TARGET = 69;
  let count = 0;
  let resetTimer = null;
  photo.style.cursor = 'pointer';
  photo.style.transition = 'transform 110ms ease-out, box-shadow 200ms ease-out, filter 200ms ease-out';
  photo.addEventListener('click', () => {
    count += 1;
    photo.style.transform = 'scale(0.95)';
    setTimeout(() => { photo.style.transform = ''; }, 110);
    // Progressive glow so the user knows clicks are registering — gets
    // hotter the closer you get to TARGET.
    const heat = Math.min(1, count / TARGET);
    const glow = 8 + heat * 32;
    photo.style.boxShadow = `0 0 ${glow}px rgba(255,${Math.round(180 - heat * 130)},0,${0.35 + heat * 0.55})`;
    photo.style.filter    = `saturate(${1 + heat * 0.6}) brightness(${1 + heat * 0.15})`;
    clearTimeout(resetTimer);
    resetTimer = setTimeout(() => {
      count = 0;
      photo.style.boxShadow = '';
      photo.style.filter    = '';
    }, 10000);
    if (count >= TARGET) {
      count = 0;
      photo.style.boxShadow = '';
      photo.style.filter    = '';
      summonDancingBeaver();
    }
  });
})();

function summonDancingBeaver() {
  if (document.querySelector('.sk-beaver')) return;
  if (!document.getElementById('sk-beaver-style')) {
    const style = document.createElement('style');
    style.id = 'sk-beaver-style';
    style.textContent = `
      .sk-beaver {
        position: fixed; bottom: 8vh; left: 50%;
        font-size: 140px; line-height: 1;
        z-index: 99999; pointer-events: none;
        filter: drop-shadow(0 8px 18px rgba(0,0,0,.55));
        animation:
          sk-beaver-drift 6s ease-in-out infinite,
          sk-beaver-fade  9s forwards;
      }
      .sk-beaver-inner {
        display: inline-block;
        animation: sk-beaver-dance 0.5s ease-in-out infinite;
      }
      @keyframes sk-beaver-dance {
        0%,100% { transform: translateY(0) rotate(-14deg) }
        50%     { transform: translateY(-22px) rotate(14deg) }
      }
      @keyframes sk-beaver-drift {
        0%,100% { transform: translateX(-50%) }
        25%     { transform: translateX(-280px) }
        75%     { transform: translateX( 220px) }
      }
      @keyframes sk-beaver-fade {
        0%,88% { opacity: 1 }
        100%   { opacity: 0 }
      }
    `;
    document.head.appendChild(style);
  }
  const beaver = document.createElement('div');
  beaver.className = 'sk-beaver';
  beaver.setAttribute('aria-hidden', 'true');
  const inner = document.createElement('span');
  inner.className = 'sk-beaver-inner';
  inner.textContent = '🦫';
  beaver.appendChild(inner);
  document.body.appendChild(beaver);
  setTimeout(() => beaver.remove(), 9000);
}

// ═══════════════════════════════════════════════════════════════════════════
// Cart state + drawer UI
// ═══════════════════════════════════════════════════════════════════════════

const SK_CART_KEY        = 'sk_cart_v1';
const SK_SHIP_STATE_KEY  = 'sk_ship_state_v1';
const SK_INSURANCE_OPTED_KEY = 'sk_insurance_opted_v1';
const SK_SHIP_FLAT_FEE   = 5;
// Free shipping kicks in when the cart subtotal crosses this threshold.
// Bumped to $100 (2026-05-21) so heavier orders absorb their own ship
// cost without the customer feeling it; small orders still pay the flat
// fee. The pricing formula already bakes the absorbed-ship cost into
// stickers for items where the per-item ship cost would exceed $5.
const SK_FREE_SHIP_THRESHOLD = 100;
// OPTIONAL shipping insurance on graded / raw / sealed orders. $1.50 per
// $100 of insurable value (rounded up to the next $100). Customer opts in
// via the cart-drawer checkbox — defaults OFF. Merch is never insured.
const SK_INSURANCE_RATE_PER_100 = 1.50;
const SK_INSURANCE_THRESHOLD    = 100;
const SK_WORKER_BASE     = 'https://sakekitty-square.nwilliams23999.workers.dev';
const SK_VENMO_HANDLE    = 'sakekittycards';
const SK_PAYPAL_HANDLE   = 'sakekittycards';
const SK_WEB3FORMS_KEY   = 'd42c7cee-c136-4450-989f-6ec666f79d3a';

// Sales tax rates by destination state. Source of truth for the cart-drawer
// preview line; the worker has its own copy that drives what's sent to
// Square. Keep both in sync when nexus changes.
const SK_TAX_RATES = {
  FL: 0.06,
};
function skTaxRate(state) {
  return SK_TAX_RATES[(state || '').toUpperCase()] || 0;
}
function skTaxAmount(subtotal, shipping, state, insurance = 0) {
  const rate = skTaxRate(state);
  if (rate <= 0) return 0;
  // Insurance is sourced via the shipping carrier, billed to the customer,
  // and folded into the taxable base alongside shipping. FL technically
  // exempts separately stated insurance — we eat that ~6¢ per $1 rather
  // than maintain a per-state taxability matrix for now.
  return (subtotal + shipping + insurance) * rate;
}
function skGetShipState() {
  try { return localStorage.getItem(SK_SHIP_STATE_KEY) || ''; } catch { return ''; }
}
function skSaveShipState(state) {
  try { localStorage.setItem(SK_SHIP_STATE_KEY, state || ''); } catch {}
}

const skCartListeners = new Set();

function skGetCart() {
  try {
    const raw = localStorage.getItem(SK_CART_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}
function skSaveCart(cart) {
  try { localStorage.setItem(SK_CART_KEY, JSON.stringify(cart)); } catch {}
  skCartListeners.forEach(fn => { try { fn(cart); } catch {} });
}
// Lightweight ephemeral toast for inventory-cap messages. No CSS dependency
// beyond what's already in the cart drawer styles.
function skToast(message) {
  let el = document.getElementById('sk-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'sk-toast';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.style.cssText = 'position:fixed;left:50%;bottom:34px;transform:translateX(-50%) translateY(20px);background:rgba(10,10,18,0.96);border:1px solid rgba(255,106,0,0.45);color:#fff;padding:12px 18px;border-radius:10px;font:600 13.5px Inter,sans-serif;box-shadow:0 8px 28px rgba(0,0,0,0.5);opacity:0;transition:opacity .18s,transform .18s;z-index:10000;pointer-events:none;max-width:88%';
    document.body.appendChild(el);
  }
  el.textContent = message;
  requestAnimationFrame(() => {
    el.style.opacity = '1';
    el.style.transform = 'translateX(-50%) translateY(0)';
  });
  clearTimeout(skToast._t);
  skToast._t = setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateX(-50%) translateY(20px)';
  }, 2400);
}

function skAddToCart(product) {
  if (!product || !product.id) return;
  const cart = skGetCart();
  const existing = cart.find(item => item.id === product.id);
  // Graded slabs are 1-of-1 by cert. Hard-cap at 1 even if Square's
  // inventory data is missing (legacy listings without track_inventory).
  const isGraded = product.category === 'graded';
  let stockCap = (typeof product.stock === 'number' && product.stock > 0)
    ? product.stock : null;
  if (isGraded) stockCap = 1;
  if (existing) {
    const target = existing.quantity + 1;
    if (stockCap !== null && target > stockCap) {
      skToast(`Only ${stockCap} in stock`);
      return;
    }
    existing.quantity = Math.min(99, target);
    // Refresh stock if it changed since last add (newer data wins)
    if (stockCap !== null) existing.stock = stockCap;
  } else {
    cart.push({
      id:          product.id,
      variationId: product.variationId || product.id,
      name:        String(product.name || 'Item'),
      price:       Number(product.price) || 0,
      imageUrl:    product.imageUrl || null,
      // 'merch' (apparel/plushies/Printful) is exempt from shipping
      // insurance. Anything else (graded cards, raw cards, sealed) is
      // insurable. The shop pages tag this when adding; we default to
      // 'card' so legacy carts still apply insurance correctly.
      category:    product.category === 'merch' ? 'merch' : 'card',
      stock:       stockCap,
      quantity:    1,
    });
  }
  skSaveCart(cart);
}
function skRemoveFromCart(id) {
  skSaveCart(skGetCart().filter(i => i.id !== id));
}
function skUpdateQuantity(id, qty) {
  const cart = skGetCart();
  const item = cart.find(i => i.id === id);
  if (!item) return;
  if (qty <= 0) {
    skSaveCart(cart.filter(i => i.id !== id));
  } else {
    let stockCap = (typeof item.stock === 'number' && item.stock > 0)
      ? item.stock : null;
    // Graded slabs are always 1-of-1 — applies even to legacy cart rows
    // saved before the per-item stock field was plumbed through.
    if (item.category === 'graded') stockCap = 1;
    if (stockCap !== null && qty > stockCap) {
      skToast(`Only ${stockCap} in stock`);
      item.quantity = Math.min(99, stockCap);
    } else {
      item.quantity = Math.min(99, qty);
    }
    skSaveCart(cart);
  }
}
function skClearCart() { skSaveCart([]); }
function skCartCount() {
  return skGetCart().reduce((s, i) => s + i.quantity, 0);
}
function skCartSubtotal() {
  return skGetCart().reduce((s, i) => s + (i.price * i.quantity), 0);
}
// Subtotal of items eligible for insurance: graded / raw / sealed cards.
// Merch is excluded (clothing / Printful / etc.).
function skInsurableSubtotal() {
  return skGetCart()
    .filter(i => i.category !== 'merch')
    .reduce((s, i) => s + (i.price * i.quantity), 0);
}
function skGetInsuranceOpted() {
  try { return localStorage.getItem(SK_INSURANCE_OPTED_KEY) === '1'; } catch { return false; }
}
function skSetInsuranceOpted(opted) {
  try { localStorage.setItem(SK_INSURANCE_OPTED_KEY, opted ? '1' : '0'); } catch {}
}
function skInsuranceCost(insurableSubtotal) {
  if (!skGetInsuranceOpted()) return 0;
  if (insurableSubtotal < SK_INSURANCE_THRESHOLD) return 0;
  return Math.ceil(insurableSubtotal / 100) * SK_INSURANCE_RATE_PER_100;
}
function skShippingCost(subtotal) {
  if (subtotal <= 0) return 0;
  if (subtotal >= SK_FREE_SHIP_THRESHOLD) return 0;
  return SK_SHIP_FLAT_FEE;
}

// Public API for shop pages
window.SK = {
  getCart:        skGetCart,
  addToCart:      skAddToCart,
  removeFromCart: skRemoveFromCart,
  updateQuantity: skUpdateQuantity,
  clearCart:      skClearCart,
  getCount:       skCartCount,
  getSubtotal:    skCartSubtotal,
  getShipping:    skShippingCost,
  getInsurance:   () => skInsuranceCost(skInsurableSubtotal()),
  FREE_SHIP_THRESHOLD: SK_FREE_SHIP_THRESHOLD,
  WORKER_BASE:    SK_WORKER_BASE,
  onCartChange(fn) { skCartListeners.add(fn); return () => skCartListeners.delete(fn); },
  openDrawer()     { document.getElementById('navCart')?.click(); },
};

// Inject cart icon + drawer into every page
(function mountCart() {
  const navInner = document.querySelector('.site-nav .nav-inner');
  if (!navInner) return;

  // 1) Cart icon — appended at the END of nav-inner so it sits after the menu
  //    links on desktop; mobile reorders it before the hamburger via CSS.
  if (!navInner.querySelector('.nav-cart')) {
    const cartBtn = document.createElement('button');
    cartBtn.type = 'button';
    cartBtn.className = 'nav-cart';
    cartBtn.id = 'navCart';
    cartBtn.setAttribute('aria-label', 'Open cart');
    cartBtn.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5.5 5.5 3 5V3h2.7l1 4h12.9l-2.6 8H8.4l-.3-1.25L6.3 5.5zM9 21a2 2 0 1 1 0-4 2 2 0 0 1 0 4zm8 0a2 2 0 1 1 0-4 2 2 0 0 1 0 4z"/>
      </svg>
      <span class="nav-cart-badge" id="navCartBadge" hidden></span>
    `;
    navInner.appendChild(cartBtn);
  }

  // On the dedicated cart page we don't inject the slide-out drawer —
  // the static .page-cart layout already owns #cartBody / #cartFooter,
  // and a second copy would collide IDs (cartShipState, payWithSquare,
  // cartInsuranceOptIn, etc.).
  const isCartPage = document.body.classList.contains('page-cart');

  // 2) Drawer + backdrop at end of body (skip on cart page)
  if (!isCartPage && !document.getElementById('cartDrawer')) {
    const backdrop = document.createElement('div');
    backdrop.className = 'cart-drawer-backdrop';
    backdrop.id = 'cartBackdrop';
    document.body.appendChild(backdrop);

    const drawer = document.createElement('aside');
    drawer.className = 'cart-drawer';
    drawer.id = 'cartDrawer';
    drawer.setAttribute('role', 'dialog');
    drawer.setAttribute('aria-labelledby', 'cartTitle');
    drawer.setAttribute('aria-hidden', 'true');
    drawer.innerHTML = `
      <div class="cart-drawer-header">
        <h3 id="cartTitle">Cart</h3>
        <div class="cart-drawer-header-actions">
          <a href="cart.html" class="cart-drawer-fullview" title="Open full cart page">View full cart →</a>
          <button type="button" class="cart-drawer-close" id="cartClose" aria-label="Close cart">×</button>
        </div>
      </div>
      <div class="cart-drawer-body" id="cartBody"></div>
      <div class="cart-drawer-footer" id="cartFooter"></div>
    `;
    document.body.appendChild(drawer);
  }

  const cartBtn   = document.getElementById('navCart');
  const drawer    = document.getElementById('cartDrawer');
  const backdrop  = document.getElementById('cartBackdrop');
  const closeBtn  = document.getElementById('cartClose');

  function open() {
    if (!drawer) return;
    drawer.classList.add('open');
    backdrop?.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('cart-open');
    renderDrawer();
  }
  function close() {
    if (!drawer) return;
    drawer.classList.remove('open');
    backdrop?.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('cart-open');
  }
  if (isCartPage) {
    // On the cart page, the nav cart icon shouldn't open a drawer — we're
    // already on the cart. Just scroll back to the top so customers can
    // re-read the totals from the icon they expect to do something.
    cartBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  } else {
    cartBtn?.addEventListener('click', open);
    backdrop?.addEventListener('click', close);
    closeBtn?.addEventListener('click', close);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && drawer?.classList.contains('open')) close();
    });
  }

  function fmt(n) { return `$${(Math.round(n * 100) / 100).toFixed(2)}`; }

  function renderBadge() {
    const badge = document.getElementById('navCartBadge');
    if (!badge) return;
    const count = skCartCount();
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.hidden = count === 0;
  }

  // ─── Promo code state ─────────────────────────────────────────────────────
  // Persisted in localStorage so the discount survives drawer close/reopen
  // and page navigation. Shape: { code, status: 'valid'|'invalid'|'pending',
  // discount, reason, validatedAt, validatedSubtotal }.
  const SK_PROMO_KEY = 'sk_promo_v1';

  function skGetPromoState() {
    try { return JSON.parse(localStorage.getItem(SK_PROMO_KEY) || 'null'); }
    catch { return null; }
  }
  function skSetPromoState(state) {
    if (!state) { localStorage.removeItem(SK_PROMO_KEY); return; }
    try { localStorage.setItem(SK_PROMO_KEY, JSON.stringify(state)); } catch {}
  }
  // Return the promo state ONLY if it's valid for the current subtotal,
  // otherwise null. (Subtotal might've changed since validation — e.g.
  // user removed an item dropping below $100 — so we re-check the floor.)
  function skGetValidPromo(currentSubtotalDollars) {
    const p = skGetPromoState();
    if (!p || p.status !== 'valid' || !p.code) return null;
    const minCents = p.minSubtotal || 0;
    if (Math.round(currentSubtotalDollars * 100) < minCents) return null;
    return p;
  }
  function renderPromoRow(promo, subtotal) {
    if (promo && promo.status === 'valid') {
      return `<div class="cart-totals-row" style="color:#4ade80"><span>Promo <code style="background:rgba(74,222,128,0.12);padding:1px 6px;border-radius:4px;font-family:'Courier New',monospace">${promo.code}</code></span><span>−${fmt(promo.discount)}</span></div>`;
    }
    return ''; // input lives below the totals; nothing to show inline yet
  }

  // Promo input box below totals — collapsed by default unless they have
  // an active code or are mid-validation.
  function renderPromoInput(promo, subtotal) {
    const stored = skGetPromoState();
    // If currently valid, show "Remove code" affordance instead of input.
    if (promo && promo.status === 'valid') {
      return `
        <div class="cart-promo-applied" style="display:flex;align-items:center;gap:8px;padding:10px 12px;border:1px solid rgba(74,222,128,0.35);border-radius:8px;background:rgba(74,222,128,0.05);margin:8px 0">
          <span style="font-size:13px;color:#4ade80;flex:1">✓ <strong>${promo.code}</strong> applied — ${fmt(promo.discount)} off</span>
          <button type="button" id="cartPromoRemove" class="btn-link" style="background:none;border:none;color:var(--dim);font-size:12px;cursor:pointer;text-decoration:underline">Remove</button>
        </div>
      `;
    }
    // If stored but invalid (e.g., subtotal dropped below min), show the error.
    const status = stored?.status;
    const reason = stored?.reason;
    const reasonText = {
      not_found:        'Code not found.',
      already_redeemed: 'Code already used.',
      below_min:        `Spend $${((stored?.minSubtotal||0)/100).toFixed(0)}+ to use this code.`,
      expired:          'Code expired.',
      disabled:         'Code is no longer active.',
      network:          'Could not check code — try again.',
    }[reason] || (status === 'invalid' ? 'Code invalid.' : '');
    const prefillValue = stored?.code && status !== 'invalid' ? stored.code : '';

    return `
      <div class="cart-promo" style="margin:8px 0">
        <label for="cartPromoInput" style="display:block;font-size:11px;font-weight:700;color:var(--dim);text-transform:uppercase;letter-spacing:1.2px;margin-bottom:6px">Promo code</label>
        <div style="display:flex;gap:8px">
          <input type="text" id="cartPromoInput" placeholder="ABCD" maxlength="12" autocomplete="off" autocapitalize="characters" spellcheck="false"
                 value="${prefillValue}"
                 style="flex:1;background:rgba(0,0,0,0.25);border:1.5px solid rgba(255,255,255,0.12);border-radius:8px;padding:10px 12px;font-size:16px;font-family:'Courier New',monospace;letter-spacing:0.1em;text-transform:uppercase;color:var(--text)" />
          <button type="button" id="cartPromoApply" class="btn btn-outline" style="padding:0 18px;font-size:13px;letter-spacing:0.06em">Apply</button>
        </div>
        ${reasonText ? `<p style="font-size:12px;color:#ff7a96;margin:6px 0 0">${reasonText}</p>` : ''}
        <p style="font-size:11px;color:var(--dim);margin:4px 0 0">Show code from your business card? Enter it here.</p>
      </div>
    `;
  }

  // Hit the worker to validate a code against the current subtotal.
  async function applyPromoCode(rawCode) {
    const code = String(rawCode || '').trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (!code) return;
    const subtotalCents = Math.round(skCartSubtotal() * 100);
    // Optimistic loading state
    skSetPromoState({ code, status: 'pending' });
    renderDrawer();

    try {
      const res = await fetch(`${SK_WORKER_BASE}/promo/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, cart_subtotal: subtotalCents }),
      });
      const data = await res.json();
      if (data.valid) {
        skSetPromoState({
          code:              data.code,
          status:            'valid',
          discount:          (data.discount_cents || 0) / 100,   // store in dollars for total math
          discountCents:     data.discount_cents,
          discountKind:      data.discount_kind,
          discountValue:     data.discount_value,
          minSubtotal:       data.min_subtotal,
          offerType:         data.offer_type,
          validatedSubtotal: subtotalCents,
        });
      } else {
        skSetPromoState({ code, status: 'invalid', reason: data.reason, minSubtotal: data.min_subtotal });
      }
    } catch (err) {
      skSetPromoState({ code, status: 'invalid', reason: 'network' });
    }
    renderDrawer();
  }

  function renderDrawer() {
    const body   = document.getElementById('cartBody');
    const footer = document.getElementById('cartFooter');
    if (!body || !footer) return;

    const cart = skGetCart();

    if (cart.length === 0) {
      body.innerHTML = `
        <div class="cart-empty">
          <div class="cart-empty-stage" aria-hidden="true">
            <span class="cart-empty-glow"></span>
            <span class="cart-empty-card cec-1">★</span>
            <span class="cart-empty-card cec-2">◆</span>
            <span class="cart-empty-card cec-3">●</span>
          </div>
          <h4>Cart's quiet for now</h4>
          <p>Browse graded slabs, sealed, and merch — or send your cards in for a quote.</p>
          <div class="cart-empty-ctas">
            <a href="shop.html" class="btn btn-primary">Shop the Catalog</a>
            <a href="trade-in.html" class="btn btn-outline btn-sm">Sell / Trade →</a>
          </div>

          <!-- Quick-link rail — gives the empty drawer some utility instead of pure void. -->
          <div class="cart-empty-quick">
            <a href="events.html"><span aria-hidden="true">📅</span><span>Upcoming events</span></a>
            <a href="grading-prep.html"><span aria-hidden="true">🏆</span><span>Grading prep</span></a>
            <a href="track.html"><span aria-hidden="true">🔍</span><span>Track an order</span></a>
            <a href="shipping.html"><span aria-hidden="true">📦</span><span>Shipping guide</span></a>
          </div>

          <!-- Utility / trust chips. -->
          <ul class="cart-empty-trust">
            <li><strong>Free shipping over $${SK_FREE_SHIP_THRESHOLD}</strong> · flat $5 under · cards & sealed ship insured at $1 per $100</li>
            <li><strong>★ Gold Star Seller</strong> on TCGPlayer · 99%+ feedback</li>
            <li>Local-vendor heads up — every order reviewed before we charge</li>
          </ul>
        </div>
      `;
      footer.innerHTML = '';
      return;
    }

    body.innerHTML = cart.map(item => {
      const thumb = item.imageUrl
        ? `<img src="${item.imageUrl}" alt="" class="cart-item-img" onerror="this.style.visibility='hidden'" />`
        : `<div class="cart-item-img placeholder">📦</div>`;
      // Graded slabs are 1-of-1 by cert — show a cap of 1 even if the cart
      // row was saved before stock plumbing existed.
      const effectiveStock = item.category === 'graded'
        ? 1
        : (typeof item.stock === 'number' ? item.stock : null);
      const atCap = effectiveStock !== null && item.quantity >= effectiveStock;
      const stockHint = effectiveStock !== null
        ? `<div class="cart-item-stock${atCap ? ' at-cap' : ''}">${atCap ? `Max ${effectiveStock} available` : `${effectiveStock} in stock`}</div>`
        : '';
      return `
        <div class="cart-item" data-id="${item.id}">
          ${thumb}
          <div class="cart-item-info">
            <h5>${item.name}</h5>
            <div class="cart-item-price">${fmt(item.price)} each</div>
            ${stockHint}
            <div class="cart-item-controls">
              <div class="cart-qty-group">
                <button type="button" class="cart-qty-btn" data-action="dec" aria-label="Decrease">−</button>
                <span class="cart-qty-num">${item.quantity}</span>
                <button type="button" class="cart-qty-btn" data-action="inc" aria-label="Increase"${atCap ? ' disabled' : ''}>+</button>
              </div>
              <button type="button" class="cart-item-remove" data-action="remove">Remove</button>
            </div>
          </div>
          <div class="cart-item-total">${fmt(item.price * item.quantity)}</div>
        </div>
      `;
    }).join('');

    body.querySelectorAll('.cart-item').forEach(el => {
      const id = el.dataset.id;
      el.querySelector('[data-action="dec"]')?.addEventListener('click', () => {
        const item = skGetCart().find(i => i.id === id);
        if (item) skUpdateQuantity(id, item.quantity - 1);
      });
      el.querySelector('[data-action="inc"]')?.addEventListener('click', () => {
        const item = skGetCart().find(i => i.id === id);
        if (item) skUpdateQuantity(id, item.quantity + 1);
      });
      el.querySelector('[data-action="remove"]')?.addEventListener('click', () => skRemoveFromCart(id));
    });

    const subtotal  = skCartSubtotal();
    const shipping  = skShippingCost(subtotal);
    const insurable = skInsurableSubtotal();
    const insurance = skInsuranceCost(insurable);
    const shipState = skGetShipState();
    const tax       = skTaxAmount(subtotal, shipping, shipState, insurance);
    // Promo discount applied? skPromoState() returns { code, discount, status, reason } or null.
    const promo     = skGetValidPromo(subtotal);
    const discount  = promo ? promo.discount : 0;
    const total     = Math.max(0, subtotal - discount + shipping + insurance + tax);

    // US state options. FL flagged so we can show a small "+7% tax" hint.
    const STATES = [
      ['AL','Alabama'],['AK','Alaska'],['AZ','Arizona'],['AR','Arkansas'],
      ['CA','California'],['CO','Colorado'],['CT','Connecticut'],['DE','Delaware'],
      ['FL','Florida'],['GA','Georgia'],['HI','Hawaii'],['ID','Idaho'],
      ['IL','Illinois'],['IN','Indiana'],['IA','Iowa'],['KS','Kansas'],
      ['KY','Kentucky'],['LA','Louisiana'],['ME','Maine'],['MD','Maryland'],
      ['MA','Massachusetts'],['MI','Michigan'],['MN','Minnesota'],['MS','Mississippi'],
      ['MO','Missouri'],['MT','Montana'],['NE','Nebraska'],['NV','Nevada'],
      ['NH','New Hampshire'],['NJ','New Jersey'],['NM','New Mexico'],['NY','New York'],
      ['NC','North Carolina'],['ND','North Dakota'],['OH','Ohio'],['OK','Oklahoma'],
      ['OR','Oregon'],['PA','Pennsylvania'],['RI','Rhode Island'],['SC','South Carolina'],
      ['SD','South Dakota'],['TN','Tennessee'],['TX','Texas'],['UT','Utah'],
      ['VT','Vermont'],['VA','Virginia'],['WA','Washington'],['WV','West Virginia'],
      ['WI','Wisconsin'],['WY','Wyoming'],['DC','District of Columbia'],
    ];
    const stateOptions = STATES.map(([code, name]) => {
      const flag = code === 'FL' ? ' (+6% tax)' : '';
      const sel  = code === shipState ? ' selected' : '';
      return `<option value="${code}"${sel}>${name}${flag}</option>`;
    }).join('');
    const taxRow = shipState
      ? (tax > 0
          ? `<div class="cart-totals-row"><span>Tax (FL 6%)</span><span>${fmt(tax)}</span></div>`
          : `<div class="cart-totals-row"><span>Tax</span><span>—</span></div>`)
      : `<div class="cart-totals-row" style="color:var(--dim)"><span>Tax</span><span>Pick state</span></div>`;
    const checkoutDisabled = !shipState;

    footer.innerHTML = `
      <label class="cart-ship-state">
        <span>Shipping to</span>
        <select id="cartShipState">
          <option value="">— Select state —</option>
          ${stateOptions}
        </select>
      </label>

      <div class="cart-totals-row"><span>Subtotal</span><span>${fmt(subtotal)}</span></div>
      ${renderPromoRow(promo, subtotal)}
      <div class="cart-totals-row"><span>Shipping</span><span>${shipping === 0 && subtotal >= SK_FREE_SHIP_THRESHOLD ? '<strong style="color:#4ade80">FREE</strong>' : fmt(shipping)}</span></div>
      ${shipping > 0 && subtotal < SK_FREE_SHIP_THRESHOLD
        ? `<div class="cart-free-ship-hint" style="font-size:12px;color:var(--orange);margin:-4px 0 6px;line-height:1.4">📦 Add ${fmt(SK_FREE_SHIP_THRESHOLD - subtotal)} more for free shipping</div>`
        : ''}
      ${insurable >= SK_INSURANCE_THRESHOLD
        ? `<label class="cart-insurance-toggle">
             <input type="checkbox" id="cartInsuranceOptIn"${skGetInsuranceOpted() ? ' checked' : ''} />
             <span class="cart-insurance-toggle-text">
               Add shipping insurance
               <span class="cart-insurance-toggle-detail">${fmt(SK_INSURANCE_RATE_PER_100)} per ${fmt(100)} of card value${insurance > 0 ? ` · adds ${fmt(insurance)}` : ''}</span>
             </span>
           </label>`
        : ''}
      ${insurance > 0
        ? `<div class="cart-totals-row"><span>Shipping insurance</span><span>${fmt(insurance)}</span></div>`
        : ''}
      ${taxRow}
      <div class="cart-totals-row grand"><span>Total</span><span>${fmt(total)}</span></div>
      <p class="cart-insurance-note">Shipping insurance is optional — recommended on high-value cards and sealed. Free shipping on orders over ${fmt(SK_FREE_SHIP_THRESHOLD)}.</p>

      ${renderPromoInput(promo, subtotal)}

      <div class="cart-pay-options">
        <button type="button" class="btn btn-primary cart-pay-btn" id="payWithSquare"${checkoutDisabled ? ' disabled' : ''}>
          <span class="pay-label">${checkoutDisabled ? 'Select shipping state' : 'Pay with Square'}</span>
          <span class="pay-sub">Apple Pay · Google Pay · Card</span>
        </button>
        <div class="cart-pay-or"><span>or</span></div>
        <div class="cart-pay-alt">
          <button type="button" class="btn btn-outline cart-pay-btn alt" id="payWithVenmo"${checkoutDisabled ? ' disabled' : ''}>
            <span class="pay-icon venmo">V</span>
            <span>Venmo</span>
          </button>
          <button type="button" class="btn btn-outline cart-pay-btn alt" id="payWithPaypal"${checkoutDisabled ? ' disabled' : ''}>
            <span class="pay-icon paypal">PP</span>
            <span>PayPal</span>
          </button>
        </div>
      </div>

      <p class="cart-ship-policy">Square handles shipping address automatically. Venmo / PayPal: we'll collect it in the next step.</p>
    `;

    document.getElementById('cartShipState')?.addEventListener('change', (e) => {
      skSaveShipState(e.target.value);
      renderDrawer();
    });

    document.getElementById('cartInsuranceOptIn')?.addEventListener('change', (e) => {
      skSetInsuranceOpted(e.target.checked);
      renderDrawer();
    });

    if (!checkoutDisabled) {
      document.getElementById('payWithSquare')?.addEventListener('click', () => payWithSquare(cart, shipping, shipState, insurance));
      document.getElementById('payWithVenmo')?.addEventListener('click',  () => openCustomerInfoModal('venmo', cart, subtotal, shipping, total, tax, insurance));
      document.getElementById('payWithPaypal')?.addEventListener('click', () => openCustomerInfoModal('paypal', cart, subtotal, shipping, total, tax, insurance));
    }

    // Promo: apply / remove handlers
    const promoApplyBtn = document.getElementById('cartPromoApply');
    const promoInput    = document.getElementById('cartPromoInput');
    const promoRemove   = document.getElementById('cartPromoRemove');
    if (promoApplyBtn && promoInput) {
      promoApplyBtn.addEventListener('click', () => applyPromoCode(promoInput.value));
      promoInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); applyPromoCode(promoInput.value); }
      });
    }
    if (promoRemove) {
      promoRemove.addEventListener('click', () => {
        skSetPromoState(null);
        renderDrawer();
      });
    }
  }

  // ─── Square: redirect to hosted checkout ──────────────────────────────────
  async function payWithSquare(cart, shipping, shippingState, insurance = 0) {
    const btn = document.getElementById('payWithSquare');
    if (!btn) return;
    btn.disabled = true;
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<span class="pay-label">Connecting to Square…</span>';

    try {
      const promo = skGetValidPromo(skCartSubtotal());
      const res = await fetch(`${SK_WORKER_BASE}/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: cart.map(i => ({
            name:        i.name,
            price:       i.price,
            quantity:    i.quantity,
            variationId: i.variationId,
          })),
          shippingCost:  shipping,
          insuranceCost: insurance,
          shippingState: shippingState || '',
          promo_code:    promo ? promo.code : undefined,
          returnUrl: `${window.location.origin}/order-confirmation.html?from=square`,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.url) {
        // If the failure is specifically about the promo code, surface that
        // and clear the stored promo so the user can re-enter or remove.
        if (data.error === 'promo_failed') {
          const reasonMsg = {
            already_redeemed: 'This code has already been used. Removing it from your cart.',
            below_min:        'Your subtotal dropped below the code minimum. Removing it.',
            expired:          'This code has expired. Removing it.',
            not_found:        'Code not found. Removing it.',
            disabled:         'This code is no longer active. Removing it.',
          }[data.reason] || 'Promo code issue — removed from cart. Try again or proceed without.';
          skSetPromoState(null);
          renderDrawer();
          alert(reasonMsg);
          btn.disabled = false;
          btn.innerHTML = originalHTML;
          return;
        }
        throw new Error(data.error || 'Could not reach Square');
      }
      // On success, the code is now used in D1. Clear local state so the
      // user can't try to use it again from the same browser.
      skSetPromoState(null);
      window.location.assign(data.url);
    } catch (err) {
      console.error('Square checkout failed:', err);
      btn.disabled = false;
      btn.innerHTML = originalHTML;
      alert('Sorry — Square checkout is having trouble right now. Try Venmo or PayPal, or reach out on Instagram.');
    }
  }

  // ─── Venmo / PayPal: show modal to collect customer + shipping info ──────
  function openCustomerInfoModal(provider, cart, subtotal, shipping, total, tax = 0, insurance = 0) {
    const label = provider === 'venmo' ? 'Venmo' : 'PayPal';
    const accent = provider === 'venmo' ? '#008cff' : '#003087';

    const modal = document.createElement('div');
    modal.className = 'pay-modal';
    modal.innerHTML = `
      <div class="pay-modal-panel">
        <button type="button" class="pay-modal-close" aria-label="Close">×</button>
        <h3>Pay with ${label}</h3>
        <p class="pay-modal-sub">We'll email ourselves your order details, then open ${label} with the total pre-filled. You'll complete payment in ${label} and we ship within 48 hours of receiving it.</p>

        <form id="payInfoForm" class="pay-modal-form">
          <label>Your name *<input type="text" name="name" required autocomplete="name" /></label>
          <label>Email *<input type="email" name="email" required autocomplete="email" /></label>
          <label>Shipping address *
            <textarea name="address" rows="3" required autocomplete="shipping street-address" placeholder="Street, city, state, ZIP"></textarea>
          </label>
          <label>Phone (optional)<input type="tel" name="phone" autocomplete="tel" /></label>

          <div class="pay-modal-totals">
            <div><span>Subtotal</span><span>${fmt(subtotal)}</span></div>
            <div><span>Shipping</span><span>${shipping === 0 ? 'Free' : fmt(shipping)}</span></div>
            ${insurance > 0 ? `<div><span>Shipping insurance</span><span>${fmt(insurance)}</span></div>` : ''}
            ${tax > 0 ? `<div><span>Tax (FL 6%)</span><span>${fmt(tax)}</span></div>` : ''}
            <div class="grand"><span>Total</span><span>${fmt(total)}</span></div>
          </div>

          <button type="submit" class="btn btn-primary pay-modal-submit" style="background:${accent}">
            Continue to ${label}
          </button>
        </form>
      </div>
    `;
    document.body.appendChild(modal);
    requestAnimationFrame(() => modal.classList.add('open'));

    const closeModal = () => {
      modal.classList.remove('open');
      setTimeout(() => modal.remove(), 250);
    };
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
    modal.querySelector('.pay-modal-close').addEventListener('click', closeModal);

    modal.querySelector('#payInfoForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = e.target;
      const fd = new FormData(form);
      const customer = {
        name:    (fd.get('name')    || '').toString().trim(),
        email:   (fd.get('email')   || '').toString().trim(),
        address: (fd.get('address') || '').toString().trim(),
        phone:   (fd.get('phone')   || '').toString().trim(),
      };

      const submitBtn = form.querySelector('.pay-modal-submit');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Sending order…';

      // Build order summary for email
      const itemLines = cart.map(i =>
        `${i.quantity} × ${i.name} @ ${fmt(i.price)} = ${fmt(i.price * i.quantity)}`
      ).join('\n');
      const shortNote = cart.length === 1
        ? `${cart[0].quantity} × ${cart[0].name}`
        : `${cart.length} items`;

      const payload = {
        access_key:  SK_WEB3FORMS_KEY,
        subject:     `Online Order (${label}) — ${customer.name} — ${fmt(total)}`,
        from_name:   'Sake Kitty Online Order',
        replyto:     customer.email,
        Name:        customer.name,
        Email:       customer.email,
        Phone:       customer.phone || '(not provided)',
        'Shipping Address': customer.address,
        'Payment Method':   label,
        'Order Items':      itemLines,
        Subtotal:    fmt(subtotal),
        Shipping:    shipping === 0 ? 'Free' : fmt(shipping),
        ...(insurance > 0 ? { 'Shipping Insurance': fmt(insurance) } : {}),
        ...(tax > 0 ? { Tax: fmt(tax) } : {}),
        Total:       fmt(total),
        _note:       'Payment is pending on customer side — they have been redirected to ' + label + '.',
      };

      try {
        const res = await fetch('https://api.web3forms.com/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify(payload),
        });
        const json = await res.json().catch(() => ({}));
        if (!res.ok || !json.success) throw new Error(json.message || 'Email submission failed');

        // Open the Venmo / PayPal link in a new tab
        const paymentUrl = provider === 'venmo'
          ? buildVenmoUrl(total, shortNote)
          : buildPaypalUrl(total);
        window.open(paymentUrl, '_blank', 'noopener');

        // Clear cart + show success state in the drawer
        skClearCart();
        closeModal();
        showDrawerOrderSuccess(label, customer.email);
      } catch (err) {
        console.error('Order submission failed:', err);
        submitBtn.disabled = false;
        submitBtn.textContent = `Continue to ${label}`;
        alert('Sorry — we could not send your order email. Please try again or reach out on Instagram @sakekittycards.');
      }
    });
  }

  function buildVenmoUrl(amount, note) {
    const params = new URLSearchParams({
      txn: 'pay',
      amount: amount.toFixed(2),
      note: `Sake Kitty order: ${note}`.slice(0, 280),
    });
    return `https://venmo.com/${SK_VENMO_HANDLE}?${params}`;
  }

  function buildPaypalUrl(amount) {
    return `https://www.paypal.me/${SK_PAYPAL_HANDLE}/${amount.toFixed(2)}`;
  }

  function showDrawerOrderSuccess(provider, email) {
    const body   = document.getElementById('cartBody');
    const footer = document.getElementById('cartFooter');
    if (!body || !footer) return;
    body.innerHTML = `
      <div class="cart-order-success">
        <div class="cart-order-check">✓</div>
        <h4>Order sent!</h4>
        <p>Your order details were emailed to us. A ${provider} payment page opened in a new tab — complete the payment there and we'll ship within 48 hours.</p>
        <p class="cart-order-email">Confirmation going to <strong>${email}</strong></p>
      </div>
    `;
    footer.innerHTML = `
      <a href="shop.html" class="btn btn-outline" style="width:100%;justify-content:center">Keep Shopping</a>
    `;
  }

  skCartListeners.add(() => {
    renderBadge();
    // Re-render whenever the cart visibly contains the cart UI: the drawer
    // when it's open, or the cart page (always).
    if (isCartPage) {
      renderDrawer();
    } else if (drawer?.classList.contains('open')) {
      renderDrawer();
    }
  });

  renderBadge();

  // On the cart page, render once on load so customers see their cart
  // immediately rather than empty containers.
  if (isCartPage) renderDrawer();
})();

// ─── Branded confirm modal ─────────────────────────────────────────────────
// Drop-in replacement for window.confirm() with the Sake Kitty look (logo,
// Bangers heading, orange-glow card, centered, ESC/Enter shortcuts, click-
// backdrop-to-cancel). Returns a Promise<boolean>. Used by Sell/Trade and
// Grading Prep "Clear All" buttons in place of the bare browser dialog.
//
//   const ok = await skConfirm({ title: 'Clear list?', body: '...', confirm: 'Clear', cancel: 'Keep' });
//
window.skConfirm = function skConfirm(opts) {
  const o = Object.assign({
    title:   'Are you sure?',
    body:    '',
    confirm: 'Confirm',
    cancel:  'Cancel',
    danger:  true,   // confirm button gets the orange/red look when true
  }, opts || {});
  return new Promise(resolve => {
    const backdrop = document.createElement('div');
    backdrop.setAttribute('role', 'dialog');
    backdrop.setAttribute('aria-modal', 'true');
    backdrop.style.cssText = [
      'position:fixed', 'inset:0',
      'background:rgba(0,0,0,0.72)',
      'backdrop-filter:blur(6px)',
      '-webkit-backdrop-filter:blur(6px)',
      'display:flex', 'align-items:center', 'justify-content:center',
      'z-index:9999',
      'padding:20px',
      'opacity:0',
      'transition:opacity .15s ease',
      'font-family:"Inter",sans-serif',
    ].join(';');
    backdrop.innerHTML = `
      <div style="
        position:relative;
        max-width:420px; width:100%;
        background:linear-gradient(180deg, rgba(255,106,0,0.08) 0%, rgba(20,12,28,0.96) 60%);
        border:1.5px solid rgba(255,106,0,0.45);
        border-radius:18px;
        box-shadow:0 0 0 1px rgba(255,106,0,0.12), 0 18px 60px rgba(0,0,0,0.6), 0 0 80px rgba(255,106,0,0.18);
        padding:28px 26px 22px;
        text-align:center;
        transform:scale(0.96);
        transition:transform .18s ease;
      ">
        <img src="logo.png" alt="Sake Kitty Cards" style="width:54px;height:54px;border-radius:50%;margin-bottom:12px;box-shadow:0 4px 20px rgba(255,106,0,0.35)" />
        <h3 style="
          font-family:'Bangers',cursive;
          font-size:30px; letter-spacing:.04em;
          margin:0 0 10px;
          background:linear-gradient(135deg, var(--orange,#ff6a00), var(--pink,#ff4e6a));
          -webkit-background-clip:text; background-clip:text;
          -webkit-text-fill-color:transparent;
          line-height:1.15;
          padding:0 6px 4px;
        ">${escapeHtml(o.title)}</h3>
        <p style="font-size:14px; color:rgba(255,255,255,0.78); line-height:1.55; margin:0 4px 22px">${escapeHtml(o.body)}</p>
        <div style="display:flex; gap:10px; justify-content:center; flex-wrap:wrap">
          <button data-skc="cancel" class="btn btn-outline btn-sm" style="min-width:120px;justify-content:center">${escapeHtml(o.cancel)}</button>
          <button data-skc="confirm" class="btn ${o.danger ? 'btn-primary' : 'btn-secondary'}" style="min-width:120px;justify-content:center">${escapeHtml(o.confirm)}</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);
    requestAnimationFrame(() => {
      backdrop.style.opacity = '1';
      backdrop.querySelector('div').style.transform = 'scale(1)';
    });

    function close(result) {
      backdrop.style.opacity = '0';
      backdrop.querySelector('div').style.transform = 'scale(0.96)';
      document.removeEventListener('keydown', onKey);
      setTimeout(() => { backdrop.remove(); resolve(result); }, 150);
    }
    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); close(false); }
      else if (e.key === 'Enter') { e.preventDefault(); close(true); }
    }
    backdrop.querySelector('[data-skc="confirm"]').addEventListener('click', () => close(true));
    backdrop.querySelector('[data-skc="cancel"]').addEventListener('click', () => close(false));
    backdrop.addEventListener('click', e => { if (e.target === backdrop) close(false); });
    document.addEventListener('keydown', onKey);
    backdrop.querySelector('[data-skc="confirm"]').focus();
  });

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
};

/* ── Shop FX: card press/hover ripple (ramps with hold/hover time) + ambient dots ──
   Pointer events drive it, so it works for BOTH desktop hover and a mobile
   press-and-hold: the ripple builds while the finger is down and the card opens
   on release (the normal link click fires on touchend). Honors reduced-motion;
   dots only render on the shop + product pages. */
(function skShopFx() {
  if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  // Intensity = how long you've kept hovering/holding cards: ramps 0->1 over 60s,
  // eases back 1->0 over the next 60s, then repeats.
  (function cardRipple() {
    let active = null, px = 0, py = 0;
    let elapsed = 0, last = performance.now(), nextSpawn = 0;
    const PEAK = 60, PERIOD = 120;

    const setPos = (e, card) => {
      const r = card.getBoundingClientRect();
      px = e.clientX - r.left; py = e.clientY - r.top;
    };
    const begin = (e) => {
      const c = e.target.closest && e.target.closest('.product-card:not(.sold-out)');
      if (!c) return;
      active = c;
      if (getComputedStyle(c).position === 'static') c.style.position = 'relative';
      setPos(e, c);
    };
    const end = (e) => {
      const c = e.target.closest && e.target.closest('.product-card');
      if (c && active === c && !c.contains(e.relatedTarget)) active = null;
    };
    // pointerover/out = desktop hover; pointerdown/up + cancel = mobile press-hold.
    document.addEventListener('pointerover', begin, true);
    document.addEventListener('pointerdown', begin, true);
    document.addEventListener('pointerout', end, true);
    document.addEventListener('pointerup', () => { active = null; }, true);
    document.addEventListener('pointercancel', () => { active = null; }, true);
    document.addEventListener('pointermove', (e) => { if (active) setPos(e, active); }, { passive: true });

    function spawn(card, intensity) {
      const s = document.createElement('span');
      s.className = 'sk-card-ripple';
      s.style.left = px + 'px';
      s.style.top = py + 'px';
      s.style.setProperty('--op', (0.08 + intensity * 0.22).toFixed(3));
      card.appendChild(s);
      setTimeout(() => s.remove(), 1100);
    }

    function tick(now) {
      const dt = (now - last) / 1000; last = now;
      if (active && document.contains(active)) elapsed += dt;
      else { active = null; elapsed = Math.max(0, elapsed - dt * 1.5); }
      const p = elapsed % PERIOD;
      const intensity = p <= PEAK ? p / PEAK : (PERIOD - p) / PEAK;
      if (active && !document.hidden) {
        nextSpawn -= dt * 1000;
        if (nextSpawn <= 0) { spawn(active, intensity); nextSpawn = 820 - intensity * 680; }
      }
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  })();

  // Ambient dots — shop + product pages only.
  (function dots() {
    if (!/\/(shop|product)\.html$/.test(location.pathname)) return;
    const layer = document.createElement('div');
    layer.id = 'sk-dots-layer';
    (document.body || document.documentElement).appendChild(layer);
    const COLORS = ['255,106,0', '255,0,128', '0,212,255', '123,47,255'];
    function dot() {
      if (document.hidden) return;
      const d = document.createElement('span');
      d.className = 'sk-dot';
      const size = (3 + Math.random() * 5).toFixed(1);
      d.style.width = d.style.height = size + 'px';
      d.style.left = (Math.random() * 100).toFixed(2) + 'vw';
      d.style.top = (Math.random() * 100).toFixed(2) + 'vh';
      d.style.setProperty('--c', COLORS[(Math.random() * COLORS.length) | 0]);
      d.style.animationDuration = (3.5 + Math.random() * 4).toFixed(1) + 's';
      layer.appendChild(d);
      setTimeout(() => d.remove(), 9000);
    }
    for (let i = 0; i < 5; i++) setTimeout(dot, i * 250);
    setInterval(dot, 750);
  })();
})();
