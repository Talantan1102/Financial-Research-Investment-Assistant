// V3 cytoscape 鸟瞰 — 节点点击 → V2 modal。spec § 5.3。
(function () {
  const DIM_COLORS = {
    prompt_context: '#3b82f6',
    tools_function: '#06b6d4',
    orchestration: '#8b5cf6',
    memory: '#f59e0b',
    rag_knowledge: '#10b981',
    guardrails: '#ef4444',
    eval_observability: '#84cc16',
    cost_routing: '#ec4899',
  };

  let cy = null;

  function statusOpacity(status) {
    return status === 'lit' ? 1.0 : status === 'wip' ? 0.7 : 0.4;
  }

  function confidenceBorder(c) {
    // 灰 → 绿 渐变
    const stops = ['#cccccc', '#a8d8a8', '#80c080', '#5ca85c', '#3a903a', '#1a781a'];
    return stops[Math.max(0, Math.min(5, c || 0))];
  }

  async function loadAndRender(query) {
    query = query || '';
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
    cy = cytoscape({
      container: document.getElementById('overview-canvas'),
      elements: elements,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'font-size': 11,
            width: 'mapData(size, 1, 10, 30, 60)',
            height: 'mapData(size, 1, 10, 30, 60)',
            'background-color': function (ele) { return DIM_COLORS[ele.data('dimension')] || '#999'; },
            'background-opacity': function (ele) { return statusOpacity(ele.data('status')); },
            'border-width': 3,
            'border-color': function (ele) { return confidenceBorder(ele.data('confidence')); },
            'border-style': function (ele) { return ele.data('has_deep_card') ? 'solid' : 'dashed'; },
            'text-valign': 'bottom',
            'text-margin-y': 4,
          },
        },
        {
          selector: 'edge',
          style: {
            width: 1,
            'line-color': '#ccc',
            'curve-style': 'bezier',
            opacity: 0.6,
          },
        },
        {
          selector: '.cy-flash-highlight',
          style: {
            'background-color': 'yellow',
            'border-color': '#ff6600',
            'border-width': 5,
          },
        },
      ],
      layout: { name: 'cose-bilkent', animate: false, randomize: false },
    });

    cy.on('tap', 'node', async function (evt) {
      const id = evt.target.data('id');
      const overlay = document.getElementById('modal-overlay');
      if (!overlay) return;
      overlay.innerHTML = '<div class="modal-loading">载入...</div>';
      overlay.style.display = 'flex';
      try {
        const html = await (await fetch('/cap/' + encodeURIComponent(id))).text();
        overlay.innerHTML = html;
      } catch (e) {
        overlay.innerHTML = '<div class="error">modal 加载失败</div>';
      }
    });

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
