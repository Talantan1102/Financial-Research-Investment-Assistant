// Plan 2 Task 6 — 右键菜单 show / position / dispatch
(function () {
  let currentCapId = null;
  const menu = () => document.getElementById('context-menu');

  function showContextMenu(event, capId) {
    event.preventDefault();
    currentCapId = capId;
    const m = menu();
    if (!m) return false;
    m.dataset.capId = capId;
    m.querySelectorAll('[hx-post]').forEach(btn => {
      const orig = btn.getAttribute('hx-post');
      btn.setAttribute('hx-post', orig.replace(/__CAP__/g, capId));
      btn.setAttribute('hx-target', `button[data-cap-id="${capId}"]`);
      btn.setAttribute('hx-swap', 'outerHTML');
    });
    if (window.htmx) window.htmx.process(m);
    m.style.left = event.pageX + 'px';
    m.style.top = event.pageY + 'px';
    m.hidden = false;
    m.setAttribute('aria-hidden', 'false');
    return false;
  }

  function hideContextMenu() {
    const m = menu();
    if (!m) return;
    m.hidden = true;
    m.setAttribute('aria-hidden', 'true');
    m.querySelectorAll('[hx-post]').forEach(btn => {
      btn.setAttribute(
        'hx-post',
        btn.getAttribute('hx-post').replace(/\/cap\/[^/]+\//, '/cap/__CAP__/')
      );
    });
  }

  function copyAnchor() {
    if (!currentCapId) return;
    const dim = location.pathname.split('/').pop();
    const url = `${location.origin}/m/${dim}#cap-${currentCapId}`;
    navigator.clipboard.writeText(url).then(
      () => window.harness?.toast?.('锚点已复制'),
      () => alert(url)
    );
    hideContextMenu();
  }

  document.addEventListener('click', (e) => {
    const m = menu();
    if (m && !m.hidden && !m.contains(e.target)) hideContextMenu();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideContextMenu();
  });
  document.addEventListener('htmx:afterSwap', (e) => {
    if (e.detail.target && e.detail.target.classList?.contains('cap-chip')) {
      hideContextMenu();
      window.harness?.toast?.('状态已更新');
    }
  });

  window.harness = window.harness || {};
  window.harness.showContextMenu = showContextMenu;
  window.harness.copyAnchor = copyAnchor;
})();
