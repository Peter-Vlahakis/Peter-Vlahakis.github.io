/* Home: hero name load-in, hero video, About content, and the resume embed. */
(function () {
  'use strict';

  var Site = window.Site;
  var NAME_DELAY_MS = 250; // after fonts are ready
  var NAME_MS = 720;
  var WORD_STAGGER_MS = 100;
  var FONT_WAIT_MS = 2500; // do not hold the name back forever if a font stalls
  var NEAR = '300px 0px'; // start loading the resume just before it scrolls in
  // About sits directly under the full-height hero, so "near" would mean "at load".
  // Its media waits until the section is actually on screen, which keeps the first load light.
  var ON_SCREEN = '0px 0px -8px 0px';

  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var saveData = !!(navigator.connection && navigator.connection.saveData);
  var desktop = window.matchMedia('(min-width: 1024px)');

  // The email address is put together here at page load, so it never appears whole in a page or JSON file.
  var EMAIL = ['pvlahakis', 'utexas', 'edu'];
  // LinkedIn's "in" logo (the knocked-out letters show the button behind them)
  var LINKEDIN_ICON =
    '<svg class="about__icon" viewBox="-2 -2 28 28" width="22" height="22" aria-hidden="true" focusable="false"><path d="' +
    'M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414' +
    'v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926' +
    '-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 ' +
    '13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 ' +
    '24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>';

  function emailLink(className) {
    var address = EMAIL[0] + '@' + EMAIL.slice(1).join('.');
    var a = Site.el('a', className, address);
    a.href = 'mailto:' + address;
    return a;
  }

  // Footer: the "name [at] domain" text that shows without JavaScript becomes a working email link.
  Array.prototype.forEach.call(document.querySelectorAll('[data-email]'), function (node) {
    node.replaceWith(emailLink(null));
  });

  /* ----- Hero name ----- */

  var words = Array.prototype.slice.call(document.querySelectorAll('.hero__word'));

  function revealName() {
    words.forEach(function (word, index) {
      window.setTimeout(function () {
        window.Scramble.run(word, { duration: NAME_MS, mode: 'load' });
        word.classList.add('is-in');
      }, index * WORD_STAGGER_MS);
    });
  }

  if (!window.Scramble.isEnabled()) {
    words.forEach(function (word) {
      word.classList.add('is-in');
    });
  } else {
    var fontsReady = document.fonts ? document.fonts.ready : Promise.resolve();
    var giveUp = new Promise(function (resolve) {
      window.setTimeout(resolve, FONT_WAIT_MS);
    });
    Promise.race([fontsReady, giveUp]).then(function () {
      window.setTimeout(revealName, NAME_DELAY_MS);
    });
  }

  /* ----- Hero video: poster first, then the clip fades in over it ----- */

  var hero = document.querySelector('.hero');
  var poster = hero.querySelector('.hero__poster');
  var video = hero.querySelector('.hero__video');
  var pauseButton = hero.querySelector('.hero__pause');
  var pausedByUser = false;

  function play() {
    var attempt = video.play();
    if (attempt && attempt.catch) attempt.catch(function () {});
  }

  function attachVideo() {
    var small = window.matchMedia('(max-width: 767.98px)').matches;
    video.addEventListener(
      'canplaythrough',
      function () {
        video.classList.add('is-ready');
        pauseButton.hidden = false;
        if (!pausedByUser) play();
      },
      { once: true }
    );
    video.src = small ? video.getAttribute('data-src-small') : video.getAttribute('data-src-large');
    video.load();
  }

  function afterFirstPaint(callback) {
    function go() {
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(callback);
      });
    }
    if (poster.complete) go();
    else {
      poster.addEventListener('load', go, { once: true });
      poster.addEventListener('error', go, { once: true });
    }
  }

  // Poster only (no video request) under reduced motion or Save-Data.
  if (!reducedMotion.matches && !saveData) {
    afterFirstPaint(attachVideo);

    pauseButton.addEventListener('click', function () {
      pausedByUser = !pausedByUser;
      if (pausedByUser) video.pause();
      else play();
      pauseButton.textContent = pausedByUser ? 'Play' : 'Pause';
    });

    // Do not decode video nobody can see.
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        if (!video.classList.contains('is-ready') || pausedByUser) return;
        if (entries[0].isIntersecting) play();
        else video.pause();
      }).observe(hero);
    }
  }

  /* ----- About ----- */

  function whenNear(target, margin, callback) {
    if (!('IntersectionObserver' in window)) return callback();
    var observer = new IntersectionObserver(
      function (entries) {
        if (entries.some(function (entry) { return entry.isIntersecting; })) {
          observer.disconnect();
          callback();
        }
      },
      { rootMargin: margin }
    );
    observer.observe(target);
  }

  // Reserve each image's box now; attach its source when About approaches the viewport.
  function deferredImage(manifest, id, sizes) {
    var img = Site.image(manifest, id, { sizes: sizes });
    if (!img) return null;
    img.setAttribute('data-src', img.getAttribute('src'));
    img.setAttribute('data-srcset', img.getAttribute('srcset'));
    img.removeAttribute('src');
    img.removeAttribute('srcset');
    return img;
  }

  function activate(img) {
    img.setAttribute('srcset', img.getAttribute('data-srcset'));
    img.setAttribute('src', img.getAttribute('data-src'));
    img.removeAttribute('data-srcset');
    img.removeAttribute('data-src');
  }

  // Copy: **double asterisks** bold words; [words](page.html) links to another page of the site.
  function rich(tag, className, words) {
    var node = Site.el(tag, className);
    var pattern = /\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
    var last = 0;
    var match;
    while ((match = pattern.exec(words))) {
      if (match.index > last) node.appendChild(document.createTextNode(words.slice(last, match.index)));
      if (match[1]) {
        node.appendChild(Site.el('strong', null, match[1]));
      } else {
        var link = Site.el('a', 'about__inline-link', match[2]);
        link.href = match[3];
        node.appendChild(link);
      }
      last = pattern.lastIndex;
    }
    if (last < words.length) node.appendChild(document.createTextNode(words.slice(last)));
    return node;
  }

  // Name, subtitle (its " · " separators in white), and the contact buttons: email, then the LinkedIn icon
  function renderIdentity(about) {
    var box = document.getElementById('about-id');
    box.appendChild(Site.el('h3', 'about__name', about.name));
    var subtitle = Site.el('p', 'about__subtitle');
    about.subtitle.split(' · ').forEach(function (part, index) {
      if (index) subtitle.appendChild(Site.el('span', 'about__sep', ' · '));
      subtitle.appendChild(document.createTextNode(part));
    });
    box.appendChild(subtitle);
    var links = Site.el('ul', 'about__links');
    about.links.forEach(function (link) {
      var a;
      if (link.kind === 'email') {
        a = emailLink('about__button');
      } else {
        a = Site.el('a', 'about__button about__button--icon');
        a.href = link.href;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.setAttribute('aria-label', link.label);
        a.insertAdjacentHTML('beforeend', LINKEDIN_ICON);
      }
      var item = Site.el('li');
      item.appendChild(a);
      links.appendChild(item);
    });
    box.appendChild(links);
  }

  // One paragraph: beside the headshot on wide screens, under the header on phones (css/home.css)
  function renderBio(about) {
    document.getElementById('about-bio').appendChild(rich('p', 'about__text', Site.text(about.bio)));
  }

  // Life in Motion: heading, a one-line intro, then the photos
  function renderMotion(about, gallery) {
    var wrap = document.getElementById('about-motion');
    wrap.appendChild(Site.el('h3', 'about__heading', about.gallery_title));
    wrap.appendChild(rich('p', 'about__text', about.gallery_intro));
    wrap.appendChild(gallery);
  }

  /* ----- Gallery: justified rows. Every row fills the width exactly and every photo keeps its whole
     shape, so row heights differ a little. Breaks are recomputed whenever the width changes. ----- */

  function targetRowHeight(width) {
    if (desktop.matches) return 220;
    return width < 600 ? 170 : 250;
  }

  /*
   * Split the photos, in order, into rows whose heights stay near the target. joined[k] means photos k
   * and k + 1 must share a row. A row of only portraits or only landscapes costs a little more, so mixed
   * rows win close calls.
   */
  function justify(tiles, width, gap, target, joined) {
    var n = tiles.length;
    var best = [0];
    var from = [];
    for (var end = 1; end <= n; end++) {
      best[end] = Infinity;
      if (end < n && joined[end - 1]) continue;
      var ratios = 0;
      var portraits = 0;
      for (var start = end - 1; start >= 0 && end - start <= 7; start--) {
        ratios += tiles[start].ratio;
        if (tiles[start].ratio < 1) portraits += 1;
        if (start > 0 && joined[start - 1]) continue;
        var count = end - start;
        var height = (width - (count - 1) * gap) / ratios;
        var cost = Math.pow((height - target) / target, 2);
        if (count > 1 && (portraits === 0 || portraits === count)) cost += 0.04;
        if (best[start] + cost < best[end]) {
          best[end] = best[start] + cost;
          from[end] = start;
        }
      }
    }
    var rows = [];
    for (var stop = n; stop > 0; stop = from[stop]) rows.unshift(tiles.slice(from[stop], stop));
    return rows;
  }

  function galleryLayout(gallery, tiles, joined) {
    var laidOut = 0;
    function layout() {
      var width = gallery.clientWidth;
      if (!width || width === laidOut) return;
      laidOut = width;
      var gap = parseFloat(getComputedStyle(gallery).rowGap) || 0;
      var rows = justify(tiles, width, gap, targetRowHeight(width), joined);
      gallery.textContent = '';
      rows.forEach(function (row) {
        var line = Site.el('div', 'gallery__row');
        var ratios = row.reduce(function (sum, tile) { return sum + tile.ratio; }, 0);
        var height = (width - (row.length - 1) * gap) / ratios;
        row.forEach(function (tile) {
          // flex-grow in proportion to the shape: each photo is height x ratio wide, the row exactly full
          tile.node.style.flexGrow = tile.ratio;
          tile.img.sizes = Math.ceil(height * tile.ratio) + 'px';
          line.appendChild(tile.node);
        });
        gallery.appendChild(line);
      });
    }
    layout();
    var pending = 0;
    function schedule() {
      if (!pending) pending = window.requestAnimationFrame(function () { pending = 0; layout(); });
    }
    if ('ResizeObserver' in window) new ResizeObserver(schedule).observe(gallery);
    else window.addEventListener('resize', schedule);
  }

  function renderAbout(site, manifest) {
    var about = site.about;
    var section = document.getElementById('about');
    var pending = [];

    var portrait = deferredImage(manifest, about.headshot, '(min-width: 768px) 240px, 60vw');
    if (portrait) {
      document.getElementById('portrait').appendChild(portrait);
      pending.push(portrait);
    }
    renderIdentity(about);
    renderBio(about);

    // Photos open the expanded view at full quality, with no caption.
    var gallery = document.getElementById('gallery');
    var position = {};
    var tiles = [];
    about.gallery.forEach(function (id) {
      var img = deferredImage(manifest, id, '33vw');
      if (!img) return;
      var tile = Site.el('div', 'gallery__tile');
      tile.style.aspectRatio = img.width + ' / ' + img.height;
      tile.appendChild(Site.zoomable(img, manifest[id], ''));
      position[id] = tiles.length;
      tiles.push({ node: tile, img: img, ratio: img.width / img.height });
      pending.push(img);
    });
    var joined = [];
    (about.keep_together || []).forEach(function (pair) {
      var a = position[pair[0]];
      var b = position[pair[1]];
      if (a != null && b === a + 1) joined[a] = true;
    });

    renderMotion(about, gallery);
    galleryLayout(gallery, tiles, joined);

    whenNear(section, ON_SCREEN, function () {
      pending.forEach(activate);
    });

    // The sections below moved when this content arrived; honour a #hash in the address.
    if (location.hash.length > 1) {
      var target = document.getElementById(location.hash.slice(1));
      if (target) target.scrollIntoView({ behavior: 'auto' });
    }
  }

  Promise.all([Site.getJSON('data/site.json'), Site.getJSON('data/manifest.json')])
    .then(function (data) {
      renderAbout(data[0], data[1]);
    })
    .catch(function () {
      Site.fail(document.getElementById('about-motion'), 'About content could not be loaded.');
    });

  /* ----- Resume: inline PDF on wide screens; phones keep the download button and a plain link ----- */

  var frame = document.getElementById('resume-frame');

  function embedResume() {
    var pdf = document.createElement('object');
    pdf.type = 'application/pdf';
    pdf.data = frame.getAttribute('data-src') + '#view=FitH';
    pdf.setAttribute('aria-label', 'Resume of Peter Vlahakis (PDF)');
    pdf.tabIndex = 0;
    while (frame.firstChild) pdf.appendChild(frame.firstChild); // the plain link becomes the fallback content
    frame.appendChild(pdf);
  }

  if (window.matchMedia('(min-width: 768px)').matches) whenNear(frame, NEAR, embedResume);
})();
