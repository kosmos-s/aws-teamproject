'use strict';
// Applies the saved theme before the page paints. 'dark' (default) or 'light'.
(function () {
  let theme = 'dark';
  try { theme = localStorage.getItem('kosmos-theme') || (window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'); } catch {}
  document.documentElement.dataset.theme = theme === 'light' ? 'light' : 'dark';
})();
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('kosmos-theme', theme); } catch {}
  for (const b of document.querySelectorAll('[data-theme-choice]')) b.setAttribute('aria-pressed', String(b.dataset.themeChoice === theme));
  const t = document.getElementById('theme-toggle'); if (t) t.textContent = theme === 'light' ? '🌙 다크' : '☀ 라이트';
}
window.addEventListener('DOMContentLoaded', () => {
  setTheme(document.documentElement.dataset.theme);
  document.getElementById('theme-toggle')?.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'));
  for (const b of document.querySelectorAll('[data-theme-choice]')) b.addEventListener('click', () => setTheme(b.dataset.themeChoice));
});
