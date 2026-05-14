// dashboard/static/refresh-panel.js
// Plan 3 — SSE 客户端 + refresh 面板渲染。spec § 3。
(function () {
  'use strict';

  const ICONS = {
    pending: '○',
    running: '⟳',
    done:    '✓',
    skip:    '⊘',
    error:   '✗',
  };

  let eventSource = null;        // 持续到 done event,不随面板关闭取消
  let lastSummary = null;        // 缓存最新 done payload,面板再打开恢复显示
  let stepStates  = {};          // {chip_resolve: 'done', ...} 缓存
  let stepDetails = {};          // {chip_resolve: '62 chip · 4 lit', ...}
  let panelEl     = null;
  let isFading    = false;

  function $(id) { return document.getElementById(id); }

  function setStepDOM(stepName, status, detail) {
    const row = panelEl.querySelector('.refresh-step[data-step="' + stepName + '"]');
    if (!row) return;
    const icon   = row.querySelector('.step-icon');
    const detEl  = row.querySelector('.step-detail');
    // 同时改 row.dataset.state(供 .refresh-step[data-state] CSS) +
    // icon.dataset.state(供 .step-icon[data-state] CSS) + textContent
    icon.textContent = ICONS[status] || ICONS.pending;
    icon.dataset.state = status;
    row.dataset.state = status;
    if (detail) detEl.textContent = detail;
  }

  function restoreCachedState() {
    Object.keys(stepStates).forEach(function (step) {
      setStepDOM(step, stepStates[step], stepDetails[step] || '');
    });
    if (lastSummary) renderSummary(lastSummary);
  }

  function resetPanel() {
    stepStates = {}; stepDetails = {}; lastSummary = null;
    panelEl.querySelectorAll('.refresh-step').forEach(function (row) {
      row.dataset.state = 'pending';
      const icon = row.querySelector('.step-icon');
      icon.dataset.state = 'pending';
      icon.textContent = ICONS.pending;
      row.querySelector('.step-detail').textContent = '';
    });
    const sum = $('refresh-summary');
    sum.hidden = true; sum.textContent = '';
    $('refresh-retry').hidden = true;
    panelEl.style.opacity = '';
    isFading = false;
  }

  function renderSummary(data) {
    const sum = $('refresh-summary');
    const s = data.steps_summary || {};
    const total = ((data.total_ms || 0) / 1000).toFixed(1);
    const parts = ['⏱ ' + total + 's'];
    if (s.done)  parts.push(s.done + ' done');
    if (s.skip)  parts.push(s.skip + ' skip');
    if (s.error) parts.push(s.error + ' error');
    sum.textContent = parts.join(' · ');
    sum.hidden = false;
  }

  function startStream() {
    if (eventSource) { eventSource.close(); eventSource = null; }
    resetPanel();

    eventSource = new EventSource('/refresh');

    eventSource.addEventListener('step', function (evt) {
      let data;
      try { data = JSON.parse(evt.data); } catch (e) { return; }
      stepStates[data.step]  = data.status;
      stepDetails[data.step] = data.detail || '';
      setStepDOM(data.step, data.status, data.detail);
    });

    eventSource.addEventListener('done', function (evt) {
      let data;
      try { data = JSON.parse(evt.data); } catch (e) { return; }
      lastSummary = data;
      renderSummary(data);
      eventSource.close(); eventSource = null;

      const hasError = (data.steps_summary && data.steps_summary.error) > 0;
      if (hasError) {
        $('refresh-retry').hidden = false;
        if (window.Toast) window.Toast.show({ type: 'error', msg: '刷新部分失败,可重试', ttl: 6000 });
      } else {
        // 5s fade + reload
        isFading = true;
        setTimeout(function () {
          if (!isFading) return;  // 期间被点 refresh 重跑则取消 fade
          panelEl.style.transition = 'opacity 800ms';
          panelEl.style.opacity = '0';
          setTimeout(function () { location.reload(); }, 850);
        }, 5000);
      }
    });

    eventSource.addEventListener('error', function () {
      // 网络/服务端断连
      if (window.Toast) window.Toast.show({ type: 'error', msg: 'SSE 断连,可重试' });
      $('refresh-retry').hidden = false;
      if (eventSource) { eventSource.close(); eventSource = null; }
    });
  }

  function openPanel() {
    panelEl.hidden = false;
    panelEl.focus();
    if (eventSource) {
      // 流仍在跑,恢复显示当前状态(从内存 buffer)
      restoreCachedState();
    } else if (lastSummary && (lastSummary.steps_summary || {}).error > 0) {
      // 错误态保留,允许 retry,不重跑
      restoreCachedState();
    } else {
      // 全新开跑(包括 done 已 reload 错过 / 第一次打开)
      startStream();
    }
  }

  function closePanel() {
    panelEl.hidden = true;
    isFading = false;  // 取消任何 fade-pending
    // EventSource 不关 — 流继续跑;再次 open 恢复状态
  }

  function init() {
    panelEl = $('refresh-panel');
    if (!panelEl) return;  // 页面无面板挂载(测试场景)

    // nav-rail 主按钮(Plan 2 写的 id="refresh-btn" class="refresh-btn")
    const navBtn = document.getElementById('refresh-btn');
    if (navBtn) {
      navBtn.addEventListener('click', function (e) {
        e.preventDefault();
        if (panelEl.hidden) openPanel();
        else closePanel();
      });
    }
    // 兼容兜底
    document.querySelectorAll('.refresh-btn, [data-action="refresh"]').forEach(function (btn) {
      if (btn === navBtn) return;
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        if (panelEl.hidden) openPanel();
        else closePanel();
      });
    });

    // ESC 关
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panelEl.hidden) closePanel();
    });

    // Retry
    const retry = $('refresh-retry');
    if (retry) {
      retry.addEventListener('click', function () { startStream(); });
    }
  }

  // 全局 API(供 overview.js 空状态浮条调用)
  window.HarnessRefresh = {
    open: function () {
      if (!panelEl) return;
      if (panelEl.hidden) openPanel();
    },
    close: closePanel,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
