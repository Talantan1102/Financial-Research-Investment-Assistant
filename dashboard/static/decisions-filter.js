// dashboard/static/decisions-filter.js
// Client-side filter for /decisions:layer chip + state chip + keyword AND 关系
(function () {
  const cards = document.querySelectorAll(".decision-card");
  const layerChips = document.querySelectorAll(".filter-layer-chip");
  const stateChips = document.querySelectorAll(".filter-state-chip");
  const keywordInput = document.querySelector(".filter-keyword");

  function applyFilter() {
    const activeLayer = new Set(
      Array.from(layerChips)
        .filter(c => c.classList.contains("active"))
        .map(c => c.dataset.value)
    );
    const activeState = new Set(
      Array.from(stateChips)
        .filter(c => c.classList.contains("active"))
        .map(c => c.dataset.value)
    );
    const keyword = (keywordInput?.value || "").toLowerCase();

    cards.forEach(card => {
      const layer = card.dataset.layer;
      const state = card.dataset.state;
      const text = card.dataset.text;
      const layerOK = activeLayer.size === 0 || activeLayer.has(layer);
      const stateOK = activeState.size === 0 || activeState.has(state);
      const kwOK = !keyword || text.includes(keyword);
      card.style.display = layerOK && stateOK && kwOK ? "" : "none";
    });
  }

  layerChips.forEach(c => c.addEventListener("click", () => {
    c.classList.toggle("active");
    applyFilter();
  }));
  stateChips.forEach(c => c.addEventListener("click", () => {
    c.classList.toggle("active");
    applyFilter();
  }));
  keywordInput?.addEventListener("input", applyFilter);
})();
