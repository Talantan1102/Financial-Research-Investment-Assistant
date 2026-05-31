// 就地展开 — 单击 chip 展开/收起 DeepCard。
// 注:cap id 含点号(如 context.constrained_schema),detail 的 id 形如 detail-context.constrained_schema。
// CSS 选择器 #detail-context.constrained_schema 会把 .constrained_schema 当成 class → 永远匹配不到,
// 所以这里用 getElementById(字面 id,点号 OK) + fetch 注入,绕开 htmx 的 CSS-selector target。
(function () {
  function reveal(detail) {
    detail.style.transition = 'max-height 0.26s ease-out, opacity 0.2s';
    detail.classList.add('open');
    detail.style.opacity = '1';
    detail.style.maxHeight = detail.scrollHeight + 'px';
    // 动画结束后释放 maxHeight,避免 markdown/mermaid 异步渲染改变高度后被裁剪
    window.setTimeout(() => {
      if (detail.classList.contains('open')) detail.style.maxHeight = 'none';
    }, 300);
  }

  function collapse(detail) {
    detail.classList.remove('open');
    detail.style.transition = 'max-height 0.24s ease-out, opacity 0.18s';
    detail.style.maxHeight = detail.scrollHeight + 'px';
    requestAnimationFrame(() => {
      detail.style.maxHeight = '0';
      detail.style.opacity = '0';
    });
    window.setTimeout(() => {
      detail.hidden = true;
    }, 260);
  }

  function toggleExpand(capId) {
    const detail = document.getElementById(`detail-${capId}`);
    if (!detail) return;
    const chip = document.querySelector(`button[data-cap-id="${CSS.escape(capId)}"]`);

    if (detail.classList.contains('open')) {
      chip?.setAttribute('aria-expanded', 'false');
      collapse(detail);
      return;
    }

    chip?.setAttribute('aria-expanded', 'true');
    detail.hidden = false;
    detail.style.maxHeight = '0';
    detail.style.opacity = '0';

    // 已加载过 → 直接展开,不重复请求
    if (detail.dataset.loaded === '1' && detail.innerHTML.trim() !== '') {
      requestAnimationFrame(() => reveal(detail));
      return;
    }

    fetch(`/cap/${encodeURIComponent(capId)}/expand`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then((html) => {
        detail.innerHTML = html;
        detail.dataset.loaded = '1';
        window.harness?.renderField?.(detail);
        requestAnimationFrame(() => reveal(detail));
      })
      .catch((err) => {
        detail.innerHTML = `<p class="field-empty field-empty--todo">展开失败:${err.message}</p>`;
        detail.dataset.loaded = '';
        window.Toast?.show({ type: 'error', msg: `展开失败:${err.message}` });
        requestAnimationFrame(() => reveal(detail));
      });
  }

  // 深链:打开页面时若 hash 指向某 cap,自动滚动并展开
  window.addEventListener('DOMContentLoaded', () => {
    if (location.hash && location.hash.startsWith('#cap-')) {
      const capId = decodeURIComponent(location.hash.substring(5));
      const chip = document.querySelector(`button[data-cap-id="${CSS.escape(capId)}"]`);
      if (chip) {
        chip.scrollIntoView({ behavior: 'smooth', block: 'center' });
        window.setTimeout(() => toggleExpand(capId), 400);
      }
    }
  });

  window.harness = window.harness || {};
  window.harness.toggleExpand = toggleExpand;
})();
