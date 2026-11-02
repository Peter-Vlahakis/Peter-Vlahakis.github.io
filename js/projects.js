/* Projects: list on the left, one scrollable pane on the right, deep links via ?project=<id>.
   Each project: overview (title and subtitle, summary, spec table beside the hero, arrow), CAD render,
   CAM, extra photos. Text sits left and pictures right; every image opens the expanded view. */
(function () {
  'use strict';

  var Site = window.Site;
  var el = Site.el;
  var list = document.getElementById('project-list');
  var pane = document.getElementById('pane');
  var drop = document.getElementById('pdrop');
  var dropButton = drop.querySelector('.pdrop__button');
  var dropList = document.getElementById('pdrop-list');
  var dropName = document.getElementById('pdrop-name');
  var dropCount = document.getElementById('pdrop-count');
  // The page's own address, from its canonical tag; each project's canonical and og:url add ?project=<id>.
  var canonical = document.querySelector('link[rel="canonical"]');
  var ogUrl = document.querySelector('meta[property="og:url"]');
  var pageUrl = canonical ? canonical.getAttribute('href').split('?')[0] : '';
  var wide = window.matchMedia('(min-width: 768px)');
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var baseTitle = document.title;

  /*
   * Display widths for the browser's srcset choice. They mirror --frame-w in css/projects.css, with the
   * list taken at its narrowest (240px) so the estimate never comes out smaller than the real width.
   * Hero, 1024px and wider: the pane less its side margins (48px), the gap (16px), and the narrowest
   * spec table (about 283px), so under 590px in all; it is drawn no wider than that, often narrower.
   */
  var FRAME_RATIO = 4 / 3;
  var SIZES = {
    hero: '(min-width: 1024px) calc(100vw - 580px), (min-width: 768px) calc(100vw - 240px), 100vw',
    render: '(min-width: 1560px) 676px, (min-width: 1000px) calc((100vw - 240px) * 0.55), (min-width: 768px) 364px, 100vw'
  };

  // A frame is filled edge to edge ("cover"), so a picture wider than 4:3 is drawn wider than the frame.
  function frameSizes(entry) {
    var f = Math.max(1, entry.width / entry.height / FRAME_RATIO);
    return (
      '(min-width: 1560px) ' + Math.ceil(520 * f) + 'px, ' +
      '(min-width: 1000px) calc((100vw - 240px) * ' + (0.42 * f).toFixed(3) + '), ' +
      '(min-width: 768px) ' + Math.ceil(280 * f) + 'px, ' +
      'calc(100vw * ' + f.toFixed(3) + ')'
    );
  }

  var OPS_HEAD = ['Operation', 'Tool', 'Purpose'];

  var projects = [];
  var manifest = {};
  var currentId = null;

  function idFromAddress() {
    return new URLSearchParams(location.search).get('project');
  }

  function byId(id) {
    for (var i = 0; i < projects.length; i++) if (projects[i].id === id) return projects[i];
    return null;
  }

  /* ----- Copy: **double asterisks** mark bold words (the operation names in CAM captions) ----- */

  function rich(tag, className, words) {
    var node = el(tag, className);
    String(words).split('**').forEach(function (part, i) {
      if (!part) return;
      node.appendChild(i % 2 ? el('strong', 'ptext-bold', part) : document.createTextNode(part));
    });
    return node;
  }

  function plain(words) {
    return String(words || '').split('**').join('');
  }

  /* ----- Project links: the left list, the phone dropdown, and Previous / Next ----- */

  // A link to one project. A plain click switches in place (then runs after); modified clicks open normally.
  function projectLink(project, className, after) {
    var link = el('a', className);
    link.href = 'projects.html?project=' + encodeURIComponent(project.id);
    link.setAttribute('data-id', project.id);
    link.addEventListener('click', function (event) {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      if (project.id !== currentId) {
        history.pushState({ project: project.id }, '', '?project=' + encodeURIComponent(project.id));
      }
      show(project.id);
      if (after) after();
    });
    return link;
  }

  function renderList() {
    projects.forEach(function (project) {
      var link = projectLink(project, 'plist__link');
      link.appendChild(el('span', 'plist__title', project.title));
      link.appendChild(el('span', 'plist__context', Site.text(project.context)));
      var item = el('li');
      item.appendChild(link);
      list.appendChild(item);
    });
  }

  // Phones: one bar with the current project and "1 of 6"; it opens the full list with subtitles.
  function setDrop(open) {
    dropList.hidden = !open;
    dropButton.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function renderDrop() {
    projects.forEach(function (project) {
      var link = projectLink(project, 'pdrop__link', function () {
        setDrop(false);
        dropButton.focus({ preventScroll: true });
      });
      link.appendChild(el('span', 'pdrop__title', project.title));
      link.appendChild(el('span', 'pdrop__context', Site.text(project.context)));
      var item = el('li');
      item.appendChild(link);
      dropList.appendChild(item);
    });
    dropButton.addEventListener('click', function () {
      setDrop(dropList.hidden);
    });
    // A tap anywhere outside closes it, and so does Escape (focus goes back to the bar).
    document.addEventListener('pointerdown', function (event) {
      if (!dropList.hidden && !drop.contains(event.target)) setDrop(false);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !dropList.hidden) {
        setDrop(false);
        dropButton.focus({ preventScroll: true });
      }
    });
    wide.addEventListener('change', function () {
      setDrop(false);
    });
  }

  // Bring the current item into view inside the list (a column on wide screens, a strip on phones).
  // Done by hand: scrollIntoView() would also move the keyboard's Tab starting point past the nav.
  function reveal(link) {
    var box = list.getBoundingClientRect();
    var item = link.getBoundingClientRect();
    if (item.top < box.top) list.scrollTop -= box.top - item.top;
    else if (item.bottom > box.bottom) list.scrollTop += item.bottom - box.bottom;
    if (item.left < box.left) list.scrollLeft -= box.left - item.left;
    else if (item.right > box.right) list.scrollLeft += item.right - box.right;
  }

  function markCurrent() {
    Array.prototype.forEach.call(list.querySelectorAll('.plist__link'), function (link) {
      if (link.getAttribute('data-id') === currentId) {
        link.setAttribute('aria-current', 'true');
        reveal(link);
      } else {
        link.removeAttribute('aria-current');
      }
    });
    var index = projects.indexOf(byId(currentId));
    dropName.textContent = projects[index].title;
    dropCount.textContent = index + 1 + ' of ' + projects.length;
    Array.prototype.forEach.call(dropList.querySelectorAll('.pdrop__link'), function (link) {
      if (link.getAttribute('data-id') === currentId) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  }

  /* ----- Images ----- */

  // A picture in the project's uniform 4:3 frame, cropped to fill it ("focus" keeps the subject in
  // view). A click opens the whole picture at full quality, with its caption.
  function framed(id, caption, focus) {
    var entry = manifest[id];
    if (!entry) return null;
    var img = Site.image(manifest, id, { sizes: frameSizes(entry) });
    if (focus) img.style.objectPosition = focus;
    var frame = el('div', 'pframe');
    frame.appendChild(Site.zoomable(img, entry, plain(caption)));
    return frame;
  }

  /* ----- Right pane: overview, render, CAM, photos (always this order) ----- */

  function specTable(specs) {
    var dl = el('dl', 'specs');
    Object.keys(specs || {}).forEach(function (key) {
      var row = el('div', 'specs__row');
      row.appendChild(el('dt', 'label', key));
      row.appendChild(el('dd', null, specs[key]));
      dl.appendChild(row);
    });
    return dl;
  }

  function overview(project) {
    var block = el('header', 'overview');
    var head = el('div', 'overview__head');
    head.appendChild(el('h1', 'overview__title', project.title));
    head.appendChild(el('p', 'overview__context', Site.text(project.context)));
    block.appendChild(head);
    var summary = Site.text(project.summary);
    if (summary) block.appendChild(el('p', 'overview__summary', summary));

    var row = el('div', 'overview__row');
    row.appendChild(specTable(project.specs));
    var img = Site.image(manifest, project.opening, { sizes: SIZES.hero, eager: true });
    if (img) {
      var hero = el('figure', 'overview__hero');
      // The hero's own shape, so on wide screens the table and photo sit together with no gap between.
      // Tall (portrait) and wide (landscape) heroes are sized differently beside the table.
      hero.style.setProperty('--hero-ar', (img.width / img.height).toFixed(4));
      row.classList.add(img.width < img.height ? 'overview__row--tall' : 'overview__row--wide');
      hero.appendChild(Site.zoomable(img, manifest[project.opening], ''));
      row.appendChild(hero);
    }
    block.appendChild(row);
    return block;
  }

  // Points down to the design and manufacturing story, and smooth-scrolls there on click.
  function scrollArrow(target, label, className) {
    var a = el('a', className);
    a.href = '#' + target.id;
    a.appendChild(el('span', 'pnext__label', label));
    a.insertAdjacentHTML(
      'beforeend',
      '<svg class="pnext__icon" viewBox="0 0 44 16" width="44" height="16" aria-hidden="true" focusable="false"><path d="M2 2.5 22 13.5 42 2.5"/></svg>'
    );
    a.addEventListener('click', function (event) {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      target.scrollIntoView({ behavior: reducedMotion.matches ? 'auto' : 'smooth', block: 'start' });
    });
    return a;
  }

  /*
   * The arrow must show the moment a project opens. When the one under the overview starts below the
   * visible area (phones, short windows), a copy is pinned to the bottom edge until the real one
   * scrolls into view. The copy is for the pointer only; keyboard and screen readers use the real one.
   */
  var inFlow = null;
  var pinned = null;
  var placing = 0;

  function setPinned(node) {
    if (pinned) pinned.remove();
    pinned = node;
    if (!pinned) return;
    pinned.setAttribute('aria-hidden', 'true');
    pinned.tabIndex = -1;
    pinned.hidden = true;
    document.body.appendChild(pinned);
  }

  function placePinned() {
    placing = 0;
    if (!pinned) return;
    var bottom = wide.matches ? pane.getBoundingClientRect().bottom : window.innerHeight;
    pinned.hidden = !(inFlow && inFlow.getBoundingClientRect().top > bottom - 8);
  }

  function schedulePinned() {
    if (!placing) placing = requestAnimationFrame(placePinned);
  }

  function section(label, id) {
    var block = el('section', 'block pblock');
    if (id) block.id = id;
    block.appendChild(el('h2', 'phead', label));
    return block;
  }

  // Caption on the left, render on the right: a little larger than the CAM frames.
  function renderBlock(project) {
    var render = project.render;
    if (!render || !manifest[render.image]) return null;
    var img = Site.image(manifest, render.image, { sizes: SIZES.render });
    var words = Site.text(render.caption);
    var block = section('CAD Render', 'project-render');
    var row = el('div', 'prender');
    if (words) row.appendChild(rich('p', 'prender__caption', words));
    var fig = el('figure', 'prender__media');
    fig.appendChild(Site.zoomable(img, manifest[render.image], plain(words)));
    row.appendChild(fig);
    block.appendChild(row);
    return block;
  }

  function opsTable(ops) {
    var wrap = el('div', 'ops-wrap');
    var table = el('table', 'ops');
    var head = el('thead');
    var tr = el('tr');
    OPS_HEAD.forEach(function (cell) {
      var th = el('th', 'label', cell);
      th.scope = 'col';
      tr.appendChild(th);
    });
    head.appendChild(tr);
    table.appendChild(head);
    var body = el('tbody');
    ops.forEach(function (row) {
      var r = el('tr');
      row.forEach(function (cell, i) {
        var c = el(i === 0 ? 'th' : 'td', null, cell);
        if (i === 0) c.scope = 'row';
        r.appendChild(c);
      });
      body.appendChild(r);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    return wrap;
  }

  /*
   * One row per setup: title and operation table on the left, CAM capture on the right with its
   * caption underneath. A photo between setups uses the same row: heading and caption left, photo right.
   */
  function stepRow(step) {
    var row = el('article', 'setup');
    var body = el('div', 'setup__body');
    var title = step.title || step.heading;
    if (title) body.appendChild(el('h3', 'setup__title', title));
    if (step.ops && step.ops.length) body.appendChild(opsTable(step.ops));
    var words = Site.text(step.caption);
    var frame = step.image ? framed(step.image, words, step.focus) : null;
    var media = null;
    if (frame) {
      media = el('figure', 'setup__media');
      media.appendChild(frame);
    }
    if (step.type === 'photo') {
      row.classList.add('setup--photo');
      if (words) body.appendChild(rich('p', 'setup__caption', words));
    } else if (media && words) {
      media.appendChild(rich('figcaption', 'setup__caption', words));
    } else if (words) {
      body.appendChild(rich('p', 'setup__caption', words));
    }
    row.appendChild(body);
    if (media) row.appendChild(media);
    else row.classList.add('setup--text');
    return row;
  }

  function camBlock(project) {
    var cam = project.cam;
    if (!cam) return null;
    var block = section(cam.label || 'CAM', 'project-cam');
    (cam.notes || []).forEach(function (note) {
      block.appendChild(el('p', 'cam__note', Site.text(note)));
    });
    var steps = el('div', 'setups');
    (cam.steps || []).forEach(function (step) {
      steps.appendChild(stepRow(step));
    });
    if (steps.children.length) block.appendChild(steps);
    return block;
  }

  // Photos side by side at the frame size, captions lined up underneath.
  function photoGrid(items) {
    var grid = el('div', 'pgrid');
    items.forEach(function (item) {
      var words = Site.text(item.caption);
      var frame = framed(item.image, words, item.focus);
      if (!frame) return;
      var fig = el('figure', 'pfig');
      fig.appendChild(frame);
      if (words) fig.appendChild(rich('figcaption', 'caption pfig__caption', words));
      grid.appendChild(fig);
    });
    return grid.children.length ? grid : null;
  }

  function photosBlock(project) {
    var photos = project.photos;
    if (!photos) return null;
    var block = section(photos.label || 'Photos');
    var groups = photos.groups || [{ items: photos.items || [] }];
    groups.forEach(function (group) {
      var grid = photoGrid(group.items || []);
      if (!grid) return;
      if (group.label) block.appendChild(el('h3', 'photos__group', group.label));
      block.appendChild(grid);
    });
    return block.children.length > 1 ? block : null;
  }

  // Previous and Next at the foot of every project: no Previous on the first, no Next on the last.
  function pager(project) {
    var index = projects.indexOf(project);
    var wrap = el('nav', 'pnav');
    wrap.setAttribute('aria-label', 'Previous and next project');
    [
      { other: projects[index - 1], side: 'prev', arrow: '\u2190', word: 'Previous' },
      { other: projects[index + 1], side: 'next', arrow: '\u2192', word: 'Next' }
    ].forEach(function (step) {
      if (!step.other) return;
      // Keyboard focus moves to the new project, since the link that was used goes with the old one.
      var link = projectLink(step.other, 'pnav__link pnav__link--' + step.side, function () {
        pane.focus({ preventScroll: true });
      });
      var dir = el('span', 'pnav__dir label', step.word);
      var arrow = el('span', 'pnav__arrow', step.arrow);
      arrow.setAttribute('aria-hidden', 'true');
      if (step.side === 'prev') dir.insertBefore(arrow, dir.firstChild);
      else dir.appendChild(arrow);
      link.appendChild(dir);
      link.appendChild(el('span', 'pnav__name', step.other.title));
      wrap.appendChild(link);
    });
    return wrap;
  }

  function show(id) {
    var project = byId(id) || projects[0];
    if (!project) return;
    currentId = project.id;

    pane.textContent = '';
    var render = renderBlock(project);
    var cam = camBlock(project);
    var head = overview(project);
    var target = render || cam;
    inFlow = null;
    if (target) {
      var label = render ? 'CAD render & CAM' : project.cam.label || 'CAM';
      inFlow = scrollArrow(target, label, 'pnext');
      head.appendChild(inFlow);
      setPinned(scrollArrow(target, label, 'pnext pnext--pinned'));
    } else {
      setPinned(null);
    }
    [head, render, cam, photosBlock(project), pager(project)].forEach(function (block) {
      if (block) pane.appendChild(block);
    });

    pane.scrollTop = 0;
    if (!wide.matches) window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
    document.title = project.title + ' | ' + baseTitle;
    if (pageUrl) {
      var address = pageUrl + '?project=' + encodeURIComponent(project.id);
      canonical.setAttribute('href', address);
      if (ogUrl) ogUrl.setAttribute('content', address);
    }
    markCurrent();
    schedulePinned();
  }

  window.addEventListener('popstate', function () {
    show(idFromAddress());
  });
  pane.addEventListener('scroll', schedulePinned, { passive: true });
  window.addEventListener('scroll', schedulePinned, { passive: true });
  window.addEventListener('resize', schedulePinned);
  // Web fonts can change the overview's height after the first layout.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedulePinned);

  Promise.all([Site.getJSON('data/projects.json'), Site.getJSON('data/manifest.json')])
    .then(function (data) {
      projects = data[0].projects;
      manifest = data[1];
      renderList();
      renderDrop();
      show(idFromAddress()); // no ?project= selects the first project
    })
    .catch(function () {
      Site.fail(pane, 'Projects could not be loaded.');
    });
})();
