(() => {
  'use strict';

  const APPEARANCE = {
    theme: { key: 'faryoTheme', values: ['system', 'light', 'dark'], title: 'Theme', labels: { system: 'System', light: 'Light', dark: 'Dark' } },
    font: { key: 'faryoFont', values: ['default', 'serif', 'rounded', 'mono'], title: 'Font', labels: { default: 'Default', serif: 'Serif', rounded: 'Rounded', mono: 'Mono' } },
    size: { key: 'faryoTextSize', values: ['normal', 'large', 'small'], title: 'Size', labels: { normal: 'Normal', large: 'Large', small: 'Small' } },
  };
  const themeMedia = window.matchMedia?.('(prefers-color-scheme: dark)');
  const themeColors = { light: '#F7F0E5', dark: '#17130F' };
  const ownerWorkbenchThemeColors = { light: '#F6F7F9', dark: '#0F1115' };

  function value(name) {
    const cfg = APPEARANCE[name], current = localStorage.getItem(cfg.key);
    return cfg.values.includes(current) ? current : cfg.values[0];
  }

  function resolvedTheme(theme = value('theme')) {
    return theme === 'dark' || (theme === 'system' && themeMedia?.matches) ? 'dark' : 'light';
  }

  function updateThemeColor(theme = value('theme')) {
    const colors = document.documentElement.dataset.faryoUi === 'workbench-v2'
      ? ownerWorkbenchThemeColors
      : themeColors;
    const color = colors[resolvedTheme(theme)];
    document.querySelectorAll('meta[name="theme-color"]').forEach(meta => { meta.content = color; });
  }

  function updateButton(name, current) {
    const cfg = APPEARANCE[name], button = document.getElementById(`${name}Btn`);
    if (!button) return;
    const title = button.querySelector('strong'), meta = button.querySelector('small');
    if (title && meta) {
      title.textContent = cfg.title;
      meta.textContent = cfg.labels[current];
    } else {
      button.textContent = `${cfg.title}: ${cfg.labels[current]}`;
    }
  }

  function apply() {
    const root = document.documentElement;
    const theme = value('theme');
    root.setAttribute('data-theme', resolvedTheme(theme));
    updateButton('theme', theme);
    for (const name of ['font', 'size']) {
      const current = value(name), cfg = APPEARANCE[name];
      if (current === cfg.values[0]) root.removeAttribute(`data-${name}`);
      else root.setAttribute(`data-${name}`, current);
      updateButton(name, current);
    }
    updateThemeColor(theme);
  }

  function cycle(name) {
    const cfg = APPEARANCE[name];
    if (!cfg) return;
    localStorage.setItem(cfg.key, cfg.values[(cfg.values.indexOf(value(name)) + 1) % cfg.values.length]);
    apply();
  }

  apply();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, { once: true });
  else apply();
  themeMedia?.addEventListener?.('change', () => { if (value('theme') === 'system') apply(); });
  window.addEventListener('storage', event => {
    if (!event.key || Object.values(APPEARANCE).some(cfg => cfg.key === event.key)) apply();
  });

  window.FaryoAppearance = { apply, cycle, value, resolvedTheme, updateThemeColor, config: APPEARANCE };
})();
