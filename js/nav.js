/* Navigation: hover scramble, mobile menu toggle, and (on Home) section tracking. */
(function () {
  'use strict';

  var HOVER_MS = 350;
  var SPY_LINE = 0.42; // a section is current once its top passes 42% of the viewport height
  var nav = document.querySelector('.nav');
  if (!nav) return;

  var links = Array.prototype.slice.call(nav.querySelectorAll('.nav__link'));
  var toggle = nav.querySelector('.nav__toggle');
  var isHome = document.body.getAttribute('data-page') === 'home';

  // Browser chrome colour follows the --bg token, so the palette lives in one file.
  var bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
  if (bg) {
    var meta = document.createElement('meta');
    meta.name = 'theme-color';
    meta.content = bg;
    document.head.appendChild(meta);
  }

  links.forEach(function (link) {
    link.addEventListener('mouseenter', function () {
      window.Scramble.run(link, { duration: HOVER_MS, mode: 'hover' });
    });
  });

  /* ----- Mobile menu ----- */

  function setOpen(open) {
    nav.setAttribute('data-open', open ? 'true' : 'false');
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.textContent = open ? 'Close' : 'Menu';
    document.documentElement.style.overflow = open ? 'hidden' : '';
  }

  if (toggle) {
    toggle.addEventListener('click', function () {
      setOpen(nav.getAttribute('data-open') !== 'true');
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && nav.getAttribute('data-open') === 'true') {
        setOpen(false);
        toggle.focus();
      }
    });
    window.matchMedia('(min-width: 768px)').addEventListener('change', function () {
      setOpen(false);
    });
    links.forEach(function (link) {
      link.addEventListener('click', function () {
        setOpen(false);
      });
    });
  }

  if (!isHome) return;

  /* ----- Home: About and Resume are sections of this page ----- */

  // Map each nav link that targets this page to its section ("" = top of page).
  var tracked = [];
  links.forEach(function (link) {
    var url = new URL(link.href);
    var file = url.pathname.split('/').pop();
    if (file !== '' && file !== 'index.html') return;
    var section = url.hash ? document.getElementById(url.hash.slice(1)) : document.getElementById('top');
    if (section) tracked.push({ link: link, section: section, hash: url.hash });
  });

  // Scroll in place instead of reloading when the address is "/" rather than "/index.html".
  tracked.forEach(function (item) {
    item.link.addEventListener('click', function (event) {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      history.pushState(null, '', item.hash || location.pathname + location.search);
      if (item.hash) item.section.scrollIntoView();
      else window.scrollTo(0, 0);
    });
  });

  var ticking = false;

  function updateCurrent() {
    ticking = false;
    var line = window.innerHeight * SPY_LINE;
    var current = tracked[0];
    tracked.forEach(function (item) {
      if (item.section.getBoundingClientRect().top <= line) current = item;
    });
    tracked.forEach(function (item) {
      if (item === current) item.link.setAttribute('aria-current', item.hash ? 'true' : 'page');
      else item.link.removeAttribute('aria-current');
    });
  }

  function requestUpdate() {
    if (!ticking) {
      ticking = true;
      window.requestAnimationFrame(updateCurrent);
    }
  }

  window.addEventListener('scroll', requestUpdate, { passive: true });
  window.addEventListener('resize', requestUpdate);
  updateCurrent();
})();
