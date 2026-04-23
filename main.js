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

// Nav hamburger
const toggle = document.getElementById('navToggle');
const links  = document.getElementById('navLinks');
toggle?.addEventListener('click', () => links.classList.toggle('open'));
links?.querySelectorAll('a').forEach(a => a.addEventListener('click', () => links.classList.remove('open')));

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

// FAQ accordion
document.querySelectorAll('.faq-item').forEach(item => {
  item.querySelector('.faq-q')?.addEventListener('click', () => {
    const wasOpen = item.classList.contains('open');
    document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('open'));
    if (!wasOpen) item.classList.add('open');
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
    if (count >= UNLOCK_AT && !document.body.classList.contains('drip-unlocked')) {
      unlockPageDrip();
    }
  });
});

function unlockPageDrip() {
  document.body.classList.add('drip-unlocked');
  initPageDripSystem();
}

function initPageDripSystem() {
  if (document.querySelector('.page-drip-bg')) return;

  const container = document.createElement('div');
  container.className = 'page-drip-bg';
  document.body.appendChild(container);

  const COLORS = ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff', '#ff4e00'];

  function spawnDrip() {
    const color   = COLORS[Math.floor(Math.random() * COLORS.length)];
    const x       = 6 + Math.random() * 88; // 6–94% across
    const size    = 55 + Math.random() * 50;
    const docH    = document.documentElement.scrollHeight;
    const fallDur = Math.max(16, docH / 80); // slower on taller pages

    const blob = document.createElement('div');
    blob.className = 'page-drip-blob';
    blob.style.left   = x + 'vw';
    blob.style.width  = size + 'px';
    blob.style.height = size + 'px';
    blob.style.backgroundColor = color;
    blob.style.boxShadow = `0 0 22px ${color}`;
    blob.style.animationDuration = fallDur + 's';
    blob.style.setProperty('--fall-end', (docH - 40) + 'px');

    // Organic, non-spherical
    const r1 = 40 + Math.random() * 35;
    const r2 = 50 + Math.random() * 30;
    const r3 = 45 + Math.random() * 35;
    const r4 = 55 + Math.random() * 25;
    blob.style.borderRadius = `${r1}% ${r2}% ${r3}% ${r4}% / ${r4}% ${r3}% ${r2}% ${r1}%`;

    container.appendChild(blob);
    setTimeout(() => blob.remove(), (fallDur + 1) * 1000);
  }

  // Initial spawn + steady cadence
  for (let i = 0; i < 2; i++) setTimeout(spawnDrip, i * 2200);
  setInterval(spawnDrip, 3500);
}
