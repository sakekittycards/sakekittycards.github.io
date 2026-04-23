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

// ═══════════════════════════════════════════════════════════════════════════
// Cart state + drawer UI
// ═══════════════════════════════════════════════════════════════════════════

const SK_CART_KEY        = 'sk_cart_v1';
const SK_SHIP_FREE_OVER  = 50;
const SK_SHIP_FLAT_FEE   = 5;
const SK_WORKER_BASE     = 'https://sakekitty-square.nwilliams23999.workers.dev';
const SK_VENMO_HANDLE    = 'sakekittycards';
const SK_PAYPAL_HANDLE   = 'sakekittycards';
const SK_WEB3FORMS_KEY   = 'd42c7cee-c136-4450-989f-6ec666f79d3a';

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
function skAddToCart(product) {
  if (!product || !product.id) return;
  const cart = skGetCart();
  const existing = cart.find(item => item.id === product.id);
  if (existing) {
    existing.quantity = Math.min(99, existing.quantity + 1);
  } else {
    cart.push({
      id:          product.id,
      variationId: product.variationId || product.id,
      name:        String(product.name || 'Item'),
      price:       Number(product.price) || 0,
      imageUrl:    product.imageUrl || null,
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
    item.quantity = Math.min(99, qty);
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
function skShippingCost(subtotal) {
  if (subtotal <= 0) return 0;
  return subtotal >= SK_SHIP_FREE_OVER ? 0 : SK_SHIP_FLAT_FEE;
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

  // 2) Drawer + backdrop at end of body
  if (!document.getElementById('cartDrawer')) {
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
        <button type="button" class="cart-drawer-close" id="cartClose" aria-label="Close cart">×</button>
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
    drawer.classList.add('open');
    backdrop.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('cart-open');
    renderDrawer();
  }
  function close() {
    drawer.classList.remove('open');
    backdrop.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('cart-open');
  }
  cartBtn?.addEventListener('click', open);
  backdrop?.addEventListener('click', close);
  closeBtn?.addEventListener('click', close);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && drawer.classList.contains('open')) close();
  });

  function fmt(n) { return `$${(Math.round(n * 100) / 100).toFixed(2)}`; }

  function renderBadge() {
    const badge = document.getElementById('navCartBadge');
    if (!badge) return;
    const count = skCartCount();
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.hidden = count === 0;
  }

  function renderDrawer() {
    const body   = document.getElementById('cartBody');
    const footer = document.getElementById('cartFooter');
    if (!body || !footer) return;

    const cart = skGetCart();

    if (cart.length === 0) {
      body.innerHTML = `
        <div class="cart-empty">
          <div class="cart-empty-icon">🛒</div>
          <h4>Your cart is empty</h4>
          <p>Head to the shop to add plushies, cards, and more.</p>
          <a href="shop.html" class="btn btn-primary btn-sm">Shop Now</a>
        </div>
      `;
      footer.innerHTML = '';
      return;
    }

    body.innerHTML = cart.map(item => {
      const thumb = item.imageUrl
        ? `<img src="${item.imageUrl}" alt="" class="cart-item-img" onerror="this.style.visibility='hidden'" />`
        : `<div class="cart-item-img placeholder">📦</div>`;
      return `
        <div class="cart-item" data-id="${item.id}">
          ${thumb}
          <div class="cart-item-info">
            <h5>${item.name}</h5>
            <div class="cart-item-price">${fmt(item.price)} each</div>
            <div class="cart-item-controls">
              <div class="cart-qty-group">
                <button type="button" class="cart-qty-btn" data-action="dec" aria-label="Decrease">−</button>
                <span class="cart-qty-num">${item.quantity}</span>
                <button type="button" class="cart-qty-btn" data-action="inc" aria-label="Increase">+</button>
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
    const total     = subtotal + shipping;
    const remaining = SK_SHIP_FREE_OVER - subtotal;

    footer.innerHTML = `
      ${shipping > 0
        ? `<div class="cart-ship-note">Add <strong>${fmt(Math.max(0, remaining))}</strong> more for free shipping</div>`
        : `<div class="cart-ship-note free">✓ You've unlocked free shipping</div>`}
      <div class="cart-totals-row"><span>Subtotal</span><span>${fmt(subtotal)}</span></div>
      <div class="cart-totals-row"><span>Shipping</span><span>${shipping === 0 ? 'Free' : fmt(shipping)}</span></div>
      <div class="cart-totals-row grand"><span>Total</span><span>${fmt(total)}</span></div>

      <div class="cart-pay-options">
        <button type="button" class="btn btn-primary cart-pay-btn" id="payWithSquare">
          <span class="pay-label">Pay with Square</span>
          <span class="pay-sub">Apple Pay · Google Pay · Card</span>
        </button>
        <div class="cart-pay-or"><span>or</span></div>
        <div class="cart-pay-alt">
          <button type="button" class="btn btn-outline cart-pay-btn alt" id="payWithVenmo">
            <span class="pay-icon venmo">V</span>
            <span>Venmo</span>
          </button>
          <button type="button" class="btn btn-outline cart-pay-btn alt" id="payWithPaypal">
            <span class="pay-icon paypal">PP</span>
            <span>PayPal</span>
          </button>
        </div>
      </div>

      <p class="cart-ship-policy">Square handles shipping address automatically. Venmo / PayPal: we'll collect it in the next step.</p>
    `;

    document.getElementById('payWithSquare')?.addEventListener('click', () => payWithSquare(cart, shipping));
    document.getElementById('payWithVenmo')?.addEventListener('click',  () => openCustomerInfoModal('venmo', cart, subtotal, shipping, total));
    document.getElementById('payWithPaypal')?.addEventListener('click', () => openCustomerInfoModal('paypal', cart, subtotal, shipping, total));
  }

  // ─── Square: redirect to hosted checkout ──────────────────────────────────
  async function payWithSquare(cart, shipping) {
    const btn = document.getElementById('payWithSquare');
    if (!btn) return;
    btn.disabled = true;
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<span class="pay-label">Connecting to Square…</span>';

    try {
      const res = await fetch(`${SK_WORKER_BASE}/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: cart.map(i => ({
            name: i.name,
            price: i.price,
            quantity: i.quantity,
          })),
          shippingCost: shipping,
          returnUrl: `${window.location.origin}/order-confirmation.html?from=square`,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.url) {
        throw new Error(data.error || 'Could not reach Square');
      }
      window.location.assign(data.url);
    } catch (err) {
      console.error('Square checkout failed:', err);
      btn.disabled = false;
      btn.innerHTML = originalHTML;
      alert('Sorry — Square checkout is having trouble right now. Try Venmo or PayPal, or reach out on Instagram.');
    }
  }

  // ─── Venmo / PayPal: show modal to collect customer + shipping info ──────
  function openCustomerInfoModal(provider, cart, subtotal, shipping, total) {
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
    if (drawer.classList.contains('open')) renderDrawer();
  });

  renderBadge();
})();
