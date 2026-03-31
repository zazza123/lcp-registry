/* ==========================================================================
   Component loader — injects header.html & footer.html
   ========================================================================== */

async function loadComponents() {
  var slots = [
    { id: 'header-placeholder', path: 'components/header.html' },
    { id: 'footer-placeholder', path: 'components/footer.html' },
  ];

  await Promise.all(
    slots.map(async function (slot) {
      var el = document.getElementById(slot.id);
      if (!el) return;
      try {
        var res = await fetch(slot.path);
        if (!res.ok) throw new Error(res.statusText);
        el.outerHTML = await res.text();
      } catch (e) {
        console.warn('[components] Failed to load ' + slot.path, e);
      }
    })
  );
}

function initMobileMenu() {
  var btn = document.querySelector('.header__menu-btn');
  var nav = document.querySelector('.header__nav');
  if (!btn || !nav) return;

  btn.addEventListener('click', function () {
    var open = nav.classList.toggle('is-open');
    btn.setAttribute('aria-expanded', open);
  });

  nav.querySelectorAll('.nav__link').forEach(function (link) {
    link.addEventListener('click', function () {
      nav.classList.remove('is-open');
      btn.setAttribute('aria-expanded', 'false');
    });
  });
}
