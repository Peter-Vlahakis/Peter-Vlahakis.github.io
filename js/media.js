/* Shared helpers: JSON loading, small DOM builders, and manifest-backed images. */
(function () {
  'use strict';

  var requests = {};

  function getJSON(path) {
    if (!requests[path]) {
      requests[path] = fetch(path).then(function (res) {
        if (!res.ok) throw new Error(path + ' responded ' + res.status);
        return res.json();
      });
    }
    return requests[path];
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  // Copy fields are either a plain string or { "text": "...", "draft": true }.
  function text(value) {
    if (value == null) return '';
    return typeof value === 'string' ? value : value.text || '';
  }

  /**
   * Build an <img> from a manifest id. Returns null if the id is unknown,
   * so a missing image leaves its slot out instead of showing a broken icon.
   * options: sizes (string), eager (boolean), native (boolean: never larger than its pixel size)
   */
  function image(manifest, id, options) {
    var entry = manifest[id];
    options = options || {};
    if (!entry) return null;
    var img = document.createElement('img');
    img.width = entry.width;
    img.height = entry.height;
    img.alt = entry.alt;
    if (!options.eager) {
      img.loading = 'lazy';
      img.decoding = 'async';
    }
    img.sizes = options.sizes || '100vw';
    img.srcset = entry.srcset;
    img.src = entry.src;
    if (options.native) img.style.maxWidth = nativeWidth(entry) + 'px';
    return img;
  }

  function nativeWidth(entry) {
    var widths = entry.srcset.split(',').map(function (part) {
      return parseInt(part.trim().split(/\s+/)[1], 10) || 0;
    });
    return Math.max.apply(null, widths.concat(entry.width));
  }

  function figure(manifest, item, options) {
    var img = image(manifest, item.image, options);
    if (!img) return null;
    var fig = el('figure', options && options.className);
    fig.appendChild(img);
    var caption = text(item.caption);
    if (caption) fig.appendChild(el('figcaption', 'caption', caption));
    return fig;
  }

  function fail(container, message) {
    container.textContent = '';
    container.appendChild(el('p', 'notice', message));
  }

  // The biggest file a manifest entry has: its expanded-view still ("large"), else the top of its srcset.
  function largest(entry) {
    if (entry.large) return entry.large;
    var best = { src: entry.src, width: entry.width, height: entry.height };
    entry.srcset.split(',').forEach(function (part) {
      var bits = part.trim().split(/\s+/);
      var w = parseInt(bits[1], 10) || 0;
      if (w > best.width) best = { src: bits[0], width: w, height: Math.round((w * entry.height) / entry.width) };
    });
    return best;
  }

  /* ----- Expanded view: a modal <dialog>. Any click, Esc, or the Close button closes it, and focus goes back. ----- */

  var view = null;

  function expandedView() {
    if (view) return view;
    var dialog = el('dialog', 'lightbox');
    var close = el('button', 'lightbox__close', 'Close');
    close.type = 'button';
    var fig = el('figure', 'lightbox__figure');
    var frame = el('div', 'lightbox__frame');
    var img = el('img', 'lightbox__img');
    var credit = el('span', 'credit-tag');
    var caption = el('figcaption', 'lightbox__caption');
    frame.appendChild(img);
    frame.appendChild(credit);
    fig.appendChild(frame);
    fig.appendChild(caption);
    dialog.appendChild(close);
    dialog.appendChild(fig);
    document.body.appendChild(dialog);
    dialog.addEventListener('click', function () {
      dialog.close();
    });
    dialog.addEventListener('close', function () {
      img.removeAttribute('src');
      if (view.opener && document.contains(view.opener)) view.opener.focus();
      view.opener = null;
    });
    view = { dialog: dialog, close: close, img: img, credit: credit, caption: caption, opener: null, token: 0 };
    return view;
  }

  /**
   * Open the expanded view. item: { src, width, height, alt, caption, credit, preview }.
   * preview (optional) is a file already loaded on the page, shown until the full file arrives.
   */
  function expand(item, opener) {
    var v = expandedView();
    var token = ++v.token;
    v.opener = opener || document.activeElement;
    v.dialog.setAttribute('aria-label', item.caption || item.alt);
    v.img.alt = item.alt;
    v.img.width = item.width;
    v.img.height = item.height;
    v.img.src = item.preview || item.src;
    if (item.preview && item.preview !== item.src) {
      var full = new Image();
      full.onload = function () {
        if (token === v.token && v.dialog.open) v.img.src = item.src;
      };
      full.src = item.src;
    }
    v.caption.textContent = item.caption || '';
    v.caption.hidden = !item.caption;
    setCredit(v.credit, item.credit);
    v.dialog.showModal();
    v.close.focus();
  }

  // Photographer credit, shown in an image's bottom-left corner. Screen readers hear "Photo: ...".
  function setCredit(node, credit) {
    node.textContent = '';
    node.hidden = !credit;
    if (!credit) return node;
    node.appendChild(el('span', 'visually-hidden', 'Photo: '));
    node.appendChild(document.createTextNode(credit));
    return node;
  }

  function creditTag(credit) {
    return credit ? setCredit(el('span', 'credit-tag'), credit) : null;
  }

  /**
   * Wrap an <img> in a button that opens it in the expanded view: the 2560 px still when the
   * manifest has one, else the largest file in its srcset, with the caption underneath.
   */
  function zoomable(img, entry, caption) {
    var button = el('button', 'zoom');
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'dialog');
    button.appendChild(el('span', 'visually-hidden', 'View larger: '));
    button.appendChild(img);
    button.addEventListener('click', function () {
      var big = largest(entry);
      expand(
        {
          src: big.src,
          width: big.width,
          height: big.height,
          alt: entry.alt,
          caption: caption || '',
          credit: entry.credit,
          preview: img.currentSrc || img.src
        },
        button
      );
    });
    return button;
  }

  window.Site = {
    getJSON: getJSON,
    el: el,
    text: text,
    image: image,
    figure: figure,
    fail: fail,
    largest: largest,
    expand: expand,
    zoomable: zoomable,
    creditTag: creditTag
  };
})();
