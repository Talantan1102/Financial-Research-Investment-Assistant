// 客户端 markdown + mermaid 渲染 + 字段就地编辑。
(function () {
  let markedWarned = false;
  let mermaidWarned = false;

  function renderMarkdown(raw) {
    if (!raw) return raw;
    if (!window.marked) {
      if (!markedWarned) {
        markedWarned = true;
        window.Toast?.show({ type: 'error', msg: 'markdown 渲染库(marked)未加载,内容降级为纯文本' });
      }
      return raw; // fail-loud + 降级可读,不静默
    }
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
    nodes.forEach((node) => {
      const raw = node.getAttribute('data-raw-markdown');
      if (!raw) return;
      node.innerHTML = renderMarkdown(raw);
    });
    const mermaids = container.querySelectorAll('.mermaid');
    if (mermaids.length > 0) {
      if (window.mermaid) {
        window.mermaid.run({ nodes: mermaids });
      } else if (!mermaidWarned) {
        mermaidWarned = true;
        window.Toast?.show({ type: 'warn', msg: 'mermaid 图表库未加载,图无法渲染' });
      }
    }
  }

  function renderStory(raw) {
    const out = document.getElementById('story-out');
    if (!out) return;
    out.innerHTML = renderMarkdown(raw);
    renderField(out);
  }

  // 字段就地编辑:点 ✎ 编辑 → textarea → 保存 POST /cap/{id}/field/{field} → 客户端重渲染。
  function editField(capId, fieldId) {
    const body = document.getElementById(`field-${capId}-${fieldId}`);
    if (!body || body.dataset.editing === '1') return;
    const prevHTML = body.innerHTML;
    const raw = body.getAttribute('data-raw-markdown') || '';
    body.dataset.editing = '1';

    const ta = document.createElement('textarea');
    ta.className = 'field-edit-area';
    ta.setAttribute('data-cap-id', capId); // screenshot-upload.js 用 [data-cap-id][data-field] 定位插入点
    ta.setAttribute('data-field', fieldId);
    ta.value = raw;
    ta.rows = Math.min(16, Math.max(3, raw.split('\n').length + 1));

    const bar = document.createElement('div');
    bar.className = 'field-edit-bar';
    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'field-save-btn';
    saveBtn.textContent = '保存';
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'field-cancel-btn';
    cancelBtn.textContent = '取消';

    // 📷 截图上传 — 上传后把 markdown 图插入 textarea 光标处
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/png,image/jpeg,image/gif,image/webp';
    fileInput.hidden = true;
    fileInput.addEventListener('change', () =>
      window.harness?.uploadScreenshot?.(fileInput, capId, fieldId)
    );
    const uploadBtn = document.createElement('button');
    uploadBtn.type = 'button';
    uploadBtn.className = 'field-upload-btn';
    uploadBtn.textContent = '📷 图';
    uploadBtn.title = '上传截图(≤500KB),插入光标处';
    uploadBtn.addEventListener('click', () => fileInput.click());
    const statusSpan = document.createElement('span');
    statusSpan.className = 'upload-status';
    statusSpan.id = `status-${capId}-${fieldId}`;

    bar.append(saveBtn, cancelBtn, uploadBtn, fileInput, statusSpan);

    body.innerHTML = '';
    body.append(ta, bar);
    ta.focus();

    cancelBtn.addEventListener('click', () => {
      body.dataset.editing = '';
      body.innerHTML = prevHTML;
    });

    saveBtn.addEventListener('click', () => {
      const val = ta.value;
      saveBtn.disabled = true;
      saveBtn.textContent = '保存中…';
      const fd = new FormData();
      fd.append('value', val);
      fetch(`/cap/${encodeURIComponent(capId)}/field/${encodeURIComponent(fieldId)}`, {
        method: 'POST',
        body: fd,
      })
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.text();
        })
        .then(() => {
          body.setAttribute('data-raw-markdown', val);
          body.dataset.editing = '';
          body.innerHTML = val
            ? renderMarkdown(val)
            : '<p class="field-empty field-empty--lit">已实现 · 文档待补</p>';
          window.Toast?.show({ type: 'success', msg: '已保存' });
        })
        .catch((err) => {
          saveBtn.disabled = false;
          saveBtn.textContent = '保存';
          window.Toast?.show({ type: 'error', msg: `保存失败:${err.message}` });
        });
    });
  }

  // 全局:任何 htmx swap(如 story 卡 → modal)后,渲染其中的 markdown 字段。
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const target = e.detail && e.detail.target;
    if (target) renderField(target);
  });

  window.harness = window.harness || {};
  window.harness.renderField = renderField;
  window.harness.renderStory = renderStory;
  window.harness.renderMarkdown = renderMarkdown;
  window.harness.editField = editField;
})();
