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

// ── Paint splatter on button clicks ──
const PAINT_COLORS = ['#ff6a00', '#ff0080', '#7b2fff', '#00d4ff', '#ffcc00', '#ff4e00'];

function paintSplatter(x, y) {
  const frag = document.createDocumentFragment();
  const count = 10 + Math.floor(Math.random() * 5); // 10–14 drops

  for (let i = 0; i < count; i++) {
    const drop = document.createElement('div');
    drop.className = 'paint-drop';
    const color = PAINT_COLORS[Math.floor(Math.random() * PAINT_COLORS.length)];
    const size = 5 + Math.random() * 13;
    const angle = Math.random() * Math.PI * 2;
    const distance = 35 + Math.random() * 90;
    const rot = (Math.random() - 0.5) * 120;

    drop.style.backgroundColor = color;
    drop.style.boxShadow = `0 0 8px ${color}`;
    drop.style.left = x + 'px';
    drop.style.top  = y + 'px';
    drop.style.width  = size + 'px';
    drop.style.height = size + 'px';
    drop.style.setProperty('--dx',  Math.cos(angle) * distance + 'px');
    drop.style.setProperty('--dy',  Math.sin(angle) * distance + 'px');
    drop.style.setProperty('--rot', rot + 'deg');

    // Organic blob shape (asymmetric border-radius values)
    drop.style.borderRadius =
      `${40 + Math.random()*40}% ${55 + Math.random()*35}% ` +
      `${50 + Math.random()*30}% ${45 + Math.random()*35}%`;

    frag.appendChild(drop);
    setTimeout((d) => d.remove(), 900, drop);
  }
  document.body.appendChild(frag);
}

document.addEventListener('click', (e) => {
  // Splatter on page-content action buttons only — NOT on nav-scoped buttons,
  // which would visually spill outside the nav frame.
  if (e.target.closest('.site-nav')) return;
  const target = e.target.closest(
    '.btn-primary, .btn-venmo, .btn-paypal, .btn-paylater, .btn-tcg, .btn-outline, .qty-btn'
  );
  if (!target) return;
  paintSplatter(e.clientX, e.clientY);
});

// Make the in-nav lava blobs clickable — click to "catch" one (pause + glow)
document.querySelectorAll('.nav-lava-blob').forEach(blob => {
  blob.addEventListener('click', (e) => {
    e.stopPropagation();
    blob.classList.add('caught');
    setTimeout(() => blob.classList.remove('caught'), 650);
  });
});
