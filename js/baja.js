/* Baja SAE: builds the timeline (left) and the story (right) from data/baja.json and keeps them in step. */
(function () {
  'use strict';

  var Site = window.Site;
  var el = Site.el;
  var side = document.querySelector('.bt');
  var list = document.getElementById('timeline');
  var pane = document.getElementById('pane');
  var wide = window.matchMedia('(min-width: 768px)');
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  var SPY_LINE = 0.35; // a section is current once its top passes 35% of the visible story area
  var PANE = '(100vw - 400px)';
  var SIZES = {
    feature: '(min-width: 1500px) 1100px, (min-width: 768px) calc' + PANE + ', 100vw',
    stack: '(min-width: 1500px) 1100px, (min-width: 768px) calc' + PANE + ', 100vw',
    pair: '(min-width: 768px) calc(' + PANE + ' / 2), 100vw',
    grid: '(min-width: 1500px) 400px, (min-width: 1100px) calc(' + PANE + ' / 3), (min-width: 768px) calc(' + PANE + ' / 2), 50vw',
    row: '(min-width: 1500px) 800px, (min-width: 768px) calc(' + PANE + ' * 0.66), 100vw',
    mosaic: '(min-width: 768px) calc(' + PANE + ' / 2), 100vw',
    logo: '120px'
  };

  var manifest = {};
  var model = {};
  var stops = []; // { link, section, group } in page order
  var groups = {}; // group id -> { heading, element }
  var ticking = false;

  /* ----- Small builders ----- */

  function text(value) {
    return Site.text(value);
  }

  // The team logo sits in the nav row on this page only, and opens the team site in a new tab.
  function navLogo(link) {
    var nav = document.querySelector('.nav');
    var img = Site.image(manifest, link.image, { sizes: SIZES.logo, eager: true });
    if (!nav || !img) return;
    img.alt = '';
    var a = el('a', 'nav__team');
    a.href = link.href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.setAttribute('aria-label', link.label + ' (opens in a new tab)');
    a.appendChild(el('span', 'nav__team-logo')).appendChild(img);
    a.insertAdjacentHTML(
      'beforeend',
      '<svg class="nav__team-arrow" viewBox="0 0 12 12" aria-hidden="true" focusable="false"><path d="M3.5 2.5h6v6M9.5 2.5 2.5 9.5"/></svg>'
    );
    nav.insertBefore(a, nav.firstChild);
  }

  // Pause/Play control for anything that moves on its own (WCAG 2.2.2).
  function toggleButton(label) {
    var button = el('button', 'media-toggle');
    button.type = 'button';
    button.setAttribute('data-label', label);
    return button;
  }

  function setToggle(button, playing) {
    button.textContent = playing ? 'Pause' : 'Play';
    button.setAttribute('aria-label', (playing ? 'Pause ' : 'Play ') + button.getAttribute('data-label'));
  }

  function caption(item, extra) {
    var words = text(item.caption);
    if (!words && !extra) return null;
    var cap = el('figcaption', 'caption');
    if (words) cap.appendChild(el('span', 'caption__text', words));
    if (extra) cap.appendChild(extra);
    return cap;
  }

  // Click to expand. Animations open animated, or still if they are paused here.
  function openable(img, entry, item) {
    var button = el('button', 'bfig__open');
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'dialog');
    button.appendChild(el('span', 'visually-hidden', 'View larger: '));
    button.appendChild(img);
    button.addEventListener('click', function () {
      var still = entry.animated && img.getAttribute('srcset') === entry.poster.srcset;
      var source = still ? { src: entry.poster.src, srcset: entry.poster.srcset, width: entry.width, height: entry.height } : entry;
      var big = Site.largest(source);
      Site.expand(
        {
          src: big.src,
          width: big.width,
          height: big.height,
          alt: entry.alt,
          caption: text(item.caption),
          credit: entry.credit,
          preview: img.currentSrc || img.src
        },
        button
      );
    });
    return button;
  }

  // The image, its expand button, and the photographer credit in its bottom-left corner.
  function mediaBox(img, entry, item, className) {
    var box = el('div', className || 'bfig__media');
    box.appendChild(openable(img, entry, item));
    var tag = Site.creditTag(entry.credit);
    if (tag) box.appendChild(tag);
    return box;
  }

  // Animated images start as their still poster under reduced motion; the button swaps them.
  function animatedImage(entry, sizes) {
    var img = Site.image({ a: entry }, 'a', { sizes: sizes });
    var button = toggleButton('animation: ' + entry.alt);
    var playing = !reducedMotion.matches;
    function show() {
      var source = playing ? entry : entry.poster;
      img.setAttribute('srcset', source.srcset);
      img.setAttribute('src', source.src);
      setToggle(button, playing);
    }
    button.addEventListener('click', function () {
      playing = !playing;
      show();
    });
    show();
    return { img: img, button: button };
  }

  function figure(item, sizes) {
    var entry = manifest[item.image];
    if (!entry) return null;
    var fig = el('figure', 'bfig');
    fig.style.setProperty('--ar', (entry.width / entry.height).toFixed(4)); // used by the row layout
    var extra = null;
    var img;
    if (entry.animated) {
      var anim = animatedImage(entry, sizes);
      img = anim.img;
      extra = anim.button;
    } else {
      var native = !!item.native;
      img = Site.image(manifest, item.image, { sizes: native ? entry.width + 'px' : sizes, native: native });
    }
    fig.appendChild(mediaBox(img, entry, item));
    var cap = caption(item, extra);
    if (cap) fig.appendChild(cap);
    return fig;
  }

  // Muted clip that plays while on screen, with a Pause button. Under reduced motion it waits for Play.
  function videoFigure(block) {
    var entry = manifest[block.video];
    if (!entry || !entry.video) return null;
    var fig = el('figure', 'bfig bfig--video');
    var video = document.createElement('video');
    video.muted = true;
    video.loop = true;
    video.playsInline = true;
    video.preload = 'none';
    video.setAttribute('playsinline', '');
    video.width = entry.width;
    video.height = entry.height;
    video.poster = entry.poster.src;
    video.setAttribute('aria-label', entry.alt);
    var source = document.createElement('source');
    source.src = entry.src;
    source.type = entry.type || 'video/mp4';
    video.appendChild(source);
    fig.appendChild(video);

    var button = toggleButton('video: ' + entry.alt);
    // Poster only (no video request) under reduced motion or Save-Data, until Play is pressed
    var saveData = !!(navigator.connection && navigator.connection.saveData);
    var userPaused = reducedMotion.matches || saveData;
    var visible = false;
    function update() {
      var shouldPlay = visible && !userPaused;
      if (shouldPlay && video.paused) {
        var attempt = video.play();
        if (attempt && attempt.catch) attempt.catch(function () {});
      } else if (!shouldPlay && !video.paused) {
        video.pause();
      }
      setToggle(button, !userPaused);
    }
    button.addEventListener('click', function () {
      userPaused = !userPaused;
      update();
    });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting;
        update();
      }, { threshold: 0.4 }).observe(video);
    }
    setToggle(button, !userPaused);
    var cap = caption({ caption: block.caption }, button);
    if (cap) fig.appendChild(cap);
    return fig;
  }

  function modelSlot() {
    var viewer = document.createElement('model-viewer');
    viewer.className = 'bfig bfig--model';
    viewer.setAttribute('src', model.src);
    viewer.setAttribute('alt', model.alt);
    viewer.setAttribute('camera-controls', '');
    viewer.setAttribute('loading', 'lazy');
    var script = document.createElement('script');
    script.type = 'module';
    script.src = model.script;
    document.head.appendChild(script);
    return viewer;
  }

  /* ----- Content blocks ----- */

  var BLOCKS = {
    sub: function (b) {
      return el('h3', 'bsub', text(b.text));
    },
    text: function (b) {
      return el('p', 'btext', text(b.text));
    },
    goals: function (b) {
      var ol = el('ol', 'goals');
      b.items.forEach(function (item, index) {
        var li = el('li', 'goal');
        li.appendChild(el('span', 'goal__num', (index < 9 ? '0' : '') + (index + 1)));
        li.appendChild(el('span', 'goal__text', text(item)));
        ol.appendChild(li);
      });
      return ol;
    },
    points: function (b) {
      var wrap = el('div', 'bpoints');
      if (b.title) wrap.appendChild(el('p', 'label bpoints__title', b.title));
      var ul = el('ul', 'points');
      b.items.forEach(function (item) {
        ul.appendChild(el('li', null, text(item)));
      });
      wrap.appendChild(ul);
      return wrap;
    },
    specs: function (b) {
      var dl = el('dl', 'kv');
      b.rows.forEach(function (row) {
        var div = el('div', 'kv__row');
        div.appendChild(el('dt', 'label', row[0]));
        div.appendChild(el('dd', null, text(row[1])));
        dl.appendChild(div);
      });
      return dl;
    },
    table: function (b) {
      var wrap = el('div', 'btable-wrap');
      var table = el('table', 'btable');
      var head = el('thead');
      var tr = el('tr');
      b.head.forEach(function (cell) {
        var th = el('th', 'label', cell);
        th.scope = 'col';
        tr.appendChild(th);
      });
      head.appendChild(tr);
      table.appendChild(head);
      var body = el('tbody');
      b.rows.forEach(function (row) {
        var r = el('tr');
        row.forEach(function (cell, i) {
          var c = el(i === 0 ? 'th' : 'td', null, text(cell));
          if (i === 0) c.scope = 'row';
          r.appendChild(c);
        });
        body.appendChild(r);
      });
      table.appendChild(body);
      wrap.appendChild(table);
      return wrap;
    },
    list: function (b) {
      var wrap = el('div', 'blist');
      if (b.title) wrap.appendChild(el('p', 'label blist__title', b.title));
      var ul = el('ul', 'blist__items');
      b.items.forEach(function (item) {
        ul.appendChild(el('li', null, text(item)));
      });
      wrap.appendChild(ul);
      return wrap;
    },
    media: function (b) {
      var layout = b.layout || 'grid';
      var wrap = el('div', 'bmedia bmedia--' + layout);
      var count = 0;
      var ratios = 0;
      var cap = Infinity;
      b.items.forEach(function (item) {
        var fig = figure(item, SIZES[layout] || SIZES.grid);
        if (!fig) return;
        var entry = manifest[item.image];
        count += 1;
        ratios += entry.width / entry.height;
        if (item.native) cap = Math.min(cap, Site.largest(entry).height);
        wrap.appendChild(fig);
      });
      if (!count) return null;
      // Row: one line, every image the same height, sized in CSS from these numbers.
      if (layout === 'row') {
        wrap.style.setProperty('--n', count);
        wrap.style.setProperty('--sum', ratios.toFixed(4));
        if (cap !== Infinity) wrap.style.setProperty('--row-cap', cap + 'px');
        if (b.height === 'tile') wrap.classList.add('bmedia--tile-height');
      }
      return wrap;
    },
    video: videoFigure
  };

  /* ----- Sections ----- */

  function sectionHead(eyebrow, title, id, chip) {
    var head = el('header', 'bsec__head');
    if (eyebrow) head.appendChild(el('p', 'bsec__eyebrow', eyebrow));
    var h = el('h2', 'bsec__title', title);
    h.id = id + '-title';
    head.appendChild(h);
    if (chip) head.appendChild(el('p', 'chip bsec__chip', chip));
    return head;
  }

  function storySection(sec, groupLabel) {
    var section = el('section', 'bsec');
    section.id = sec.id;
    section.setAttribute('aria-labelledby', sec.id + '-title');
    section.appendChild(sectionHead(groupLabel, sec.title || sec.label, sec.id, sec.chip));
    if (sec.intro) section.appendChild(el('p', 'bsec__intro', text(sec.intro)));
    (sec.blocks || []).forEach(function (b) {
      var build = BLOCKS[b.type];
      var node = build ? build(b) : null;
      if (node) section.appendChild(node);
    });
    if (sec.model && model.enabled) section.appendChild(modelSlot());
    return section;
  }

  function overviewSection(ov, labels) {
    var section = el('section', 'bsec bsec--overview');
    section.id = ov.id;
    section.setAttribute('aria-labelledby', ov.id + '-title');

    // Header, after the team's sponsor-packet layout: name, team, roles, stripes.
    var head = el('header', 'ovh');
    var h1 = el('h1', 'ovh__title');
    h1.appendChild(el('span', 'ovh__eyebrow', ov.eyebrow));
    h1.appendChild(el('span', 'visually-hidden', ' – '));
    h1.appendChild(el('span', 'ovh__name', ov.title));
    head.appendChild(h1);
    head.appendChild(el('p', 'ovh__roles', ov.roles));
    var stripes = el('div', 'ovh__stripes');
    stripes.setAttribute('aria-hidden', 'true');
    head.appendChild(stripes);
    section.appendChild(head);
    section.appendChild(el('hr', 'ovh__break'));

    var body = el('div', 'ovh__body');
    var h2 = el('h2', 'bsec__title', ov.heading);
    h2.id = ov.id + '-title';
    body.appendChild(h2);
    body.appendChild(el('p', 'bsec__intro', text(ov.intro)));

    var stats = el('ul', 'stats');
    ov.stats.forEach(function (stat) {
      var li = el('li', 'stat');
      li.appendChild(el('span', 'stat__value', stat.value));
      li.appendChild(el('span', 'stat__text', text(stat.text)));
      stats.appendChild(li);
    });
    body.appendChild(stats);

    var mosaic = el('div', 'mosaic');
    ov.photos.forEach(function (id, index) {
      var entry = manifest[id];
      if (!entry) return;
      var fig = el('figure', 'mosaic__item mosaic__item--' + (index + 1));
      fig.appendChild(mediaBox(Site.image(manifest, id, { sizes: SIZES.mosaic }), entry, {}, 'mosaic__media'));
      mosaic.appendChild(fig);
    });
    body.appendChild(mosaic);

    var roles = el('div', 'roles');
    ov.roles_detail.forEach(function (role) {
      var card = el('article', 'role');
      card.appendChild(el('h3', 'role__title', role.title));
      // Points are plain strings, or { title, items } groups with a small heading each.
      var ul = null;
      role.points.forEach(function (point) {
        if (point.items) {
          ul = null;
          var group = el('div', 'role__group');
          group.appendChild(el('p', 'label role__group-title', point.title));
          var items = el('ul', 'points');
          point.items.forEach(function (item) {
            items.appendChild(el('li', null, text(item)));
          });
          group.appendChild(items);
          card.appendChild(group);
          return;
        }
        if (!ul) ul = card.appendChild(el('ul', 'points'));
        ul.appendChild(el('li', null, text(point)));
      });
      var go = el('a', 'role__link', labels[role.target] + ' →');
      go.href = '#' + role.target;
      go.addEventListener('click', function (event) {
        jump(event, role.target);
      });
      card.appendChild(go);
      roles.appendChild(card);
    });
    body.appendChild(roles);
    section.appendChild(body);
    return section;
  }

  /* ----- Timeline ----- */

  function timelineLink(className, id, label) {
    var a = el('a', className, label);
    a.href = '#' + id;
    a.addEventListener('click', function (event) {
      jump(event, id);
    });
    return a;
  }

  function buildTimeline(data) {
    var top = el('li', 'bt__top');
    var overviewLink = timelineLink('bt__link bt__link--top', data.overview.id, data.overview.label);
    top.appendChild(overviewLink);
    list.appendChild(top);
    stops.push({ link: overviewLink, id: data.overview.id, group: null });

    data.groups.forEach(function (group) {
      var li = el('li', 'bt__group');
      var heading = timelineLink('bt__heading', group.sections[0].id, group.label);
      li.appendChild(heading);
      var items = el('ol', 'bt__items');
      group.sections.forEach(function (sec) {
        var item = el('li');
        var link = timelineLink('bt__link', sec.id, sec.label);
        item.appendChild(link);
        items.appendChild(item);
        stops.push({ link: link, id: sec.id, group: group.id });
      });
      li.appendChild(items);
      list.appendChild(li);
      groups[group.id] = { element: li, heading: heading };
    });
  }

  function jump(event, id) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    var target = document.getElementById(id);
    if (!target) return;
    event.preventDefault();
    history.replaceState(null, '', '#' + id);
    target.scrollIntoView({ behavior: reducedMotion.matches ? 'auto' : 'smooth', block: 'start' });
  }

  // Phones: keep the current entry in view in the horizontal strip. Done by hand, because
  // scrollIntoView() would also move the keyboard's Tab starting point.
  function centerInStrip(link) {
    var box = list.getBoundingClientRect();
    var item = link.getBoundingClientRect();
    list.scrollLeft += item.left + item.width / 2 - (box.left + box.width / 2);
  }

  // Very short wide screens: the timeline list scrolls, so keep the current entry inside it.
  function keepInSide(link) {
    if (list.scrollHeight <= list.clientHeight) return;
    var box = list.getBoundingClientRect();
    var item = link.getBoundingClientRect();
    if (item.top < box.top) list.scrollTop -= box.top - item.top + 16;
    else if (item.bottom > box.bottom) list.scrollTop += item.bottom - box.bottom + 16;
  }

  function setCurrent(current) {
    stops.forEach(function (stop) {
      if (stop === current) {
        if (stop.link.getAttribute('aria-current') !== 'true') {
          stop.link.setAttribute('aria-current', 'true');
          if (wide.matches) keepInSide(stop.link);
          else centerInStrip(stop.link);
        }
      } else {
        stop.link.removeAttribute('aria-current');
      }
    });
    Object.keys(groups).forEach(function (id) {
      var active = current.group === id;
      groups[id].element.classList.toggle('is-active', active);
      groups[id].heading.classList.toggle('is-active', active);
    });
  }

  function spy() {
    ticking = false;
    if (!stops.length) return;
    var top, height, atEnd;
    if (wide.matches) {
      var box = pane.getBoundingClientRect();
      top = box.top;
      height = box.height;
      atEnd = pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 2;
    } else {
      top = side.getBoundingClientRect().bottom;
      height = window.innerHeight - top;
      atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
    }
    var line = top + height * SPY_LINE;
    var current = stops[0];
    stops.forEach(function (stop) {
      if (stop.section.getBoundingClientRect().top <= line) current = stop;
    });
    if (atEnd) current = stops[stops.length - 1];
    setCurrent(current);
  }

  function requestSpy() {
    if (!ticking) {
      ticking = true;
      window.requestAnimationFrame(spy);
    }
  }

  function build(data, media) {
    manifest = media;
    model = data.model || {};
    var labels = {};
    data.groups.forEach(function (group) {
      group.sections.forEach(function (sec) {
        labels[sec.id] = sec.label;
      });
    });

    if (data.link) navLogo(data.link);
    buildTimeline(data);
    pane.classList.add('pane--story');
    pane.appendChild(overviewSection(data.overview, labels));
    data.groups.forEach(function (group) {
      group.sections.forEach(function (sec) {
        pane.appendChild(storySection(sec, group.label));
      });
    });
    stops.forEach(function (stop) {
      stop.section = document.getElementById(stop.id);
    });

    pane.addEventListener('scroll', requestSpy, { passive: true });
    window.addEventListener('scroll', requestSpy, { passive: true });
    window.addEventListener('resize', requestSpy);

    var wanted = location.hash.slice(1);
    var target = wanted && document.getElementById(wanted);
    if (target) target.scrollIntoView({ behavior: 'auto', block: 'start' });
    spy();
  }

  Promise.all([Site.getJSON('data/baja.json'), Site.getJSON('data/manifest.json')])
    .then(function (data) {
      build(data[0], data[1]);
    })
    .catch(function () {
      Site.fail(pane, 'The Baja SAE page could not be loaded.');
    });
})();
