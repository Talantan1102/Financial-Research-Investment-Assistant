// Plan 2 Task 8 — 客户端 markdown + mermaid 渲染
(function () {
  function renderMarkdown(raw) {
    if (!window.marked || !raw) return raw;
    let html = window.marked.parse(raw, { breaks: true });
    html = html.replace(
      /<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g,
      (_, code) => `<div class="mermaid">${decodeHtml(code)}</div>`
    );
    return html;
  }

  function decodeHtml(s) {
    const t = document.createElement('textarea');
    t.innerHTML = s;
    return t.value;
  }

  function renderField(container) {
    if (!container) return;
    const nodes = container.querySelectorAll('.field-body[data-raw-markdown]');
    nodes.forEach(node => {
      const raw = node.getAttribute('data-raw-markdown');
      if (!raw) return;
      node.innerHTML = renderMarkdown(raw);
    });
    if (window.mermaid) {
      const mermaids = container.querySelectorAll('.mermaid');
      if (mermaids.length > 0) {
        window.mermaid.run({ nodes: mermaids });
      }
    }
  }

  function renderStory(raw) {
    const out = document.getElementById('story-out');
    if (!out) return;
    out.innerHTML = renderMarkdown(raw);
    renderField(out);
  }

  window.harness = window.harness || {};
  window.harness.renderField = renderField;
  window.harness.renderStory = renderStory;
  window.harness.renderMarkdown = renderMarkdown;
})();
