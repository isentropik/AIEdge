// Follow the device theme by default; an optional preference stays on this browser.
(() => {
  const key = 'aiedge-installer-theme';
  let theme = 'system';
  try { const saved = localStorage.getItem(key); if (saved === 'light' || saved === 'dark') theme = saved; } catch {}
  const apply = () => {
    if (theme === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
  };
  apply(); // Before the stylesheet renders, so a saved dark theme does not flash white.
  document.addEventListener('DOMContentLoaded', () => {
    const picker = document.getElementById('theme');
    picker.value = theme;
    picker.addEventListener('change', () => {
      theme = picker.value;
      apply();
      try { if (theme === 'system') localStorage.removeItem(key); else localStorage.setItem(key, theme); } catch {}
    });
  });
})();
