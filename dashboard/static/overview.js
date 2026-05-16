// V3 cytoscape 鸟瞰 — 节点点击 → V2 modal。spec § 5.3。
(function () {
  const DIM_COLORS = {
    prompt_context:    '#c89456',  // amber 主
    tools_function:    '#6f9494',  // teal 次
    orchestration:     '#94b87a',  // lit sage
    memory:            '#d4824a',  // wip terracotta
    rag_knowledge:     '#8db1b1',  // teal-glow
    guardrails:        '#a64545',  // danger 暗砖
    eval_observability:'#b9ad94',  // fg-dim
    cost_routing:      '#e5b079',  // amber-glow
  };

  let cy = null;

  function statusOpacity(status) {
    return status === 'lit' ? 1.0 : status === 'wip' ? 0.7 : 0.4;
  }

  function confidenceBorder(c) {
    // todo → wip → lit 渐变,跟 chip dots 一致
    const stops = ['#4a3f33', '#6b5d49', '#7d6e58', '#b9ad94', '#94b87a', '#c89456'];
    return stops[Math.max(0, Math.min(5, c || 0))];
  }

  async function loadAndRender(query) {
    query = query || '';
    if (cy) {
      // 维度过滤切换:旧 cy 元素渐隐 200ms 后销毁
      cy.elements().animate({ style: { opacity: 0 } }, { duration: 200 });
      await new Promise(r => setTimeout(r, 210));
      cy.destroy();
      cy = null;
    }
    let payload;
    try {
      const resp = await fetch('/api/overview/graph.json' + query);
      if (!resp.ok) throw new Error('http ' + resp.status);
      payload = await resp.json();
    } catch (e) {
      console.error('cytoscape data fetch failed', e);
      // fallback: 替换 DOM 为 fallback HTML
      try {
        const html = await (await fetch('/overview/fallback')).text();
        document.body.innerHTML = html;
      } catch (e2) {
        document.getElementById('overview-canvas').innerHTML =
          '<div class="error">数据加载失败 — <a href="/">返回网格</a></div>';
      }
      return;
    }

    const elements = [...payload.nodes, ...payload.edges];

    const countEl = document.querySelector('.ov-count');
    if (countEl) {
      countEl.textContent = payload.nodes.length + ' nodes · ' + payload.edges.length + ' edges';
    }

    cy = cytoscape({
      container: document.getElementById('overview-canvas'),
      elements: elements,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'font-family': 'Manrope, sans-serif',
            'font-size': 11,
            color: '#b9ad94',  // fg-dim
            width: 'mapData(size, 1, 10, 24, 56)',
            height: 'mapData(size, 1, 10, 24, 56)',
            'background-color': function (ele) { return DIM_COLORS[ele.data('dimension')] || '#7d6e58'; },
            'background-opacity': function (ele) {
              // todo (无 DeepCard) 用 0.4 半透;lit 1.0;wip 0.7
              if (!ele.data('has_deep_card')) return 0.4;
              const st = ele.data('status');
              return st === 'lit' ? 1.0 : st === 'wip' ? 0.7 : 0.5;
            },
            'border-width': 2,
            'border-color': function (ele) { return confidenceBorder(ele.data('confidence')); },
            'border-style': function (ele) { return ele.data('has_deep_card') ? 'solid' : 'dashed'; },
            'text-valign': 'bottom',
            'text-margin-y': 6,
            'text-outline-color': '#0c0908',  // ink
            'text-outline-width': 2,
          },
        },
        {
          // 只 lit 节点发光 — 用 overlay-color + overlay-opacity 模拟 box-shadow
          selector: 'node[status = "lit"]',
          style: {
            'overlay-color': function (ele) { return DIM_COLORS[ele.data('dimension')] || '#c89456'; },
            'overlay-opacity': 0.28,
            'overlay-padding': 5,
          },
        },
        {
          // wip 静态 underlay
          selector: 'node[status = "wip"]',
          style: {
            'underlay-color': '#d4824a',
            'underlay-opacity': 0.2,
            'underlay-padding': 4,
          },
        },
        {
          selector: 'edge',
          style: {
            'width': 'data(weight)',
            'line-color': '#7d6e58',  // fg-mute
            'curve-style': 'bezier',
            opacity: function (ele) { return ele.data('weight') >= 1.0 ? 0.85 : 0.45; },
            'line-style': function (ele) { return ele.data('weight') >= 1.0 ? 'solid' : 'dashed'; },
          },
        },
        {
          selector: '.cy-flash-highlight',
          style: {
            'overlay-color': '#e5b079',
            'overlay-opacity': 0.5,
            'border-color': '#c89456',
            'border-width': 4,
          },
        },
      ],
      layout: { name: 'cose', animate: false, randomize: false },
    });

    const tooltip = document.getElementById('overview-tooltip');
    cy.on('mouseover', 'node', function (evt) {
      if (!tooltip) return;
      const d = evt.target.data();
      const text = d.has_deep_card
        ? `${d.label} · conf ${d.confidence}/5`
        : `${d.label} · 待填 DeepCard`;
      tooltip.textContent = text;
      tooltip.hidden = false;
    });
    cy.on('mouseout', 'node', function () {
      if (tooltip) tooltip.hidden = true;
    });
    // 跟随鼠标
    document.getElementById('overview-canvas').addEventListener('mousemove', function (e) {
      if (!tooltip || tooltip.hidden) return;
      tooltip.style.left = (e.clientX + 12) + 'px';
      tooltip.style.top  = (e.clientY + 12) + 'px';
    });

    cy.on('tap', 'node', async function (evt) {
      const id = evt.target.data('id');
      const overlay = document.getElementById('modal-overlay');
      if (!overlay) return;
      overlay.innerHTML = '<div class="modal-loading">载入...</div>';
      // 走 Modal.open() class-based — 直接改 inline display 会让 Modal.close() 关不掉
      if (window.Modal && typeof window.Modal.open === 'function') Modal.open();
      try {
        const html = await (await fetch('/cap/' + encodeURIComponent(id))).text();
        overlay.innerHTML = html;
      } catch (e) {
        overlay.innerHTML = '<div class="error">modal 加载失败</div>';
      }
    });

    // 空状态浮条:nodes < 5 时显示,按钮 click 触发 HarnessRefresh.open()
    const emptyHint = document.getElementById('overview-empty-hint');
    if (emptyHint) {
      emptyHint.hidden = payload.nodes.length >= 5;
    }
    const emptyBtn = document.getElementById('overview-refresh-trigger');
    if (emptyBtn && !emptyBtn.dataset.bound) {
      emptyBtn.dataset.bound = '1';
      emptyBtn.addEventListener('click', function () {
        if (window.HarnessRefresh && typeof window.HarnessRefresh.open === 'function') {
          window.HarnessRefresh.open();
        } else {
          // refresh-panel.js 未加载,fallback toast
          if (window.Toast) window.Toast.show({ type: 'warn', msg: '刷新模块未就绪' });
        }
      });
    }

    // anchor jump support
    handleHashJump();
  }

  function handleHashJump() {
    if (!cy) return;
    if (location.hash && location.hash.indexOf('#cap_') === 0) {
      const anchor = location.hash.replace('#cap_', '');
      const node = cy.getElementById(anchor);
      if (node && node.length) {
        cy.center(node);
        node.flashClass('cy-flash-highlight', 1500);
      }
    }
  }

  function reload() {
    const checks = document.querySelectorAll('.filter-dim:checked');
    const dims = [];
    for (let i = 0; i < checks.length; i++) dims.push(checks[i].value);
    const confSel = document.querySelector('input[name="conf-filter"]:checked');
    const lowConf = confSel && confSel.value === 'low';
    const params = new URLSearchParams();
    if (dims.length > 0 && dims.length < 8) params.set('dim', dims.join(','));
    if (lowConf) params.set('low_conf', '1');
    const qs = params.toString();
    loadAndRender(qs ? ('?' + qs) : '');
  }

  document.querySelectorAll('.filter-dim').forEach(function (el) {
    el.addEventListener('change', reload);
  });
  document.querySelectorAll('input[name="conf-filter"]').forEach(function (el) {
    el.addEventListener('change', reload);
  });

  window.addEventListener('hashchange', handleHashJump);

  loadAndRender();
})();
