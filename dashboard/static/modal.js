(function(global) {
  'use strict';
  const OVERLAY_ID = 'modal-overlay';
  function getOverlay() { return document.getElementById(OVERLAY_ID); }
  function open() {
    const ov = getOverlay(); if (!ov) return;
    ov.classList.add('modal-overlay--open');
    ov.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }
  function close() {
    const ov = getOverlay(); if (!ov) return;
    ov.classList.remove('modal-overlay--open');
    ov.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    setTimeout(() => { if (!ov.classList.contains('modal-overlay--open')) ov.innerHTML = ''; }, 220);
  }
  function isOpen() {
    const ov = getOverlay();
    return ov && ov.classList.contains('modal-overlay--open');
  }
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (isOpen()) { close(); return; }
    const panel = document.getElementById('refresh-panel');
    if (panel && !panel.hidden) panel.hidden = true;
  });
  document.addEventListener('click', (e) => {
    const ov = getOverlay();
    if (!ov || !isOpen()) return;
    if (e.target === ov) close();
  });
  global.Modal = { open, close, isOpen };
})(window);
