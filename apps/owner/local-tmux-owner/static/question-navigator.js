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

  function shouldRevealForScroll(delta, elapsedMs) {
    const distance = Math.abs(Number(delta) || 0);
    const elapsed = Math.max(1, Number(elapsedMs) || 0);
    return distance >= 48 || (distance >= 12 && distance / elapsed >= 0.45);
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
    let questions = [];
    let indexedQuestions = null;
    let active = -1;
    let enabled = true;
    let updateFrame = 0;
    let syncFrame = 0;
    let scrollingTimer = 0;
    let flashTimer = 0;
    let flashTarget = null;
    let loadingIndex = -1;
    let userScrollIntentUntil = 0;
    let lastScrollTop = Number(scroller.scrollTop || 0);
    let lastScrollAt = Number(view.performance?.now?.() || Date.now());

    const requestFrame = typeof view.requestAnimationFrame === 'function'
      ? view.requestAnimationFrame.bind(view)
      : (callback) => view.setTimeout(callback, 0);
    const cancelFrame = typeof view.cancelAnimationFrame === 'function'
      ? view.cancelAnimationFrame.bind(view)
      : view.clearTimeout.bind(view);

    function hidePreview() {
      navigator.classList.remove('is-interacting');
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
      navigator.classList.add('is-interacting');
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
      const loaded = targets.map((target, index) => ({ target, index })).filter((item) => item.target);
      if (!loaded.length) return;
      const positions = loaded.map((item) => item.target.getBoundingClientRect().top);
      const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 48;
      const loadedIndex = nearBottom ? loaded.length - 1 : activeIndex(positions, anchor);
      setActive(loaded[Math.max(0, loadedIndex)]?.index ?? 0);
    }

    function scheduleActiveUpdate() {
      if (updateFrame) return;
      updateFrame = requestFrame(updateActive);
    }

    function revealTemporarily() {
      navigator.classList.add('is-scrolling');
      if (scrollingTimer) view.clearTimeout(scrollingTimer);
      scrollingTimer = view.setTimeout(() => navigator.classList.remove('is-scrolling'), 1400);
    }

    function markUserScrollIntent(event) {
      const now = Number(view.performance?.now?.() || Date.now());
      userScrollIntentUntil = now + 500;
      if (event.type === 'wheel' && Math.abs(Number(event.deltaY || 0)) >= 48) revealTemporarily();
    }

    function noteScrolling() {
      const now = Number(view.performance?.now?.() || Date.now());
      const nextScrollTop = Number(scroller.scrollTop || 0);
      const delta = nextScrollTop - lastScrollTop;
      const elapsed = now - lastScrollAt;
      if (now <= userScrollIntentUntil && shouldRevealForScroll(delta, elapsed)) revealTemporarily();
      lastScrollTop = nextScrollTop;
      lastScrollAt = now;
      scheduleActiveUpdate();
    }

    function reset() {
      targets = [];
      questions = [];
      indexedQuestions = null;
      active = -1;
      loadingIndex = -1;
      markers.replaceChildren();
      navigator.classList.add('hidden');
      navigator.classList.remove('is-scrolling', 'is-interacting');
      navigator.setAttribute('aria-hidden', 'true');
      if (current) current.textContent = '0';
      if (total) total.textContent = '0';
      if (scrollingTimer) view.clearTimeout(scrollingTimer);
      scrollingTimer = 0;
      userScrollIntentUntil = 0;
      lastScrollTop = Number(scroller.scrollTop || 0);
      lastScrollAt = Number(view.performance?.now?.() || Date.now());
      hidePreview();
    }

    function sync(nextEnabled = true, nextQuestions) {
      enabled = nextEnabled !== false;
      if (!enabled) { reset(); return; }
      if (nextQuestions === null) {
        indexedQuestions = null;
      } else if (Array.isArray(nextQuestions)) {
        indexedQuestions = nextQuestions.map((item, index) => ({
          index: Number.isInteger(Number(item?.index)) ? Number(item.index) : index,
          key: String(item?.key || `question-${index}`),
          preview: previewText(item?.preview || '', 88),
        }));
      }
      const previousActiveKey = markers.querySelector('.question-nav-marker[aria-current="step"]')?.dataset.questionKey || '';
      const renderedTargets = [...output.querySelectorAll('.compact-block.user')];
      const renderedByKey = new Map(renderedTargets.map((target) => [
        target.dataset.faryoQuestionKey || target.dataset.faryoBlockKey || '',
        target,
      ]));
      if (indexedQuestions) {
        questions = indexedQuestions;
        targets = questions.map((question) => renderedByKey.get(question.key) || null);
      } else {
        targets = renderedTargets;
        questions = renderedTargets.map((target, index) => ({
          index,
          key: target.dataset.faryoQuestionKey || target.dataset.faryoBlockKey || `question-${index}`,
          preview: previewText(target.dataset.faryoQuestionPreview || target.textContent || '', 88),
        }));
      }
      if (questions.length < 2) {
        targets = [];
        active = -1;
        markers.replaceChildren();
        navigator.classList.add('hidden');
        navigator.setAttribute('aria-hidden', 'true');
        if (current) current.textContent = '0';
        if (total) total.textContent = String(questions.length);
        hidePreview();
        return;
      }

      const existing = new Map([...markers.querySelectorAll('.question-nav-marker')]
        .map((button) => [button.dataset.questionKey, button]));
      const retained = new Set();
      questions.forEach((question, index) => {
        const target = targets[index];
        const key = question.key;
        const text = question.preview;
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
        button.classList.toggle('unloaded', !target);
        button.classList.toggle('loading', loadingIndex === index);
        button.setAttribute('aria-busy', loadingIndex === index ? 'true' : 'false');
        button.setAttribute('aria-label', `Question ${index + 1} of ${questions.length}: ${text}`);
        button.title = text;
        if (target) {
          target.id = `faryo-question-${index + 1}`;
          button.setAttribute('aria-controls', target.id);
        } else {
          button.removeAttribute('aria-controls');
        }
        markers.appendChild(button);
        retained.add(button);
      });
      for (const button of [...markers.querySelectorAll('.question-nav-marker')]) {
        if (!retained.has(button)) button.remove();
      }

      if (total) total.textContent = String(questions.length);
      navigator.classList.remove('hidden');
      navigator.setAttribute('aria-hidden', 'false');
      const preservedIndex = previousActiveKey
        ? [...markers.querySelectorAll('.question-nav-marker')].findIndex((button) => button.dataset.questionKey === previousActiveKey)
        : -1;
      const firstLoaded = targets.findIndex(Boolean);
      setActive(preservedIndex >= 0 ? preservedIndex : (active >= 0 && active < questions.length ? active : Math.max(0, firstLoaded)), { reveal: false });
      scheduleActiveUpdate();
    }

    async function jumpTo(index) {
      const requested = Math.max(0, Math.min(Number(index) || 0, questions.length - 1));
      let target = targets[requested];
      if (!target && typeof options.resolveTarget === 'function') {
        loadingIndex = requested;
        sync(enabled);
        try {
          await options.resolveTarget(questions[requested], requested);
        } catch (_error) {
          return false;
        } finally {
          loadingIndex = -1;
          sync(enabled);
        }
        target = targets[requested];
      }
      if (!target) return false;
      revealTemporarily();
      const scrollerRect = scroller.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const maximum = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      const top = targetScrollTop(scroller.scrollTop, targetRect.top, scrollerRect.top, 20, maximum);
      const reducedMotion = Boolean(view.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
      if (typeof scroller.scrollTo === 'function') scroller.scrollTo({ top, behavior: reducedMotion ? 'auto' : 'smooth' });
      else scroller.scrollTop = top;
      setActive(requested);
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
      void jumpTo(Number(button.dataset.questionIndex || 0));
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
      if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = Math.min(questions.length - 1, index + 1);
      else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = Math.max(0, index - 1);
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = questions.length - 1;
      if (next === null) return;
      event.preventDefault();
      void jumpTo(next);
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
    scroller.addEventListener('wheel', markUserScrollIntent, { passive: true });
    scroller.addEventListener('touchstart', markUserScrollIntent, { passive: true });
    scroller.addEventListener('touchmove', markUserScrollIntent, { passive: true });
    scroller.addEventListener('pointerdown', markUserScrollIntent, { passive: true });
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
      scroller.removeEventListener('wheel', markUserScrollIntent);
      scroller.removeEventListener('touchstart', markUserScrollIntent);
      scroller.removeEventListener('touchmove', markUserScrollIntent);
      scroller.removeEventListener('pointerdown', markUserScrollIntent);
      view.removeEventListener('resize', scheduleActiveUpdate);
      if (updateFrame) cancelFrame(updateFrame);
      if (syncFrame) cancelFrame(syncFrame);
      if (scrollingTimer) view.clearTimeout(scrollingTimer);
      if (flashTimer) view.clearTimeout(flashTimer);
      reset();
    }

    return Object.freeze({ sync, reset, destroy, jumpTo, updateActive, get activeIndex() { return active; } });
  }

  return Object.freeze({ version: '3', previewText, activeIndex, targetScrollTop, shouldRevealForScroll, createController });
});
