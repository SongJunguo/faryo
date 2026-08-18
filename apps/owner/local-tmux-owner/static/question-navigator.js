(function (root, factory) {
  'use strict';

  const api = factory(root);
  if (root) root.FaryoQuestionNavigator = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : null, function (root) {
  'use strict';

  function previewText(value, maxChars = 72) {
    const compact = String(value ?? '')
      .replace(/^\s*›\s*/u, '')
      .replace(/\s+/gu, ' ')
      .trim() || 'Untitled question';
    const chars = Array.from(compact);
    const limit = Math.max(8, Number(maxChars) || 72);
    return chars.length <= limit ? compact : `${chars.slice(0, limit - 1).join('')}…`;
  }

  function activeIndex(positions, anchor) {
    const values = Array.isArray(positions) ? positions : [];
    if (!values.length) return -1;
    const threshold = Number(anchor) || 0;
    let active = 0;
    for (let index = 0; index < values.length; index += 1) {
      if (Number(values[index]) <= threshold) active = index;
      else break;
    }
    return active;
  }

  function targetScrollTop(currentScrollTop, targetTop, scrollerTop, offset, maximum) {
    const requested = Number(currentScrollTop || 0)
      + Number(targetTop || 0)
      - Number(scrollerTop || 0)
      - Math.max(0, Number(offset || 0));
    return Math.max(0, Math.min(requested, Math.max(0, Number(maximum || 0))));
  }

  function createController(options = {}) {
    const view = options.view || root;
    const navigator = options.navigator;
    const markers = options.markers;
    const current = options.current;
    const total = options.total;
    const preview = options.preview;
    const scroller = options.scroller;
    const output = options.output;
    if (!view || !navigator || !markers || !scroller || !output) {
      throw new TypeError('Question navigation requires a view, navigator, markers, scroller, and output');
    }

    let targets = [];
    let active = -1;
    let enabled = true;
    let updateFrame = 0;
    let syncFrame = 0;
    let scrollingTimer = 0;
    let flashTimer = 0;
    let flashTarget = null;

    const requestFrame = typeof view.requestAnimationFrame === 'function'
      ? view.requestAnimationFrame.bind(view)
      : (callback) => view.setTimeout(callback, 0);
    const cancelFrame = typeof view.cancelAnimationFrame === 'function'
      ? view.cancelAnimationFrame.bind(view)
      : view.clearTimeout.bind(view);

    function hidePreview() {
      if (!preview) return;
      preview.classList.remove('visible');
      preview.setAttribute('aria-hidden', 'true');
    }

    function showPreview(button) {
      if (!preview || !button) return;
      const index = Number(button.dataset.questionIndex || 0);
      preview.textContent = `${index + 1}. ${button.dataset.questionPreview || 'Question'}`;
      const rect = button.getBoundingClientRect();
      const center = rect.top + rect.height / 2;
      preview.style.top = `${Math.max(48, Math.min(center, Number(view.innerHeight || 0) - 48))}px`;
      preview.style.right = `${Math.max(8, Number(view.innerWidth || 0) - rect.left + 8)}px`;
      preview.classList.add('visible');
      preview.setAttribute('aria-hidden', 'false');
    }

    function keepMarkerVisible(button) {
      if (!button) return;
      const top = Number(button.offsetTop || 0);
      const bottom = top + Number(button.offsetHeight || 0);
      const visibleTop = Number(markers.scrollTop || 0);
      const visibleBottom = visibleTop + Number(markers.clientHeight || 0);
      if (top < visibleTop) markers.scrollTop = Math.max(0, top - 4);
      else if (bottom > visibleBottom) markers.scrollTop = Math.max(0, bottom - markers.clientHeight + 4);
    }

    function setActive(index, { reveal = true } = {}) {
      if (!targets.length) index = -1;
      else index = Math.max(0, Math.min(Number(index) || 0, targets.length - 1));
      active = index;
      const buttons = [...markers.querySelectorAll('.question-nav-marker')];
      buttons.forEach((button, buttonIndex) => {
        const selected = buttonIndex === active;
        button.classList.toggle('active', selected);
        button.tabIndex = selected ? 0 : -1;
        if (selected) button.setAttribute('aria-current', 'step');
        else button.removeAttribute('aria-current');
      });
      if (current) current.textContent = active >= 0 ? String(active + 1) : '0';
      if (reveal && active >= 0) keepMarkerVisible(buttons[active]);
    }

    function updateActive() {
      updateFrame = 0;
      if (navigator.classList.contains('hidden') || !targets.length) return;
      const scrollerRect = scroller.getBoundingClientRect();
      const anchor = scrollerRect.top + Math.min(150, Math.max(72, scrollerRect.height * 0.22));
      const positions = targets.map((target) => target.getBoundingClientRect().top);
      const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 48;
      setActive(nearBottom ? targets.length - 1 : activeIndex(positions, anchor));
    }

    function scheduleActiveUpdate() {
      if (updateFrame) return;
      updateFrame = requestFrame(updateActive);
    }

    function noteScrolling() {
      navigator.classList.add('is-scrolling');
      if (scrollingTimer) view.clearTimeout(scrollingTimer);
      scrollingTimer = view.setTimeout(() => navigator.classList.remove('is-scrolling'), 850);
      scheduleActiveUpdate();
    }

    function reset() {
      targets = [];
      active = -1;
      markers.replaceChildren();
      navigator.classList.add('hidden');
      navigator.setAttribute('aria-hidden', 'true');
      scroller.classList.remove('question-navigation-visible');
      if (current) current.textContent = '0';
      if (total) total.textContent = '0';
      hidePreview();
    }

    function sync(nextEnabled = true) {
      enabled = nextEnabled !== false;
      if (!enabled) { reset(); return; }
      const previousActiveKey = markers.querySelector('.question-nav-marker[aria-current="step"]')?.dataset.questionKey || '';
      targets = [...output.querySelectorAll('.compact-block.user')];
      if (targets.length < 2) { reset(); return; }

      const existing = new Map([...markers.querySelectorAll('.question-nav-marker')]
        .map((button) => [button.dataset.questionKey, button]));
      const retained = new Set();
      targets.forEach((target, index) => {
        const key = target.dataset.faryoBlockKey || `question-${index}`;
        const text = previewText(target.dataset.faryoQuestionPreview || target.textContent || '', 88);
        let button = existing.get(key);
        if (!button) {
          button = view.document.createElement('button');
          button.type = 'button';
          button.className = 'question-nav-marker';
          const dot = view.document.createElement('span');
          dot.className = 'question-nav-dot';
          dot.setAttribute('aria-hidden', 'true');
          button.appendChild(dot);
        }
        button.dataset.questionKey = key;
        button.dataset.questionIndex = String(index);
        button.dataset.questionPreview = text;
        button.setAttribute('aria-label', `Question ${index + 1} of ${targets.length}: ${text}`);
        button.title = text;
        target.id = `faryo-question-${index + 1}`;
        button.setAttribute('aria-controls', target.id);
        markers.appendChild(button);
        retained.add(button);
      });
      for (const button of [...markers.querySelectorAll('.question-nav-marker')]) {
        if (!retained.has(button)) button.remove();
      }

      if (total) total.textContent = String(targets.length);
      navigator.classList.remove('hidden');
      navigator.setAttribute('aria-hidden', 'false');
      scroller.classList.add('question-navigation-visible');
      const preservedIndex = previousActiveKey
        ? [...markers.querySelectorAll('.question-nav-marker')].findIndex((button) => button.dataset.questionKey === previousActiveKey)
        : -1;
      setActive(preservedIndex >= 0 ? preservedIndex : (active >= 0 && active < targets.length ? active : 0), { reveal: false });
      scheduleActiveUpdate();
    }

    function jumpTo(index) {
      const target = targets[index];
      if (!target) return false;
      const scrollerRect = scroller.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const maximum = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      const top = targetScrollTop(scroller.scrollTop, targetRect.top, scrollerRect.top, 20, maximum);
      const reducedMotion = Boolean(view.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
      if (typeof scroller.scrollTo === 'function') scroller.scrollTo({ top, behavior: reducedMotion ? 'auto' : 'smooth' });
      else scroller.scrollTop = top;
      setActive(index);
      if (flashTarget) flashTarget.classList.remove('question-nav-flash');
      if (flashTimer) view.clearTimeout(flashTimer);
      flashTarget = target;
      target.classList.add('question-nav-flash');
      flashTimer = view.setTimeout(() => {
        target.classList.remove('question-nav-flash');
        if (flashTarget === target) flashTarget = null;
      }, 900);
      hidePreview();
      return true;
    }

    function markerFromEvent(event) {
      return event.target?.closest?.('.question-nav-marker');
    }

    function onClick(event) {
      const button = markerFromEvent(event);
      if (!button) return;
      event.preventDefault();
      jumpTo(Number(button.dataset.questionIndex || 0));
    }

    function onPointerOver(event) {
      const button = markerFromEvent(event);
      if (button) showPreview(button);
    }

    function onPointerOut(event) {
      const button = markerFromEvent(event);
      if (button && !button.contains(event.relatedTarget)) hidePreview();
    }

    function onFocusIn(event) {
      const button = markerFromEvent(event);
      if (button) showPreview(button);
    }

    function onFocusOut(event) {
      const button = markerFromEvent(event);
      if (button && !button.contains(event.relatedTarget)) hidePreview();
    }

    function onKeyDown(event) {
      const button = markerFromEvent(event);
      if (!button) return;
      const index = Number(button.dataset.questionIndex || 0);
      let next = null;
      if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = Math.min(targets.length - 1, index + 1);
      else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = Math.max(0, index - 1);
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = targets.length - 1;
      if (next === null) return;
      event.preventDefault();
      jumpTo(next);
      markers.querySelectorAll('.question-nav-marker')[next]?.focus();
    }

    function scheduleSync() {
      if (syncFrame) return;
      syncFrame = requestFrame(() => {
        syncFrame = 0;
        sync(enabled);
      });
    }

    markers.addEventListener('click', onClick);
    markers.addEventListener('pointerover', onPointerOver);
    markers.addEventListener('pointerout', onPointerOut);
    markers.addEventListener('focus', onFocusIn, true);
    markers.addEventListener('blur', onFocusOut, true);
    markers.addEventListener('keydown', onKeyDown);
    scroller.addEventListener('scroll', noteScrolling, { passive: true });
    view.addEventListener('resize', scheduleActiveUpdate);
    const observer = typeof view.MutationObserver === 'function'
      ? new view.MutationObserver(scheduleSync)
      : null;
    observer?.observe(output, { childList: true });

    function destroy() {
      observer?.disconnect();
      markers.removeEventListener('click', onClick);
      markers.removeEventListener('pointerover', onPointerOver);
      markers.removeEventListener('pointerout', onPointerOut);
      markers.removeEventListener('focus', onFocusIn, true);
      markers.removeEventListener('blur', onFocusOut, true);
      markers.removeEventListener('keydown', onKeyDown);
      scroller.removeEventListener('scroll', noteScrolling);
      view.removeEventListener('resize', scheduleActiveUpdate);
      if (updateFrame) cancelFrame(updateFrame);
      if (syncFrame) cancelFrame(syncFrame);
      if (scrollingTimer) view.clearTimeout(scrollingTimer);
      if (flashTimer) view.clearTimeout(flashTimer);
      reset();
    }

    return Object.freeze({ sync, reset, destroy, jumpTo, updateActive, get activeIndex() { return active; } });
  }

  return Object.freeze({ version: '1', previewText, activeIndex, targetScrollTop, createController });
});
