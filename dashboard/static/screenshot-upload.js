// Plan 2 Task 9 — 图上传 client side
(function () {
  async function uploadScreenshot(inputEl, capId, fieldId) {
    const file = inputEl.files[0];
    if (!file) return;
    const statusEl = document.getElementById(`status-${capId}-${fieldId}`);
    const setStatus = (msg, isErr) => {
      if (!statusEl) return;
      statusEl.textContent = msg;
      statusEl.className = 'upload-status' + (isErr ? ' upload-status--err' : ' upload-status--ok');
    };

    if (file.size > 500_000) {
      setStatus(`文件 ${(file.size/1024).toFixed(1)}KB 超过 500KB 限制`, true);
      return;
    }
    setStatus('上传中...', false);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const resp = await fetch(`/cap/${capId}/screenshot`, { method: 'POST', body: formData });
      if (!resp.ok) {
        const err = await resp.json();
        setStatus(`失败:${err.error || resp.statusText}`, true);
        return;
      }
      const data = await resp.json();
      setStatus(`✓ 已保存 (记得 ${data.git_hint})`, false);

      const ta = document.querySelector(`textarea[data-cap-id="${capId}"][data-field="${fieldId}"]`);
      if (ta) {
        const cursor = ta.selectionStart || ta.value.length;
        ta.value = ta.value.slice(0, cursor) + '\n' + data.markdown + '\n' + ta.value.slice(cursor);
        ta.dispatchEvent(new Event('input'));
      } else {
        navigator.clipboard.writeText(data.markdown).then(
          () => setStatus(`✓ markdown 已复制(${data.markdown})`, false),
          () => setStatus(`✓ 路径:${data.path}(${data.git_hint})`, false)
        );
      }

      window.harness?.toast?.('截图已上传');
    } catch (e) {
      setStatus(`错误:${e.message}`, true);
    } finally {
      inputEl.value = '';
    }
  }

  window.harness = window.harness || {};
  window.harness.uploadScreenshot = uploadScreenshot;
})();
