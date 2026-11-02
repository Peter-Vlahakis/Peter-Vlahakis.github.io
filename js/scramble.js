/*
 * Text scramble. A cursor sweeps left to right: characters behind it show their
 * final value, the cursor character is a random letter or digit, and characters
 * ahead are random glyphs ("hover") or blank ("load").
 * Used in two places only: the hero name and the nav links.
 */
(function () {
  'use strict';

  var POOL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  var NBSP = ' ';
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var originals = new WeakMap();
  var running = new WeakSet();
  var letterOrDigit;
  try {
    letterOrDigit = new RegExp('[\\p{L}\\p{N}]', 'u');
  } catch (err) {
    letterOrDigit = /[A-Za-z0-9]/;
  }

  function randomGlyph() {
    return POOL.charAt(Math.floor(Math.random() * POOL.length));
  }

  // Lock the box so neighbours do not shift while glyph widths change.
  function lock(el) {
    var box = el.getBoundingClientRect();
    var saved = {
      width: el.style.width,
      height: el.style.height,
      whiteSpace: el.style.whiteSpace,
      overflow: el.style.overflow
    };
    el.style.width = box.width + 'px';
    el.style.height = box.height + 'px';
    el.style.whiteSpace = 'nowrap';
    el.style.overflow = 'hidden';
    return function unlock() {
      el.style.width = saved.width;
      el.style.height = saved.height;
      el.style.whiteSpace = saved.whiteSpace;
      el.style.overflow = saved.overflow;
    };
  }

  /**
   * @param {Element} el       element whose text is animated (text-only content)
   * @param {Object}  options  duration in ms; mode "hover" or "load"
   * @returns {Promise<boolean>} true if the animation ran
   */
  function run(el, options) {
    if (!originals.has(el)) originals.set(el, el.textContent);
    if (reducedMotion.matches || running.has(el)) return Promise.resolve(false);

    var finalText = originals.get(el);
    var chars = Array.from(finalText);
    var duration = options.duration;
    var blankAhead = options.mode === 'load';
    var unlock = lock(el);
    running.add(el);

    function render(progress) {
      var cursor = Math.floor(progress * chars.length);
      var out = '';
      for (var i = 0; i < chars.length; i++) {
        var ch = chars[i];
        if (i < cursor || !letterOrDigit.test(ch)) out += ch; // spaces and punctuation never scramble
        else if (i === cursor) out += randomGlyph();
        else out += blankAhead ? NBSP : randomGlyph();
      }
      el.textContent = out;
    }

    // Paint the first state now, so a caller can unhide the element without a flash of the final text.
    render(0);

    return new Promise(function (resolve) {
      var startTime = null;

      function frame(now) {
        if (startTime === null) startTime = now;
        var progress = (now - startTime) / duration;
        if (progress >= 1) {
          el.textContent = finalText;
          unlock();
          running.delete(el);
          resolve(true);
          return;
        }
        render(progress);
        window.requestAnimationFrame(frame);
      }

      window.requestAnimationFrame(frame);
    });
  }

  window.Scramble = {
    run: run,
    isEnabled: function () {
      return !reducedMotion.matches;
    }
  };
})();
