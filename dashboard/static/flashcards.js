// flashcards.js — 翻面后 0-5 自评提交,X-Reviewed header 推进下一张
document.body.addEventListener('htmx:afterOnLoad', (evt) => {
  if (!evt.detail.xhr.getResponseHeader('X-Reviewed')) return;
  // 当前卡片已 swap 成 "✅ 已复习",下一张显示
  const reviewed = document.querySelectorAll('.flashcard[data-fc-reviewed]');
  const counter = document.getElementById('reviewed-count');
  if (counter) counter.textContent = reviewed.length;
  const next = document.querySelector('.flashcard:not([data-fc-reviewed])');
  if (next) next.style.display = '';
});
