(function(global) {
  'use strict';
  const TYPES = {
    success: { cls: 'toast--success', defaultTtl: 2400 },
    info:    { cls: 'toast--info',    defaultTtl: 2400 },
    warn:    { cls: 'toast--warn',    defaultTtl: 4000 },
    error:   { cls: 'toast--error',   defaultTtl: 5000 },
  };
  function ensureContainer() {
    let c = document.getElementById('toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'toast-container'; c.className = 'toast-container';
      c.setAttribute('aria-live', 'polite');
      document.body.appendChild(c);
    }
    return c;
  }
  function show({ type = 'info', msg = '', ttl } = {}) {
    if (!msg) return;
    const config = TYPES[type] || TYPES.info;
    const c = ensureContainer();
    const el = document.createElement('div');
    el.className = 'toast ' + config.cls;
    el.setAttribute('role', 'status');
    el.textContent = msg;
    c.appendChild(el);
    requestAnimationFrame(() => el.classList.add('toast--show'));
    const lifeMs = ttl || config.defaultTtl;
    setTimeout(() => {
      el.classList.remove('toast--show');
      el.classList.add('toast--hide');
      setTimeout(() => el.remove(), 300);
    }, lifeMs);
  }
  global.Toast = { show };
})(window);
