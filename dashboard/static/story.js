// Plan 4 Task 2 — /story 客户端实时渲染
(function () {
  const input = document.getElementById('story-input');
  const out = document.getElementById('story-out');
  if (!input || !out) return;

  let renderTimer = null;

  function doRender() {
    const raw = input.value;
    if (!raw.trim()) {
      out.innerHTML = '<p class="story-placeholder">粘 markdown 后,渲染结果会显示在这里。</p>';
      return;
    }
    if (window.harness?.renderStory) {
      window.harness.renderStory(raw);
    } else if (window.harness?.renderMarkdown) {
      out.innerHTML = window.harness.renderMarkdown(raw);
      if (window.mermaid) {
        const mermaids = out.querySelectorAll('.mermaid');
        if (mermaids.length) {
          window.mermaid.run({ nodes: mermaids });
        }
      }
    } else {
      out.innerHTML = '<pre>' + raw.replace(/</g, '&lt;') + '</pre>';
    }
  }

  input.addEventListener('input', () => {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(doRender, 220);
  });

  if (input.value.trim()) doRender();
})();
