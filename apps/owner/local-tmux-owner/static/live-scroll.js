(function (root, factory) {
  'use strict';

  const api = factory();
  if (root) root.FaryoLiveScroll = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  function snapshot(pane, threshold = 48) {
    if (!pane) return null;
    const scrollHeight = Number(pane.scrollHeight || 0);
    const scrollTop = Number(pane.scrollTop || 0);
    const clientHeight = Number(pane.clientHeight || 0);
    return {
      scrollTop,
      followLatest: scrollHeight - scrollTop - clientHeight < threshold,
    };
  }

  function restore(pane, state) {
    if (!pane) return;
    const maximum = Math.max(0, Number(pane.scrollHeight || 0) - Number(pane.clientHeight || 0));
    pane.scrollTop = !state || state.followLatest
      ? maximum
      : Math.max(0, Math.min(Number(state.scrollTop || 0), maximum));
  }

  return { snapshot, restore };
});
