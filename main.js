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
  const target = e.target.closest(
    '.btn-primary, .btn-venmo, .btn-paypal, .btn-paylater, .btn-tcg, .nav-cta, .btn-outline, .qty-btn'
  );
  if (!target) return;
  paintSplatter(e.clientX, e.clientY);
});

// Nav logo — extra splatter on click (kind of a brand easter egg)
document.querySelector('.nav-logo')?.addEventListener('click', (e) => {
  const rect = e.currentTarget.getBoundingClientRect();
  paintSplatter(rect.left + rect.width / 2, rect.top + rect.height / 2);
});
