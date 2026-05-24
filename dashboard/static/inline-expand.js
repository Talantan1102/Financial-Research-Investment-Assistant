// inline expand toggle — fetch /cap/{id}/expand + slide animate + render markdown
(function () {
  async function toggleExpand(capId) {
    const detail = document.getElementById(`detail-${capId}`);
    if (!detail) return;

    // 当前已展开 → 收起
    if (!detail.hidden) {
      detail.style.maxHeight = detail.scrollHeight + 'px';
      // force reflow
      void detail.offsetHeight;
      detail.style.transition = 'max-height 0.24s ease-out, opacity 0.18s';
      detail.style.maxHeight = '0';
      detail.style.opacity = '0';
      setTimeout(() => {
        detail.hidden = true;
        detail.style.maxHeight = '';
        detail.style.opacity = '';
      }, 240);
      return;
    }

    // 展开 — 若未加载内容,先 fetch
    if (!detail.dataset.loaded) {
      detail.innerHTML = '<div class="cap-detail-loading">加载中…</div>';
      detail.hidden = false;
      try {
        const resp = await fetch(`/cap/${capId}/expand`);
        if (!resp.ok) {
          detail.innerHTML = `<div class="cap-detail-error">加载失败: ${resp.status}</div>`;
          return;
        }
        const html = await resp.text();
        detail.innerHTML = html;
        detail.dataset.loaded = 'true';
        // markdown + mermaid render(若有 render-field.js)
        if (window.harness?.renderField) {
          window.harness.renderField(detail);
        }
      } catch (e) {
        detail.innerHTML = `<div class="cap-detail-error">网络错误: ${e.message}</div>`;
        return;
      }
    } else {
      detail.hidden = false;
    }

    // slide animate in
    detail.style.maxHeight = '0';
    detail.style.opacity = '0';
    void detail.offsetHeight;  // force reflow
    detail.style.transition = 'max-height 0.32s ease-out, opacity 0.22s';
    requestAnimationFrame(() => {
      detail.style.maxHeight = detail.scrollHeight + 'px';
      detail.style.opacity = '1';
    });
    // 动画完成后清 max-height,让内容自适应
    setTimeout(() => {
      if (!detail.hidden) {
        detail.style.maxHeight = 'none';
      }
    }, 360);
  }

  // URL hash 自动展开 (锚点链接 /m/dim#cap-id)
  window.addEventListener('DOMContentLoaded', () => {
    if (location.hash && location.hash.startsWith('#cap-')) {
      const capId = location.hash.substring(5);
      const chip = document.querySelector(`button[data-cap-id="${capId}"]`);
      if (chip) {
        chip.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => chip.click(), 400);
      }
    }
  });

  window.harness = window.harness || {};
  window.harness.toggleExpand = toggleExpand;
})();
