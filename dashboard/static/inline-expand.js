// Plan 2 Task 7 — inline expand toggle (slide animation)
(function () {
  function toggleExpand(capId) {
    const detail = document.getElementById(`detail-${capId}`);
    if (!detail) return;
    if (detail.hidden) {
      detail.hidden = false;
      detail.style.maxHeight = '0';
      detail.style.opacity = '0';
      detail.style.transition = 'max-height 0.24s ease-out, opacity 0.18s';
      requestAnimationFrame(() => {
        detail.style.maxHeight = detail.scrollHeight + 'px';
        detail.style.opacity = '1';
      });
      detail.addEventListener('htmx:afterSwap', () => {
        window.harness?.renderField?.(detail);
      }, { once: true });
    } else {
      detail.style.maxHeight = '0';
      detail.style.opacity = '0';
      setTimeout(() => {
        detail.hidden = true;
        detail.innerHTML = '';
      }, 240);
    }
  }

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
