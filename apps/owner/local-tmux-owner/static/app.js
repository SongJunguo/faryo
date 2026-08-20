(async () => {
  'use strict';
  // Workspace review is an optional surface. Start loading it immediately,
  // but never let a transient asset failure block capture/history rendering.
  const changesPanelModulePromise = import("./owner/changes-panel.mjs?v=faryo-owner-changes-1");

  const $ = (id) => document.getElementById(id);
  const outputWrap = $('outputWrap');
  const output = $('output');
  const promptInput = $('promptInput');
  const attachmentInput = $('attachmentInput');
  const attachmentPreview = $('attachmentPreview');
  const errorBox = $('errorBox');
  const phasePill = $('phasePill');
  const bottomBtn = $('bottomBtn');
  const questionNavigatorElement = $('questionNavigator');
  const questionNavMarkers = $('questionNavMarkers');
  const questionNavPreview = $('questionNavPreview');
  const dockMenu = $('dockMenu');
  const sessionMenu = $('sessionMenu');
  const detailsPanel = $('detailsPanel');
  const changesPanel = $('changesPanel');
  const panelBackdrop = $('panelBackdrop');
  const commandSuggest = $('commandSuggest');
  const promptShell = document.querySelector('.prompt-shell');
  const metaLineRe = /^\s*(gpt|o\d)[\w.\- ]*·\s+/;
  const codexCompactRules = window.FaryoCodexCompactRules || {};
  const markdownRenderer = window.FaryoMarkdownAst || {};
  const internalAnnotations = window.FaryoInternalAnnotations || {};
  const eventStreamParser = window.FaryoEventStream || {};
  const stableBlocks = window.FaryoStableBlocks || {};
  const questionNavigatorApi = window.FaryoQuestionNavigator || {};
  const codexCommandApi = window.FaryoCodexCommands || {};
  const copyFidelityApi = window.FaryoCopyFidelity || {};
  const clipboardImageApi = window.FaryoClipboardImages || {};
  const immersiveModeApi = window.FaryoImmersiveMode || {};
  const scrollSurfaceApi = window.FaryoScrollSurface || {};
  document.documentElement.dataset.faryoClipboardPaste = (
    typeof clipboardImageApi.filesFromClipboard === 'function'
    && typeof clipboardImageApi.insertText === 'function'
  ) ? 'ready' : 'unavailable';
  const copyFidelity = typeof copyFidelityApi.create === 'function'
    ? copyFidelityApi.create({ root: output, parseMarkdown: (source) => markdownRenderer.parse(source) })
    : null;
  document.documentElement.dataset.faryoCopy = copyFidelity ? 'ready' : 'unavailable';
  const runtimeCompactRules = {
    userPromptRe: /^\s*›\s+/,
    compactBlocks: (text) => [{ kind: 'output', text: text || 'No output yet' }],
    processSummaryCard: (text) => text || '',
    approvalPendingRe: /(?:^|\n)\s*(?:Reviewing(?:\s+\d+)?\s+approval requests?(?:\s+\(|\s*$)|Automatic approval review\b|Approval requested\b|Allow Codex to run\b|Would you like to (?:run the following command|make the following edits|grant these permissions)\?)/i,
  };
  const COMPACT_CAPTURE_LINES = 320, FULL_CAPTURE_LINES = 800;
  const FETCH_TIMEOUT_MS = 12000, MAX_ATTACHMENTS = 5;
  const TIP_REFRESH_MS = 120000, STATUS_REFRESH_MS = 20000, FULL_REFRESH_MS = 10000, CAPTURE_FALLBACK_MS = 2500;
  const WORKBENCH_CACHE_KEY = 'faryoWorkbenchSnapshot', WORKBENCH_CACHE_MS = 120000;
  const PET_SEND_MS = 1500;
  const PET_STOP_MS = 850;
  const PET_RUN_DECAY_MS = 1200;
  const IMAGE_MAX_EDGE = 1280, IMAGE_JPEG_QUALITY = 0.60;
  const PROMPT_TIPS = [
    'Tap pet to interrupt',
    'Tap + for tools',
    'Type / for commands',
    'Type cd for recent dirs',
    'Ctrl/⌘ Enter sends',
    'Tap Enter for the TUI choice',
    'Raw shows terminal',
    'Tap Raw again to lock',
    'Tap ↓ for latest',
    '⧉ copies last output',
    'Tap title to fold header',
    'Tap the Faryo logo for home',
    'Tap expand for full screen',
    'Tap version to fold footer',
    'Tap folder to switch sessions',
    'Set font on home',
  ];
  let captureRefreshInFlight = false, pendingCaptureRefreshLines = null, pendingDeferredCapture = null, activeCaptureRefreshController = null, captureRefreshRunId = 0;
  let statusRefreshInFlight = false, activeStatusRefreshController = null, statusRefreshRunId = 0, statusRefreshTimer = null;
  let eventStreamController = null, eventStreamRunId = 0, eventRetryTimer = null, captureFallbackTimer = null, eventRetryDelayMs = 1800, liveState = 'fallback';
  let petSending = false, petSendTimer = null, petStopping = false, petStopTimer = null, agentRunning = false, lastPetPhase = '';
  let outputActivity = 0, outputActivityTimer = null, lastCaptureSignature = '', lastCompactCapture = null, lastFullCapture = null;
  let outputMode = 'compact', fullLocked = false, fullRefreshTimer = null, preserveErrorUntil = 0, seenInitialPageShow = false, needsConfirmUI = false, errorTimer = null, currentPromptTip = '';
  let markdownRenderRevision = 0, highlighterRenderFrame = 0;
  const markdownHtmlCache = new Map();
  let pendingAttachments = [];
  const routeMatch = location.pathname.match(/^\/(hp|pc|txy)(?:\/|$)/);
  const routeBase = routeMatch ? `/${routeMatch[1]}` : '';
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone;
  const useDocumentScroller = typeof scrollSurfaceApi.shouldUseDocumentScroller === 'function'
    && scrollSurfaceApi.shouldUseDocumentScroller({ routeBase, width: window.innerWidth, standalone: Boolean(isStandalone) });
  const conversationScroller = useDocumentScroller && typeof scrollSurfaceApi.createDocumentScroller === 'function'
    ? scrollSurfaceApi.createDocumentScroller(window)
    : outputWrap;
  document.documentElement.classList.toggle('document-scroll-mode', useDocumentScroller);
  document.documentElement.dataset.faryoScrollSurface = useDocumentScroller ? 'document' : 'conversation';
  const params = new URLSearchParams(location.search);
  const OWNER_TOKEN_STORAGE_KEY = 'faryoOwnerToken:v1';
  const queryOwnerToken = params.get('token') || '';
  let ownerToken = queryOwnerToken;
  try {
    if (queryOwnerToken) sessionStorage.setItem(OWNER_TOKEN_STORAGE_KEY, queryOwnerToken);
    else ownerToken = sessionStorage.getItem(OWNER_TOKEN_STORAGE_KEY) || '';
  } catch (_err) {}
  if (queryOwnerToken) {
    params.delete('token');
    const cleanQuery = params.toString();
    history.replaceState(null, '', `${location.pathname}${cleanQuery ? `?${cleanQuery}` : ''}${location.hash}`);
  }
  let gatewayCsrfToken = '';
  let selectedSession = params.get('session') || '';
  const HISTORY_PAGE_TURNS = 12;
  const HISTORY_REFRESH_MIN_MS = 2500;
  let conversationHistory = {
    revision: '', sessionId: '', totalTurns: 0, questions: [], turns: new Map(),
    loadedStart: null, loadedEnd: 0, olderCursor: '', initialized: false,
  };
  let historyLoadPromise = null, historyRequestController = null, historyRefreshTimer = null;
  let historyRunId = 0, historyCaptureSignature = '', historyLastRefreshAt = 0;
  let historyUserIntentUntil = 0, historyOlderLoadQueued = false;
  let initialLatestScrollPending = true, initialLatestScrollTimer = null;
  let submitInFlight = false, pendingSubmission = null;
  let activeSurfacePanel = null, panelReturnFocus = null;
  let immersiveController = null;
  const restoringLivePanels = new WeakSet();
  let questionNavigatorController = null;
  let commandSuggestionIndex = 0, commandSuggestionSignature = '';
  if (typeof questionNavigatorApi.createController === 'function') {
    try {
      questionNavigatorController = questionNavigatorApi.createController({
        view: window,
        navigator: questionNavigatorElement,
        markers: questionNavMarkers,
        current: $('questionNavCurrent'),
        total: $('questionNavTotal'),
        preview: questionNavPreview,
        scroller: conversationScroller,
        output,
        resolveTarget: resolveQuestionTarget,
      });
    } catch (_error) {
      questionNavigatorController = null;
    }
  }

  function setWorkbenchInert(inert) {
    for (const element of [document.querySelector('header'), outputWrap, document.querySelector('footer'), questionNavigatorElement]) {
      if (element) element.inert = inert;
    }
  }

  function panelFocusable(panel) {
    if (!panel) return [];
    return [...panel.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
      .filter((element) => element.getClientRects().length > 0);
  }

  function closeSurfacePanels({ restoreFocus = true } = {}) {
    const returnFocus = panelReturnFocus;
    for (const panel of [sessionMenu, detailsPanel, changesPanel]) panel?.classList.add('hidden');
    panelBackdrop?.classList.add('hidden');
    panelBackdrop?.setAttribute('aria-hidden', 'true');
    document.documentElement.classList.remove('panel-open');
    $('draftState')?.setAttribute('aria-expanded', 'false');
    $('detailsBtn')?.setAttribute('aria-expanded', 'false');
    setWorkbenchInert(false);
    activeSurfacePanel = null;
    panelReturnFocus = null;
    if (restoreFocus && returnFocus?.isConnected) requestAnimationFrame(() => returnFocus.focus());
  }

  function openSurfacePanel(panel, trigger) {
    if (!panel) return;
    if (activeSurfacePanel === panel && !panel.classList.contains('hidden')) {
      closeSurfacePanels();
      return;
    }
    if (activeSurfacePanel) closeSurfacePanels({ restoreFocus: false });
    closeDockMenu();
    activeSurfacePanel = panel;
    panelReturnFocus = trigger || document.activeElement;
    panel.classList.remove('hidden');
    panelBackdrop?.classList.remove('hidden');
    panelBackdrop?.setAttribute('aria-hidden', 'false');
    document.documentElement.classList.add('panel-open');
    $('draftState')?.setAttribute('aria-expanded', panel === sessionMenu ? 'true' : 'false');
    $('detailsBtn')?.setAttribute('aria-expanded', panel === detailsPanel ? 'true' : 'false');
    setWorkbenchInert(true);
    requestAnimationFrame(() => (panel.querySelector('[data-close-panel]') || panelFocusable(panel)[0])?.focus());
  }

  function trapSurfacePanelFocus(event) {
    if (event.key !== 'Tab' || !activeSurfacePanel) return;
    const focusable = panelFocusable(activeSurfacePanel);
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  function promptDraftKey(session = selectedSession) { return `faryoPromptDraft:${routeBase || 'owner'}:${session || 'default'}`; }
  function pendingSubmissionKey(session = selectedSession) { return `${promptDraftKey(session)}:pending`; }
  function persistPromptDraft(session = selectedSession, value = promptInput.value) {
    try {
      if (value) sessionStorage.setItem(promptDraftKey(session), value);
      else sessionStorage.removeItem(promptDraftKey(session));
    } catch (_err) {}
  }
  function persistPendingSubmission(submission = pendingSubmission, session = submission?.session || selectedSession) {
    try {
      if (submission) sessionStorage.setItem(pendingSubmissionKey(session), JSON.stringify(submission));
      else sessionStorage.removeItem(pendingSubmissionKey(session));
    } catch (_err) {}
  }
  function clearPendingSubmission(submission) {
    if (!submission?.session) return;
    persistPendingSubmission(null, submission.session);
  }
  function clearDeliveredPromptDraft(submission) {
    try {
      const key = promptDraftKey(submission.session);
      if (sessionStorage.getItem(key) === submission.browserText) sessionStorage.removeItem(key);
    } catch (_err) {}
  }
  function preserveFailedPromptDraft(submission) {
    try {
      const key = promptDraftKey(submission.session);
      if (sessionStorage.getItem(key) === null) sessionStorage.setItem(key, submission.browserText);
      if (sessionStorage.getItem(key) === submission.browserText) persistPendingSubmission(submission, submission.session);
    } catch (_err) {}
  }
  function restorePromptDraft() {
    try {
      promptInput.value = sessionStorage.getItem(promptDraftKey()) || '';
      const restored = JSON.parse(sessionStorage.getItem(pendingSubmissionKey()) || 'null');
      pendingSubmission = restored?.browserText === promptInput.value && (!restored.session || restored.session === selectedSession)
        ? { ...restored, session: selectedSession }
        : null;
      if (pendingSubmission && restored.session !== selectedSession) persistPendingSubmission(pendingSubmission, selectedSession);
      if (!pendingSubmission) sessionStorage.removeItem(pendingSubmissionKey());
    } catch (_err) {
      pendingSubmission = null;
    }
  }
  function newClientMessageId() {
    if (window.crypto?.randomUUID) return `web-${window.crypto.randomUUID()}`;
    return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
  }

  document.documentElement.classList.toggle('standalone', Boolean(isStandalone));
  document.documentElement.dataset.faryoDisplayMode = isStandalone ? 'standalone' : 'browser';
  if (typeof immersiveModeApi.createController === 'function') {
    immersiveController = immersiveModeApi.createController({
      document,
      target: document.documentElement,
      root: document.documentElement,
      toggleButtons: [$('immersiveBtn'), $('detailsFullscreenBtn')],
      exitButton: $('immersiveExitBtn'),
      onChange: (active) => {
        if (active && activeSurfacePanel) closeSurfacePanels({ restoreFocus: false });
        syncKeyboardState();
      },
      onError: (reason) => {
        if (activeSurfacePanel) closeSurfacePanels({ restoreFocus: false });
        setError(reason === 'unsupported'
          ? 'Full screen is unavailable here. Install Faryo from Home for an app-style window.'
          : 'The browser did not enter full screen. Try again from a direct tap, or install Faryo from Home.');
      },
    });
  }
  document.documentElement.dataset.faryoImmersive = immersiveController ? 'ready' : 'unavailable';
  restorePromptDraft();
  promptInput.addEventListener('input', () => {
    if (pendingSubmission?.browserText !== promptInput.value) {
      const staleSubmission = pendingSubmission;
      pendingSubmission = null;
      persistPendingSubmission(null, staleSubmission?.session || selectedSession);
    }
    persistPromptDraft();
    autosize();
    updateSendVisibility();
    renderCommandSuggestions();
  });

  function syncKeyboardState() {
    const viewport = window.visualViewport;
    const keyboardOpen = viewport ? window.innerHeight - viewport.height > Math.max(110, window.innerHeight * 0.16) : false;
    document.documentElement.classList.toggle('keyboard-open', keyboardOpen || document.activeElement === promptInput);
    updateSendVisibility();
    renderCommandSuggestions();
  }
  promptInput.addEventListener('focus', syncKeyboardState);
  promptInput.addEventListener('blur', () => setTimeout(syncKeyboardState, 120));
  promptInput.addEventListener('blur', () => setTimeout(() => commandSuggest?.classList.add('hidden'), 120));
  window.visualViewport?.addEventListener('resize', syncKeyboardState);
  window.visualViewport?.addEventListener('scroll', syncKeyboardState);
  window.addEventListener('resize', syncKeyboardState);
  syncKeyboardState();
  function fitPromptTip(text) { return Array.from(text || '').length > 22 ? Array.from(text).slice(0, 21).join('') + '...' : text; }
  function setPromptTip(tip) { currentPromptTip = tip || PROMPT_TIPS[0]; promptInput.placeholder = fitPromptTip(currentPromptTip); promptInput.title = currentPromptTip; }

  function rotatePromptTip() {
    if (promptInput.value) return;
    const pool = PROMPT_TIPS.filter((tip) => tip !== currentPromptTip);
    setPromptTip(pool[Math.floor(Math.random() * pool.length)] || PROMPT_TIPS[0]);
    autosize();
  }
  rotatePromptTip();
  setInterval(rotatePromptTip, TIP_REFRESH_MS);

  function autosize() {
    if (!promptInput.value) {
      promptInput.style.height = '';
      promptInput.style.overflowY = 'hidden';
      return;
    }
    promptInput.style.height = 'auto';
    promptInput.style.overflowY = promptInput.scrollHeight > 136 ? 'auto' : 'hidden';
    promptInput.style.height = Math.min(promptInput.scrollHeight, 136) + 'px';
  }
  autosize();

  let recentDirFetchAt = 0;
  function recentDirCommands() {
    const data = cachedWorkbench();
    if (!data && Date.now() - recentDirFetchAt > 30000) { recentDirFetchAt = Date.now(); refreshSessionMenu().then(() => renderCommandSuggestions()).catch(() => {}); }
    const route = routeBase.replace('/', '');
    const seen = new Set(), items = [];
    const sessions = (data?.sessions || []).slice().sort((a, b) => Number(b.updatedTs || 0) - Number(a.updatedTs || 0));
    for (const item of sessions) {
      const cwd = String(item.cwd || '').trim();
      if (!cwd || cwd === '~' || (route && String(item.route || '') !== route) || seen.has(cwd)) continue;
      if (String(item.tmuxSession || '') === selectedSession && String(item.route || '') === route) continue;
      seen.add(cwd);
      items.push(`cd ${cwd}`);
      if (items.length >= 4) break;
    }
    return items;
  }
  function commandMatches() {
    if (typeof codexCommandApi.match !== 'function') return [];
    const query = promptInput.value.trimStart().toLowerCase();
    return codexCommandApi.match(promptInput.value, { recentDirectories: query.startsWith('cd') ? recentDirCommands() : [], limit: 64 });
  }
  function applyCommandSuggestion(item) {
    const value = String(item?.value || item || '');
    if (!value) return false;
    promptInput.value = value;
    promptInput.focus();
    promptInput.setSelectionRange(value.length, value.length);
    commandSuggestionIndex = 0;
    commandSuggestionSignature = '';
    persistPromptDraft();
    autosize();
    updateSendVisibility();
    renderCommandSuggestions();
    return true;
  }
  function renderCommandSuggestions() {
    const items = commandMatches();
    if (!commandSuggest) return;
    const signature = `${promptInput.value}\n${items.map((item) => item.value).join('\n')}`;
    if (signature !== commandSuggestionSignature) {
      commandSuggestionSignature = signature;
      commandSuggestionIndex = 0;
    }
    commandSuggestionIndex = Math.min(commandSuggestionIndex, Math.max(0, items.length - 1));
    commandSuggest.classList.toggle('hidden', !items.length);
    commandSuggest.setAttribute('aria-activedescendant', items.length ? `command-option-${commandSuggestionIndex}` : '');
    if (!items.length) {
      commandSuggest.replaceChildren();
      return;
    }
    const summary = promptInput.value.trimStart() === '/' ? `<div class="command-suggest-summary">${items.length} Codex commands · ↑↓ to explore</div>` : '';
    commandSuggest.innerHTML = summary + items.map((item, index) => {
      const selected = index === commandSuggestionIndex;
      const label = item.matchedAlias || item.command || item.value;
      const aliases = !item.matchedAlias && item.aliases?.length ? ` · ${item.aliases.join(', ')}` : '';
      const hint = item.argumentHint ? ` ${item.argumentHint}` : '';
      const risk = item.risk ? `<span class="command-risk">${escapeHtml(item.risk)}</span>` : '';
      return `<button id="command-option-${index}" type="button" role="option" aria-selected="${selected}" data-index="${index}" class="${selected ? 'selected' : ''}"><span class="command-suggest-main"><strong>${escapeHtml(label)}${escapeHtml(hint)}</strong><small>${escapeHtml(item.description || '')}</small></span><span class="command-suggest-meta">${escapeHtml(item.category || 'Command')}${escapeHtml(aliases)}${risk}</span></button>`;
    }).join('');
  }
  function handleCommandSuggestionKey(event) {
    const items = commandMatches();
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && items.length) {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      commandSuggestionIndex = (commandSuggestionIndex + delta + items.length) % items.length;
      renderCommandSuggestions();
      requestAnimationFrame(() => commandSuggest?.querySelector('.selected')?.scrollIntoView({ block: 'nearest' }));
      return true;
    }
    const item = items[commandSuggestionIndex] || items[0];
    if ((event.key === 'Tab' || event.key === 'Enter') && item) {
      event.preventDefault();
      return applyCommandSuggestion(item);
    }
    if (event.key === 'Escape') {
      commandSuggest?.classList.add('hidden');
      commandSuggestionSignature = '';
    }
    return false;
  }
  commandSuggest?.addEventListener('mousedown', (event) => event.preventDefault());
  commandSuggest?.addEventListener('click', (event) => {
    const index = Number(event.target.closest('button')?.dataset.index);
    const item = commandMatches()[index];
    if (item) applyCommandSuggestion(item);
  });
  for (const id of ['petControl', 'dockPlusBtn']) $(id)?.addEventListener('pointerdown', (event) => event.preventDefault());

  function updateSendVisibility() {
    const ready = promptInput.value.trim() || pendingAttachments.length > 0;
    const docked = !document.documentElement.classList.contains('keyboard-open');
    $('sendBtn')?.classList.toggle('hidden', !ready);
    $('dockPlusBtn')?.classList.toggle('hidden', Boolean(ready && docked));
    updatePetControl();
  }
  updateSendVisibility();

  function isNearBottom() { return conversationScroller.scrollHeight - conversationScroller.scrollTop - conversationScroller.clientHeight < 80; }
  function updateBottomButton() {
    if (pendingDeferredCapture && isNearBottom()) { applyDeferredCapture(true); return; }
    bottomBtn.classList.toggle('hidden', isNearBottom());
  }

  function applyDeferredCapture(force = false) {
    if (!pendingDeferredCapture) return false;
    if (!force && !isNearBottom()) return false;
    const capture = pendingDeferredCapture;
    pendingDeferredCapture = null;
    renderOutput(capture);
    scrollBottom(true);
    return true;
  }

  function renderCaptureWhenSafe(capture, keepBottom) {
    noteOutputActivity(capture);
    const previousScrollTop = conversationScroller.scrollTop;
    pendingDeferredCapture = null;
    renderOutput(capture);
    if (initialLatestScrollPending) applyInitialLatestScroll(capture?.captureSource !== 'codex-jsonl');
    else if (keepBottom) scrollBottom(true);
    else requestAnimationFrame(() => {
      conversationScroller.scrollTop = previousScrollTop;
      updateBottomButton();
    });
  }

  function scrollBottom(force = false) {
    if (force || isNearBottom()) {
      requestAnimationFrame(() => {
        conversationScroller.scrollTop = conversationScroller.scrollHeight;
        updateBottomButton();
      });
    }
  }

  function beginInitialLatestScroll() {
    initialLatestScrollPending = true;
    if (initialLatestScrollTimer) clearTimeout(initialLatestScrollTimer);
    initialLatestScrollTimer = null;
  }

  function cancelInitialLatestScroll() {
    initialLatestScrollPending = false;
    if (initialLatestScrollTimer) clearTimeout(initialLatestScrollTimer);
    initialLatestScrollTimer = null;
  }

  function applyInitialLatestScroll(final = false) {
    if (!initialLatestScrollPending || Date.now() <= historyUserIntentUntil) return false;
    const apply = () => {
      if (!initialLatestScrollPending || Date.now() <= historyUserIntentUntil) return;
      conversationScroller.scrollTop = conversationScroller.scrollHeight;
      updateBottomButton();
    };
    requestAnimationFrame(() => {
      apply();
      requestAnimationFrame(apply);
    });
    if (final) {
      if (initialLatestScrollTimer) clearTimeout(initialLatestScrollTimer);
      initialLatestScrollTimer = setTimeout(() => {
        if (!initialLatestScrollPending || Date.now() <= historyUserIntentUntil) return;
        apply();
        initialLatestScrollPending = false;
        initialLatestScrollTimer = null;
      }, 500);
    }
    return true;
  }

  function livePanelStorageKey(session = selectedSession) {
    return `faryoLiveExpanded:${routeBase || 'owner'}:${session || 'default'}`;
  }

  function storedLivePanelPreference(session = selectedSession) {
    try { return sessionStorage.getItem(livePanelStorageKey(session)); }
    catch (_err) { return null; }
  }

  function persistLivePanelPreference(session, expanded) {
    try { sessionStorage.setItem(livePanelStorageKey(session), expanded ? '1' : '0'); }
    catch (_err) {}
  }

  function liveTerminalState() {
    const panel = output.querySelector('.compact-live-terminal');
    if (!panel) return null;
    const expanded = panel.open === true;
    return {
      session: panel.dataset.session || selectedSession,
      expanded,
      scroll: expanded ? (window.FaryoLiveScroll?.snapshot(panel.querySelector('pre')) || null) : null,
    };
  }

  function resolvedLivePanelExpanded(state, session = selectedSession) {
    if (typeof window.FaryoLiveScroll?.resolveExpanded === 'function') {
      return window.FaryoLiveScroll.resolveExpanded(session, state, storedLivePanelPreference(session), window.innerWidth);
    }
    if (state?.session === session && typeof state.expanded === 'boolean') return state.expanded;
    const stored = storedLivePanelPreference(session);
    return stored === '1' || (stored !== '0' && window.innerWidth >= 720);
  }

  function restoreLiveTerminalState(state) {
    const panel = output.querySelector('.compact-live-terminal');
    if (!panel) return;
    const expanded = resolvedLivePanelExpanded(state, selectedSession);
    restoringLivePanels.add(panel);
    panel.open = expanded;
    requestAnimationFrame(() => {
      if (expanded) {
        window.FaryoLiveScroll?.restore(
          panel.querySelector('pre'),
          state?.session === selectedSession ? state.scroll : null,
        );
      }
      setTimeout(() => restoringLivePanels.delete(panel), 0);
    });
  }

  function selectionInsideLivePanel(panel) {
    const selection = window.getSelection?.();
    if (!panel || !selection || selection.isCollapsed) return false;
    return panel.contains(selection.anchorNode) || panel.contains(selection.focusNode);
  }

  function liveLineCount(text) {
    return String(text || '').split('\n').filter((line) => line.length).length;
  }

  function updateLivePanelLabel(panel, text, paused = false) {
    const label = panel?.querySelector('.compact-live-state');
    if (!label) return;
    const lines = liveLineCount(text);
    label.textContent = paused ? `Updates paused · ${lines} lines ready` : `Agent working · ${lines} lines`;
  }

  function createLiveTerminalPanel() {
    const panel = document.createElement('details');
    panel.className = 'compact-live-terminal';
    panel.dataset.session = selectedSession || 'default';
    panel.dataset.faryoTransient = 'live';
    panel.dataset.liveRevision = '0';
    panel.innerHTML = '<summary class="compact-live-title"><span class="live-dot"></span><span>Live from tmux</span><span class="compact-live-state">Agent working</span><button class="compact-live-copy" type="button" aria-label="Copy Live from tmux" title="Copy Live from tmux">⧉</button></summary><pre></pre>';
    output.appendChild(panel);
    return panel;
  }

  function commitLiveTerminalText(panel, text, state = null) {
    const pre = panel?.querySelector('pre');
    if (!pre) return;
    const scrollState = state || liveTerminalState();
    pre.textContent = String(text || '');
    panel.__faryoPendingLiveText = null;
    panel.__faryoPendingLiveRemoval = false;
    panel.dataset.liveRevision = String(Number(panel.dataset.liveRevision || 0) + 1);
    updateLivePanelLabel(panel, text, false);
    restoreLiveTerminalState(scrollState);
  }

  function syncLiveTerminal(text, state = null) {
    const value = String(text || '');
    let panel = output.querySelector('.compact-live-terminal');
    if (!value) {
      if (!panel) return;
      if (selectionInsideLivePanel(panel)) {
        panel.__faryoPendingLiveRemoval = true;
        const label = panel.querySelector('.compact-live-state');
        if (label) label.textContent = 'Finished · selection held';
      } else {
        panel.remove();
      }
      return;
    }
    if (!panel) panel = createLiveTerminalPanel();
    panel.dataset.session = selectedSession || 'default';
    panel.__faryoPendingLiveRemoval = false;
    const pre = panel.querySelector('pre');
    if (pre?.textContent === value && !panel.__faryoPendingLiveText) return;
    if (selectionInsideLivePanel(panel)) {
      panel.__faryoPendingLiveText = value;
      updateLivePanelLabel(panel, value, true);
      return;
    }
    commitLiveTerminalText(panel, value, state);
  }

  function flushDeferredLiveTerminal() {
    const panel = output.querySelector('.compact-live-terminal');
    if (!panel || selectionInsideLivePanel(panel)) return;
    if (panel.__faryoPendingLiveRemoval) {
      panel.remove();
      return;
    }
    if (typeof panel.__faryoPendingLiveText === 'string') {
      const value = panel.__faryoPendingLiveText;
      commitLiveTerminalText(panel, value, liveTerminalState());
    }
  }

  let liveSelectionFlushTimer = null;
  document.addEventListener('selectionchange', () => {
    if (liveSelectionFlushTimer) clearTimeout(liveSelectionFlushTimer);
    liveSelectionFlushTimer = setTimeout(flushDeferredLiveTerminal, 80);
  });

  conversationScroller.addEventListener('scroll', () => { updateBottomButton(); maybeLoadOlderHistory(); }, { passive: true });
  conversationScroller.addEventListener('wheel', noteHistoryUserIntent, { passive: true });
  conversationScroller.addEventListener('touchstart', noteHistoryUserIntent, { passive: true });
  conversationScroller.addEventListener('touchmove', noteHistoryUserIntent, { passive: true });
  conversationScroller.addEventListener('pointerdown', noteHistoryUserIntent, { passive: true });
  bottomBtn.addEventListener('click', () => { if (!applyDeferredCapture(true)) scrollBottom(true); });
  output.addEventListener('toggle', (event) => {
    const panel = event.target.closest?.('.compact-live-terminal');
    if (!panel) return;
    if (restoringLivePanels.has(panel)) {
      restoringLivePanels.delete(panel);
      return;
    }
    persistLivePanelPreference(panel.dataset.session || selectedSession, panel.open);
    if (panel.open) requestAnimationFrame(() => window.FaryoLiveScroll?.restore(panel.querySelector('pre'), null));
  }, true);
  output.addEventListener('click', async (event) => {
    const liveCopy = event.target.closest('.compact-live-copy');
    if (liveCopy) {
      event.preventDefault();
      event.stopPropagation();
      const text = liveCopy.closest('.compact-live-terminal')?.querySelector('pre')?.textContent || '';
      try {
        await navigator.clipboard.writeText(text);
        liveCopy.textContent = '✓';
        setTimeout(() => { if (liveCopy.isConnected) liveCopy.textContent = '⧉'; }, 900);
      } catch (_error) {
        setError('Copy failed');
      }
      return;
    }
    const protectedLink = event.target.closest('a[data-faryo-fetch-href]');
    if (protectedLink) {
      event.preventDefault();
      await openProtectedResource(protectedLink);
      return;
    }
    const codeCopy = event.target.closest('.markdown-code-copy');
    if (codeCopy) {
      const text = codeCopy.closest('.markdown-code-block')?.querySelector('pre')?.textContent || '';
      try {
        await navigator.clipboard.writeText(text);
        codeCopy.textContent = 'Copied';
        codeCopy.setAttribute('aria-label', 'Code copied');
        setTimeout(() => {
          if (!codeCopy.isConnected) return;
          codeCopy.textContent = 'Copy';
          codeCopy.setAttribute('aria-label', 'Copy code');
        }, 1000);
      } catch (_error) {
        setError('Copy failed');
      }
      return;
    }
    const copy = event.target.closest('.copy-output-block');
    if (copy) {
      const block = copy.closest('.compact-block.output');
      const payload = copyFidelity?.payloadForBlock(block);
      const copied = payload ? await copyFidelity.write(payload) : false;
      if (copied) {
        copy.textContent = '✓';
        setTimeout(() => { if (copy.isConnected) copy.textContent = '⧉'; }, 900);
      } else {
        setError('Copy failed');
      }
      return;
    }
    const image = event.target.closest('.chat-image-thumb');
    if (image) {
      const source = image.querySelector('img');
      showImageLightbox(source?.currentSrc || source?.src || '', image.dataset.label || '');
      return;
    }
    const markdownImage = event.target.closest('.chat-markdown-image');
    if (markdownImage) {
      showImageLightbox(markdownImage.currentSrc || markdownImage.src || '', markdownImage.alt || 'Image preview');
      return;
    }
  });
  document.addEventListener('copy', (event) => {
    if (outputMode === 'compact') copyFidelity?.handleCopy(event);
  });
  window.addEventListener('faryo-markdown-highlighter-ready', () => {
    markdownRenderRevision += 1;
    clearMarkdownRenderCache();
    if (!lastCompactCapture || outputMode !== 'compact' || highlighterRenderFrame) return;
    highlighterRenderFrame = requestAnimationFrame(() => {
      highlighterRenderFrame = 0;
      const keepBottom = isNearBottom();
      renderOutput(lastCompactCapture);
      if (keepBottom) scrollBottom(true);
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    document.getElementById('imageLightbox')?.classList.add('hidden');
  });
  window.addEventListener('pagehide', () => {
    for (const url of protectedImageUrls.values()) URL.revokeObjectURL(url);
    protectedImageUrls.clear();
  });

  function setError(message, options = {}) {
    if (!message && Date.now() < preserveErrorUntil) return;
    if (errorTimer) { clearTimeout(errorTimer); errorTimer = null; }
    if (!message) { errorBox.classList.add('hidden'); errorBox.textContent = ''; return; }
    errorBox.textContent = message;
    errorBox.classList.remove('hidden');
    const timeoutMs = options.timeoutMs === undefined ? 5000 : options.timeoutMs;
    if (timeoutMs > 0) {
      errorTimer = window.setTimeout(() => {
        errorTimer = null;
        setError('');
      }, timeoutMs);
    }
  }

  function userErrorMessage(err) {
    const status = err && err.status;
    const raw = (err && err.message) || 'Request failed';
    const messageMap = {
      'single session mode': 'Single-session mode is enabled.',
    };
    const detail = messageMap[raw] || raw;
    return status ? `HTTP ${status}: ${detail}` : detail;
  }

  function setBusy(isBusy) {
    for (const id of ['sendBtn', 'refreshBtn', 'dockFullBtn', 'detailsChatBtn', 'detailsRawBtn', 'detailsRefreshBtn', 'dockPlusBtn', 'approveSmallBtn', 'attachmentBtn', 'upBtn', 'downBtn']) {
      const el = $(id);
      if (el) el.disabled = isBusy;
    }
  }

  function handleBackgroundError(err) {
    if (!err || err.name === 'AbortError') return;
    console.debug('background refresh failed', err);
  }

  async function gatewayCsrfHeaders() {
    if (!routeBase || ownerToken) return {};
    if (!gatewayCsrfToken) {
      const res = await fetch('/api/csrf', { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok || !data.csrf) {
        const err = new Error(data.error || 'CSRF token unavailable');
        err.status = res.status;
        throw err;
      }
      gatewayCsrfToken = data.csrf;
    }
    return { 'X-Faryo-Csrf': gatewayCsrfToken };
  }

  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (ownerToken) headers['X-Owner-Token'] = ownerToken;
    const method = String(options.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) Object.assign(headers, await gatewayCsrfHeaders());
    if (options.body && !headers['Content-Type'] && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    const requestPath = path.startsWith('/api/') ? `${routeBase}${path}` : path;
    const res = await fetch(requestPath, Object.assign({}, options, { headers, cache: 'no-store' }));
    const text = await res.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_) {
      const err = new Error(res.ok ? 'API response is not JSON' : `${res.status} ${res.statusText || 'API error'}`);
      err.status = res.status;
      err.nonJson = true;
      throw err;
    }
    if (!res.ok || data.ok === false) {
      const err = new Error(data.error || `${res.status} ${res.statusText}`); err.status = res.status; err.payload = data; throw err;
    }
    return data;
  }

  async function loadOwnerCapabilities() {
    const payload = await api('/api/capabilities');
    document.documentElement.dataset.faryoCapabilitySchema = String(payload.schemaVersion || 'unknown');
    $('detailsChangesBtn').hidden = payload.features?.workspaceChanges === false;
    $('detailsDiagnosticsBtn').hidden = payload.features?.diagnostics === false;
    return payload;
  }

  async function downloadDiagnostics() {
    const button = $('detailsDiagnosticsBtn');
    button.disabled = true;
    try {
      const payload = await api('/api/diagnostics');
      const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'faryo-diagnostics.json';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      button.querySelector('span').textContent = 'Diagnostics downloaded';
      setTimeout(() => { if (button.isConnected) button.querySelector('span').textContent = 'Download diagnostics'; }, 1200);
    } catch (error) {
      setError(userErrorMessage(error));
    } finally {
      button.disabled = false;
    }
  }

  function apiPath(path) {
    return selectedSession && path.startsWith('/api/') ? path + (path.includes('?') ? '&' : '?') + `session=${encodeURIComponent(selectedSession)}` : path;
  }

  function emptyConversationHistory() {
    return {
      revision: '', sessionId: '', totalTurns: 0, questions: [], turns: new Map(),
      loadedStart: null, loadedEnd: 0, olderCursor: '', initialized: false,
    };
  }

  function resetConversationHistory() {
    historyRunId += 1;
    historyRequestController?.abort();
    historyRequestController = null;
    historyLoadPromise = null;
    if (historyRefreshTimer) clearTimeout(historyRefreshTimer);
    historyRefreshTimer = null;
    historyCaptureSignature = '';
    historyLastRefreshAt = 0;
    historyOlderLoadQueued = false;
    conversationHistory = emptyConversationHistory();
  }

  function structuredCapture(capture) {
    return capture?.captureSource === 'codex-jsonl' || capture?.captureSource === 'codex-app-server';
  }

  function loadedHistoryTurns() {
    return [...conversationHistory.turns.values()].sort((left, right) => left.index - right.index);
  }

  function historyDisplayText() {
    const turns = loadedHistoryTurns();
    const blocks = [];
    let previous = null;
    for (const turn of turns) {
      if (previous !== null && turn.index > previous + 1) {
        const missing = turn.index - previous - 1;
        blocks.push(`• … ${missing} earlier turn${missing === 1 ? '' : 's'} not loaded; use the question rail to fetch them …`);
      }
      blocks.push(String(turn.text || ''));
      previous = turn.index;
    }
    return blocks.filter(Boolean).join('\n\n');
  }

  function mergedConversationCapture(capture) {
    if (outputMode !== 'compact' || !structuredCapture(capture) || !conversationHistory.initialized
      || !conversationHistory.turns.size
      || (conversationHistory.sessionId && capture.sessionId && conversationHistory.sessionId !== capture.sessionId)) {
      return capture;
    }
    return { ...capture, text: historyDisplayText(), historyTotalTurns: conversationHistory.totalTurns };
  }

  function historyAnchorSnapshot() {
    const scrollerTop = conversationScroller.getBoundingClientRect().top;
    const child = [...output.children].find((element) => element.getBoundingClientRect().bottom > scrollerTop + 1);
    return child ? {
      key: child.dataset.faryoBlockKey || '',
      top: child.getBoundingClientRect().top,
      scrollTop: conversationScroller.scrollTop,
      scrollHeight: conversationScroller.scrollHeight,
    } : { key: '', top: 0, scrollTop: conversationScroller.scrollTop, scrollHeight: conversationScroller.scrollHeight };
  }

  function restoreHistoryAnchor(snapshot) {
    if (!snapshot) return;
    const apply = () => {
      const target = snapshot.key
        ? [...output.children].find((element) => element.dataset.faryoBlockKey === snapshot.key)
        : null;
      conversationScroller.scrollTop = target
        ? conversationScroller.scrollTop + target.getBoundingClientRect().top - snapshot.top
        : snapshot.scrollTop + Math.max(0, conversationScroller.scrollHeight - snapshot.scrollHeight);
      updateBottomButton();
    };
    requestAnimationFrame(() => {
      apply();
      requestAnimationFrame(apply);
    });
  }

  function mergeConversationHistoryPage(data, expectedSessionId) {
    const revision = String(data?.revision || '');
    if (!revision) throw new Error('Conversation history revision is missing');
    if (conversationHistory.revision && conversationHistory.revision !== revision) {
      conversationHistory = emptyConversationHistory();
    }
    conversationHistory.revision = revision;
    conversationHistory.sessionId = expectedSessionId || conversationHistory.sessionId;
    conversationHistory.totalTurns = Number(data.totalTurns || 0);
    conversationHistory.questions = Array.isArray(data.questions) ? data.questions.map((item, index) => ({
      index: Number.isInteger(Number(item?.index)) ? Number(item.index) : index,
      key: String(item?.key || `question-${index}`),
      preview: String(item?.preview || 'Untitled question'),
    })) : [];
    for (const turn of data.turns || []) {
      const index = Number(turn?.index);
      if (!Number.isInteger(index) || index < 0) continue;
      conversationHistory.turns.set(index, {
        index,
        key: String(turn.key || `question-${index}`),
        preview: String(turn.preview || ''),
        text: String(turn.text || ''),
      });
    }
    const loaded = loadedHistoryTurns();
    conversationHistory.loadedStart = loaded.length ? loaded[0].index : null;
    conversationHistory.loadedEnd = loaded.length ? loaded[loaded.length - 1].index + 1 : 0;
    if (Number(data.start) === conversationHistory.loadedStart) {
      conversationHistory.olderCursor = String(data.olderCursor || '');
    }
    conversationHistory.initialized = true;
  }

  function loadedQuestionTarget(key) {
    return [...output.querySelectorAll('.compact-block.user')]
      .find((element) => element.dataset.faryoQuestionKey === key) || null;
  }

  async function loadConversationHistory(options = {}) {
    const around = options.around !== undefined && options.around !== null
      && Number.isInteger(Number(options.around)) ? Number(options.around) : null;
    if (around !== null && conversationHistory.turns.has(around)) return conversationHistory.turns.get(around);
    if (historyLoadPromise) {
      try { await historyLoadPromise; } catch (_error) {}
      if (around !== null && conversationHistory.turns.has(around)) return conversationHistory.turns.get(around);
    }
    const runId = historyRunId;
    const session = selectedSession;
    const expectedSessionId = String(lastCompactCapture?.sessionId || conversationHistory.sessionId || '');
    const query = new URLSearchParams({ limit: String(HISTORY_PAGE_TURNS) });
    if (options.cursor) query.set('cursor', String(options.cursor));
    if (around !== null) query.set('around', String(around));
    const controller = new AbortController();
    historyRequestController = controller;
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    const anchor = options.preserveAnchor ? historyAnchorSnapshot() : null;
    const keepBottom = Boolean(initialLatestScrollPending || (options.latest && isNearBottom()));
    historyLoadPromise = (async () => {
      const data = await api(apiPath(`/api/conversation-history?${query}`), { signal: controller.signal });
      if (runId !== historyRunId || session !== selectedSession) return null;
      mergeConversationHistoryPage(data, expectedSessionId);
      historyLastRefreshAt = Date.now();
      if (lastCompactCapture && outputMode === 'compact') {
        renderOutput(lastCompactCapture);
        if (anchor) restoreHistoryAnchor(anchor);
        else if (initialLatestScrollPending && options.latest) applyInitialLatestScroll(true);
        else if (keepBottom && Date.now() > historyUserIntentUntil) scrollBottom(true);
      }
      return data;
    })();
    try {
      return await historyLoadPromise;
    } catch (error) {
      if (Number(error?.status) === 409) {
        resetConversationHistory();
        if (!options.retrying) return loadConversationHistory({ latest: true, retrying: true });
      }
      if (options.latest && initialLatestScrollPending) applyInitialLatestScroll(true);
      throw error;
    } finally {
      clearTimeout(timeoutId);
      if (historyRequestController === controller) historyRequestController = null;
      historyLoadPromise = null;
      if (historyOlderLoadQueued) {
        historyOlderLoadQueued = false;
        setTimeout(maybeLoadOlderHistory, 0);
      }
    }
  }

  async function resolveQuestionTarget(question) {
    if (loadedQuestionTarget(question?.key)) return true;
    try {
      await loadConversationHistory({ around: Number(question?.index) });
    } catch (error) {
      setError(userErrorMessage(error));
      throw error;
    }
    return Boolean(loadedQuestionTarget(question?.key));
  }

  function scheduleConversationHistoryRefresh(capture, delay = 80) {
    if (outputMode !== 'compact' || capture?.captureSource !== 'codex-jsonl') return;
    if (conversationHistory.sessionId && capture.sessionId && conversationHistory.sessionId !== capture.sessionId) {
      resetConversationHistory();
      beginInitialLatestScroll();
    }
    const text = String(capture.text || '');
    const signature = `${capture.sessionId || ''}:${text.length}:${text.slice(-160)}`;
    if (historyCaptureSignature === signature
      && (conversationHistory.initialized || historyLoadPromise || historyRefreshTimer)) return;
    historyCaptureSignature = signature;
    if (historyRefreshTimer) clearTimeout(historyRefreshTimer);
    const wait = Math.max(delay, HISTORY_REFRESH_MIN_MS - (Date.now() - historyLastRefreshAt));
    historyRefreshTimer = setTimeout(() => {
      historyRefreshTimer = null;
      loadConversationHistory({ latest: true }).catch(handleBackgroundError);
    }, wait);
  }

  function noteHistoryUserIntent() {
    cancelInitialLatestScroll();
    historyUserIntentUntil = Date.now() + 600;
  }

  function maybeLoadOlderHistory() {
    if (Date.now() > historyUserIntentUntil || outputMode !== 'compact'
      || !conversationHistory.initialized || !conversationHistory.olderCursor
      || conversationScroller.scrollTop > 120) return;
    if (historyLoadPromise) {
      historyOlderLoadQueued = true;
      return;
    }
    historyUserIntentUntil = 0;
    loadConversationHistory({ cursor: conversationHistory.olderCursor, preserveAnchor: true })
      .catch(handleBackgroundError);
  }

  function localResourcePath(path) {
    return routeBase + apiPath(path);
  }

  function localFileTarget(path, line = 0, column = 0) {
    const endpoint = ownerToken ? '/api/local-file' : '/api/local-file/view';
    const resourcePath = `${endpoint}?path=${encodeURIComponent(path)}${line ? `&line=${line}` : ''}${column ? `&column=${column}` : ''}`;
    const href = localResourcePath(resourcePath);
    return ownerToken ? { href, fetchHref: href } : href;
  }

  function localImageTarget(path) {
    const href = localResourcePath(`/api/local-image?path=${encodeURIComponent(path)}`);
    return ownerToken ? { href: '', fetchHref: href } : href;
  }

  function setLiveState(state) {
    liveState = state;
    if ($('detailsConnection')) $('detailsConnection').textContent = state;
    updatePetControl();
  }

  function ensureOutputActivityTimer() {
    if (outputActivityTimer) return;
    outputActivityTimer = setInterval(() => {
      outputActivity = Math.max(0, outputActivity - 0.6);
      updatePetControl();
      if (outputActivity === 0) {
        clearInterval(outputActivityTimer);
        outputActivityTimer = null;
      }
    }, PET_RUN_DECAY_MS);
  }

  function noteOutputActivity(capture) {
    const text = `${capture?.text || ''}\n${capture?.liveText || ''}`;
    const signature = `${text.length}:${text.slice(-180)}`;
    if (signature === lastCaptureSignature) return;
    const delta = Math.max(0, text.length - Number(lastCaptureSignature.split(':', 1)[0] || 0));
    lastCaptureSignature = signature;
    if (!agentRunning) return;
    outputActivity = Math.min(5, outputActivity + (delta > 1600 ? 1.8 : delta > 360 ? 1.2 : 0.8));
    ensureOutputActivityTimer();
    updatePetControl();
  }

  function petPhase() {
    if (petStopping) return 'stopping';
    if (petSending) return 'send';
    if (pendingAttachments.some((item) => ['compressing', 'uploading'].includes(item.status))) return 'carrying';
    if (pendingAttachments.length) return 'carrying';
    if (outputMode === 'full' && fullLocked) return 'offline';
    if (promptInput.value.trim() || document.activeElement === promptInput || document.documentElement.classList.contains('keyboard-open')) return 'working';
    if (agentRunning) return 'running';
    if (liveState === 'live') return 'idle';
    if (liveState === 'reconnecting') return 'resting';
    return 'offline';
  }

  function updatePetControl() {
    const pet = $('petControl');
    if (!pet) return;
    const phase = petPhase();
    const labels = { stopping: 'stopping', send: 'sending', carrying: 'carrying files', working: 'working', running: 'running', idle: 'online', resting: 'reconnecting', offline: 'offline' };
    if (phase !== lastPetPhase) {
      lastPetPhase = phase;
      pet.className = `pet-control pet-${phase}`;
      pet.title = `Faryo ${labels[phase] || phase}`;
      pet.setAttribute('aria-label', `${pet.title}; tap to interrupt`);
    }
    if (phase === 'running') {
      const speed = outputActivity >= 3.5 ? '.48s' : outputActivity >= 1.6 ? '.72s' : outputActivity > 0 ? '1.08s' : '1.6s';
      pet.style.setProperty('--pet-run-speed', speed);
    } else if (pet.style.getPropertyValue('--pet-run-speed')) {
      pet.style.removeProperty('--pet-run-speed');
    }
  }

  function playPetSend() {
    petSending = true;
    agentRunning = true;
    outputActivity = Math.max(outputActivity, 2.2);
    ensureOutputActivityTimer();
    if (promptShell) {
      promptShell.classList.remove('pet-sending');
      void promptShell.offsetWidth;
      promptShell.classList.add('pet-sending');
    }
    if (petSendTimer) clearTimeout(petSendTimer);
    petSendTimer = setTimeout(() => {
      petSending = false;
      petSendTimer = null;
      promptShell?.classList.remove('pet-sending');
      updatePetControl();
    }, PET_SEND_MS);
    updatePetControl();
  }

  function stopPetSend() {
    if (petSendTimer) clearTimeout(petSendTimer);
    petSendTimer = null;
    petSending = false;
    promptShell?.classList.remove('pet-sending');
  }

  function playPetStop() {
    petStopping = true;
    if (petStopTimer) clearTimeout(petStopTimer);
    petStopTimer = setTimeout(() => {
      petStopping = false;
      petStopTimer = null;
      updatePetControl();
    }, PET_STOP_MS);
    updatePetControl();
  }

  function eventUrl() {
    return routeBase + apiPath(`/api/events?lines=${COMPACT_CAPTURE_LINES}`);
  }

  function closeEventStream() {
    if (eventRetryTimer) clearTimeout(eventRetryTimer);
    eventRetryTimer = null;
    eventStreamRunId += 1;
    eventStreamController?.abort();
    eventStreamController = null;
  }

  function setStatusRefresh(on) { if (statusRefreshTimer) clearInterval(statusRefreshTimer); statusRefreshTimer = null; if (on && !document.hidden) statusRefreshTimer = setInterval(() => refreshStatus({ silent: true }).catch(handleBackgroundError), STATUS_REFRESH_MS); }
  function headerStatusVisible() { return !document.querySelector('header')?.classList.contains('collapsed'); }
  function syncStatusRefresh(refreshNow = false) { const on = headerStatusVisible(); setStatusRefresh(on); if (on && refreshNow) refreshStatus({ silent: true }).catch(handleBackgroundError); }

  function setFullRefresh(on) {
    if (fullRefreshTimer) clearInterval(fullRefreshTimer);
    fullRefreshTimer = null;
    if (on && !document.hidden) fullRefreshTimer = setInterval(() => {
      refreshCapture(FULL_CAPTURE_LINES, { silent: true }).catch(handleBackgroundError);
    }, FULL_REFRESH_MS);
  }

  function setCaptureFallback(on) { if (captureFallbackTimer) clearInterval(captureFallbackTimer); captureFallbackTimer = null; if (on && !document.hidden && outputMode === 'compact') captureFallbackTimer = setInterval(() => refreshCapture(COMPACT_CAPTURE_LINES, { silent: true }).catch(handleBackgroundError), CAPTURE_FALLBACK_MS); }

  function applyCaptureEvent(event) {
    if (event.type !== 'capture') return;
    const keepBottom = isNearBottom();
    const capture = JSON.parse(event.data || '{}');
    setLiveState('live');
    if (capture.sessionTitle) renderSessionLabel(capture.sessionTitle);
    if (Object.prototype.hasOwnProperty.call(capture, 'agentRunning')) {
      const nextRunning = Boolean(capture.agentRunning);
      if (nextRunning !== agentRunning) {
        agentRunning = nextRunning;
        updatePetControl();
      }
    }
    if (outputMode === 'compact') renderCaptureWhenSafe(capture, keepBottom);
  }

  function retryEventStream(controller, runId, error) {
    if (controller.signal.aborted || eventStreamController !== controller || eventStreamRunId !== runId) return;
    eventStreamController = null;
    setLiveState('reconnecting');
    if (headerStatusVisible()) refreshStatus({ silent: true }).catch(handleBackgroundError);
    setCaptureFallback(true);
    if (error && error.name !== 'AbortError') console.debug('event stream reconnecting', error);
    const delay = eventRetryDelayMs;
    eventRetryDelayMs = Math.min(15000, Math.round(eventRetryDelayMs * 1.7));
    if (outputMode === 'compact' && !document.hidden) eventRetryTimer = setTimeout(startEventStream, delay);
  }

  async function consumeEventStream(controller, runId) {
    const headers = ownerToken ? { 'X-Owner-Token': ownerToken } : {};
    const response = await fetch(eventUrl(), {
      headers,
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal,
    });
    if (!response.ok) {
      const error = new Error(`Event stream failed ${response.status}`);
      error.status = response.status;
      throw error;
    }
    if (!response.body || typeof eventStreamParser.createParser !== 'function') throw new Error('Streaming response is unavailable');
    eventRetryDelayMs = 1800;
    setCaptureFallback(false);
    setLiveState('live');
    const parser = eventStreamParser.createParser(applyCaptureEvent);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (eventStreamController === controller && eventStreamRunId === runId) {
      const chunk = await reader.read();
      if (chunk.done) break;
      parser.push(decoder.decode(chunk.value, { stream: true }));
    }
    parser.push(decoder.decode(), true);
    if (!controller.signal.aborted) throw new Error('Event stream ended');
  }

  function startEventStream() {
    if (!window.fetch || !window.ReadableStream || outputMode !== 'compact' || document.hidden) {
      setLiveState('fallback');
      setCaptureFallback(outputMode === 'compact' && !document.hidden);
      return;
    }
    closeEventStream();
    setLiveState('reconnecting');
    const controller = new AbortController();
    const runId = eventStreamRunId;
    eventStreamController = controller;
    consumeEventStream(controller, runId).catch((error) => retryEventStream(controller, runId, error));
  }

  function compactGitLabel(git) {
    if (!git) return 'git --';
    if (git.state === 'error' && /^(?:⚠️|⚠)?\s*DETACHED\b/u.test(git.label || '')) return (git.label || '⚠️ DETACHED').replace(/^(?:⚠️|⚠)?\s*/u, '⚠️ ');
    const clean = git.state === 'clean';
    const icon = clean ? '🌿' : '✏️';
    const raw = (git.label || '').replace(/^(?:🌿|✏️|✏)\s*/u, '').trim();
    const parts = raw.split(/\s+/).filter(Boolean);
    const markRe = /^(?:[+-]\d+|±\d+|\?\d+|[↑↓]\d+|m[+-]\d+)$/;
    const marks = parts.filter((part) => markRe.test(part)).join(' ');
    const branch = parts.filter((part) => !markRe.test(part)).join(' ') || 'git';
    const shortBranch = branch.length > 14 ? `${branch.slice(0, 13)}…` : branch;
    return `${icon}${marks ? ` ${marks}` : ''} ${shortBranch}`;
  }

  function updateStatusPill(git) {
    phasePill.className = `pill git-pill ${(git && git.state) || 'muted'}`;
    phasePill.textContent = compactGitLabel(git);
    phasePill.title = git ? git.title : 'Current directory is not a Git repository';
  }

  function weeklyElapsedPercent(rateLimit) {
    if (rateLimit.resetsAt === null || rateLimit.resetsAt === ''
      || rateLimit.windowDurationMins === null || rateLimit.windowDurationMins === '') return null;
    const resetSeconds = Number(rateLimit.resetsAt);
    const windowMinutes = Number(rateLimit.windowDurationMins);
    if (!Number.isFinite(resetSeconds) || !Number.isFinite(windowMinutes) || windowMinutes <= 0) return null;
    const windowMs = windowMinutes * 60 * 1000;
    const startMs = resetSeconds * 1000 - windowMs;
    const elapsedMs = Math.min(Math.max(Date.now() - startMs, 0), windowMs);
    return Math.round((elapsedMs / windowMs) * 100);
  }

  function numericTokenCount(value) {
    if (value === null || value === '' || typeof value === 'undefined') return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? Math.round(number) : null;
  }

  function compactTokenCount(value) {
    const count = numericTokenCount(value);
    if (count === null) return null;
    if (count >= 1_000_000) {
      const millions = Math.round((count / 1_000_000) * 10) / 10;
      return `${Number.isInteger(millions) ? millions : millions.toFixed(1)}m`;
    }
    if (count >= 100_000) return `${Math.round(count / 1000)}k`;
    if (count >= 10_000) return `${(count / 1000).toFixed(1)}k`;
    if (count >= 1000) return `${Math.round(count / 1000)}k`;
    return String(count);
  }

  function exactTokenCount(value) {
    const count = numericTokenCount(value);
    if (count === null) return null;
    try { return new Intl.NumberFormat().format(count); }
    catch (_err) { return String(count); }
  }

  function renderContextStatus(contextUsage) {
    const percent = Number(contextUsage.percent);
    const percentText = Number.isFinite(percent) ? `${quotaPercent(percent)}%` : null;
    const usedTokens = numericTokenCount(contextUsage.usedTokens ?? contextUsage.inputTokens);
    const contextWindow = numericTokenCount(contextUsage.contextWindow);
    const reportedWindow = contextUsage.contextWindowSource === 'agent-reported';
    const hasReportedCounts = reportedWindow && usedTokens !== null && contextWindow > 0;
    const compactCounts = hasReportedCounts ? `${compactTokenCount(usedTokens)}/${compactTokenCount(contextWindow)}` : '';
    const compact = `Ctx ${percentText || '--'}${compactCounts ? ` · ${compactCounts}` : ''}`;
    const detail = hasReportedCounts
      ? `${exactTokenCount(usedTokens)} / ${exactTokenCount(contextWindow)} tokens${percentText ? ` · ${percentText} used` : ''}`
      : (percentText ? `${percentText} used` : 'Unavailable');
    const label = $('ctxText');
    if (label) {
      label.textContent = compact;
      label.title = hasReportedCounts ? `Agent-reported context · ${detail}` : detail;
    }
    if ($('detailsContext')) $('detailsContext').textContent = detail;
    return compact;
  }

  function quotaPercent(value) {
    if (value === null || value === '' || typeof value === 'undefined') return null;
    const number = Number(value);
    if (!Number.isFinite(number)) return null;
    const rounded = Math.round(Math.max(0, Math.min(100, number)) * 10) / 10;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  }

  function weeklyResetLabel(rateLimit) {
    if (rateLimit.resetsAt === null || rateLimit.resetsAt === '' || typeof rateLimit.resetsAt === 'undefined') return '';
    const resetSeconds = Number(rateLimit.resetsAt);
    if (!Number.isFinite(resetSeconds)) return '';
    const reset = new Date(resetSeconds * 1000);
    if (Number.isNaN(reset.getTime())) return '';
    try {
      return new Intl.DateTimeFormat(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      }).format(reset);
    } catch (_err) {
      return reset.toLocaleString();
    }
  }

  function renderQuotaStatus(rateLimit) {
    const button = $('quotaTop') || $('statusLeft');
    const label = $('quotaText');
    const details = $('detailsQuota');
    const usageFill = $('quotaFill');
    const weekFill = $('quotaWeekFill');
    const percent = rateLimit.usedPercent === null || typeof rateLimit.usedPercent === 'undefined' ? NaN : Number(rateLimit.usedPercent);
    const scopedPercent = rateLimit.scopedPercent === null || typeof rateLimit.scopedPercent === 'undefined' ? NaN : Number(rateLimit.scopedPercent);
    if (Number.isFinite(scopedPercent)) {
      const used = quotaPercent(percent);
      const scopedUsed = quotaPercent(scopedPercent);
      const remaining = used === null ? null : quotaPercent(100 - Number(used));
      const scopedRemaining = quotaPercent(100 - Number(scopedUsed));
      const scopedLabel = rateLimit.scopedLabel || 'Model';
      const compact = remaining === null ? 'Week --' : `Week ${remaining}% left`;
      const detail = [remaining === null ? 'All unavailable' : `All ${remaining}% left`, `${scopedLabel} ${scopedRemaining}% left`].join(' · ');
      button.style.setProperty('--quota-pct', used === null ? 0 : Number(used));
      button.style.setProperty('--quota-week-pct', Number(scopedUsed));
      usageFill.setAttribute('aria-hidden', 'true');
      weekFill.setAttribute('aria-hidden', 'true');
      if (label) label.textContent = compact;
      if (details) details.textContent = detail;
      button.title = `Weekly quota · ${detail}`;
      button.setAttribute('aria-label', button.title);
      return compact;
    }
    const weekPercent = weeklyElapsedPercent(rateLimit);
    if (!Number.isFinite(percent)) {
      button.style.setProperty('--quota-pct', 0);
      button.style.setProperty('--quota-week-pct', Number.isFinite(weekPercent) ? weekPercent : 0);
      if (label) label.textContent = 'Week --';
      if (details) details.textContent = 'Unavailable';
      button.title = 'Quota unknown';
      button.setAttribute('aria-label', 'Quota unknown');
      return 'Week --';
    }
    const clamped = Math.max(0, Math.min(100, percent));
    const used = quotaPercent(clamped);
    const remaining = quotaPercent(100 - clamped);
    const reset = weeklyResetLabel(rateLimit);
    const compact = `Week ${remaining}% left`;
    const detail = `${remaining}% left · ${used}% used${reset ? ` · resets ${reset}` : ''}`;
    button.style.setProperty('--quota-pct', clamped);
    button.style.setProperty('--quota-week-pct', Number.isFinite(weekPercent) ? Math.max(0, Math.min(100, weekPercent)) : 0);
    usageFill.setAttribute('aria-hidden', 'true');
    weekFill.setAttribute('aria-hidden', 'true');
    if (label) label.textContent = compact;
    if (details) details.textContent = detail;
    button.title = `Weekly quota · ${detail}`;
    button.setAttribute('aria-label', button.title);
    return compact;
  }

  function leadingText(text, maxChars) {
    const chars = Array.from(String(text || ''));
    return chars.length <= maxChars ? chars.join('') : chars.slice(0, maxChars).join('') + '...';
  }

  function compactPathLabel(path) {
    const value = String(path || '').replace(/\\/g, '/').replace(/\/$/, '');
    if (!value) return 'cwd unknown';
    if (value === '~') return '~';
    return value.split('/').filter(Boolean).pop() || value;
  }

  function compactModelLabel(model, fastStatus) {
    const label = String(model || 'model').replace(/\s+/g, ' ').trim().replace(/\bgpt(?=[-\s])/i, 'GPT');
    return fastStatus && fastStatus !== 'off' ? `${label} ⚡` : label;
  }

  function updateFolderLabel(data) {
    const cwdText = data.displayCwd || data.shortCwd || data.cwd || 'cwd unknown';
    const folderLabel = `📁 ${compactPathLabel(cwdText)}`;
    $('draftState').textContent = leadingText(folderLabel, 22);
    $('draftState').title = cwdText;
  }

  function updateCachedSessionTitle(sessionLabel) {
    try {
      const cached = JSON.parse(sessionStorage.getItem(WORKBENCH_CACHE_KEY) || 'null');
      if (!cached?.data) return;
      const route = routeBase.replace('/', '');
      let changed = false;
      for (const collection of [cached.data.sessions, cached.data.activeSessions]) {
        if (!Array.isArray(collection)) continue;
        for (const item of collection) {
          if (String(item?.tmuxSession || '') !== selectedSession) continue;
          if (route && item?.route && String(item.route) !== route) continue;
          if (item.title === sessionLabel) continue;
          item.title = sessionLabel;
          changed = true;
        }
      }
      if (!changed) return;
      sessionStorage.setItem(WORKBENCH_CACHE_KEY, JSON.stringify(cached));
      if (activeSurfacePanel === sessionMenu) renderSessionMenu(cached.data, false);
    } catch (_err) {}
  }

  function renderSessionLabel(value, { syncCache = true } = {}) {
    const sessionLabel = String(value || '').replace(/\s+/g, ' ').trim();
    if (!sessionLabel) return;
    $('topicText').textContent = leadingText(sessionLabel, 18);
    $('sessionTitle').title = `${$('ownerText').textContent || 'TMUX'} · ${sessionLabel}`;
    if ($('detailsSession')) $('detailsSession').textContent = sessionLabel;
    document.title = `${sessionLabel} · Faryo`;
    if (syncCache) updateCachedSessionTitle(sessionLabel);
  }

  function renderStatus(data) {
    const model = data.model || `tmux:${data.session || 'unknown'}`;
    const ownerLabel = data.ownerLabel || 'TMUX';
    const contextUsage = data.contextUsage || {};
    const contextText = renderContextStatus(contextUsage);
    const weeklyRateLimit = data.weeklyRateLimit || {};
    const sessionLabel = data.sessionTitle || data.sessionId || 'session unknown';
    const modelLabel = compactModelLabel(model, data.fastStatus);
    selectedSession = data.session || selectedSession;
    $('ownerText').textContent = ownerLabel;
    renderSessionLabel(sessionLabel);
    $('modelText').textContent = modelLabel;
    $('modelText').title = model;
    const quotaText = renderQuotaStatus(weeklyRateLimit);
    $('subTitle').title = `${contextText} · ${quotaText} · ${model}${data.fastStatus ? ` · fast:${data.fastStatus}` : ''}`;
    updateFolderLabel(data);
    updateStatusPill(data.gitStatus);
    if ($('detailsOwner')) $('detailsOwner').textContent = ownerLabel;
    if ($('detailsModel')) $('detailsModel').textContent = modelLabel;
    if ($('detailsGit')) $('detailsGit').textContent = phasePill.textContent || 'git --';
    agentRunning = Boolean(data.agentRunning);
    updatePetControl();
  }

  function switchSession(route, session) {
    const next = new URL(routeBase === `/${route}` ? location.href : `/${route}/`, location.origin);
    next.searchParams.set('session', session);
    if (routeBase !== `/${route}`) return location.assign(`${next.pathname}${next.search}${location.hash}`);
    persistPromptDraft();
    persistPendingSubmission();
    selectedSession = session;
    beginInitialLatestScroll();
    closeSurfacePanels({ restoreFocus: false });
    pendingSubmission = null;
    restorePromptDraft();
    autosize();
    updateSendVisibility();
    history.replaceState(null, '', `${next.pathname}${next.search}${location.hash}`);
    sessionMenu.classList.add('hidden');
    resetConversationHistory();
    resetRefreshState();
    clearMarkdownRenderCache();
    closeEventStream();
    lastCaptureSignature = '';
    lastCompactCapture = lastFullCapture = null;
    refreshStatus({ silent: true }).catch(handleBackgroundError);
    refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError);
    if (outputMode === 'compact') startEventStream();
  }

  function cachedWorkbench() {
    try {
      const cached = JSON.parse(sessionStorage.getItem(WORKBENCH_CACHE_KEY) || 'null');
      return cached?.data && Date.now() - Number(cached.storedAt || 0) <= WORKBENCH_CACHE_MS ? cached.data : null;
    } catch (_err) { return null; }
  }

  function renderSessionMenu(data, needsRefresh) {
    const list = (data?.sessions || []).filter((item) => item.active && item.tmuxSession).map((item) => { const route = String(item.route || '').trim(), session = String(item.tmuxSession), where = item.cwdLabel || compactPathLabel(item.cwd || ''), meta = escapeHtml(`${item.routeLabel || route || 'Owner'}${where ? ` · ${where}` : ''}${item.updatedAt ? ` · ${item.updatedAt}` : ''}`), active = routeBase === `/${route}` && session === selectedSession; return `<button type="button" class="${active ? 'active' : ''}" data-route="${escapeHtml(route)}" data-session="${escapeHtml(session)}"><span><strong>${escapeHtml(String(item.title || item.id || session))}</strong><small>${meta}</small></span><em>${active ? 'Now' : 'Open'}</em></button>`; }).join('');
    const current = routeBase && selectedSession ? `<button type="button" class="active" data-route="${escapeHtml(routeBase.replace('/', ''))}" data-session="${escapeHtml(selectedSession)}"><span><strong>${escapeHtml($('topicText').textContent || selectedSession)}</strong><small>${escapeHtml($('draftState').title || $('draftState').textContent || 'Current session')}</small></span><em>Now</em></button>` : '';
    const refresh = needsRefresh ? '<button type="button" data-refresh="workbench"><span><strong>Refresh</strong><small>Load latest gateway sessions</small></span><em>↻</em></button>' : '';
    sessionMenu.innerHTML = `<div class="surface-panel-heading"><div><span class="surface-panel-eyebrow">Workspace</span><strong id="sessionPanelTitle">Running sessions</strong></div><button class="panel-close" type="button" data-close-panel aria-label="Close running sessions">×</button></div>${list || current || '<div class="session-empty">No cached sessions</div>'}${refresh}`;
  }

  async function refreshSessionMenu() {
    const headers = ownerToken ? { 'X-Owner-Token': ownerToken } : {};
    const res = await fetch('/api/workbench', { headers, cache: 'no-store' }), data = await res.json(); if (!res.ok || data.ok === false) throw new Error(data.error || 'Failed to load sessions');
    try { sessionStorage.setItem(WORKBENCH_CACHE_KEY, JSON.stringify({ storedAt: Date.now(), data })); } catch (_err) {}
    renderSessionMenu(data, false);
  }

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  function decorateMetaLines(renderedHtml, text) {
    const htmlLines = renderedHtml.split('\n');
    const textLines = text.split('\n');
    if (htmlLines.length !== textLines.length) return renderedHtml;
    return htmlLines.map((line, index) => {
      const plainLine = textLines[index];
      if (!metaLineRe.test(plainLine)) return line;
      return `<span class="agent-meta-line">${line || ' '}</span>`;
    }).join('\n');
  }

  function renderPlanBlock(text) {
    const titleRe = /^(?:[-*•]\s*)?(?:Updated Plan|Plan updated)\b/i;
    const itemRe = /^(?:\[(?:x|X|✓|✔)\]|\[\s?\]|[✔✓☑□☐-]|\d+\.)\s*/;
    const items = [];
    for (const raw of text.split('\n')) {
      const line = raw.trim().replace(/^[│|└├↳]\s*/, '').trim();
      if (!line || titleRe.test(line)) continue;
      const item = line
        .replace(/^\[(?:x|X|✓|✔)\]\s*/, '✓ ')
        .replace(/^\[\s?\]\s*/, '□ ')
        .replace(/^[✔✓☑]\s*/, '✓ ')
        .replace(/^[□☐]\s*/, '□ ');
      if (itemRe.test(line) || !items.length) items.push(item);
      else items[items.length - 1] = `${items[items.length - 1]} ${item}`;
    }
    if (!items.length) return '<section class="compact-process-line">📝 Plan updated</section>';
    return `<section class="compact-block plan"><div class="compact-plan-title">Plan updated</div>${items.length ? `<div class="compact-plan-list">${items.map((item) => `<div class="compact-plan-item">${escapeHtml(item)}</div>`).join('')}</div>` : ''}</section>`;
  }

  function clearMarkdownRenderCache() {
    markdownHtmlCache.clear();
  }

  function renderMarkdownSegment(source, mode) {
    const text = String(source || '');
    const cacheable = typeof stableBlocks.fingerprint === 'function';
    const cacheKey = cacheable
      ? `${markdownRenderRevision}:${mode}:${text.length}:${stableBlocks.fingerprint(text)}`
      : '';
    const cached = cacheKey ? markdownHtmlCache.get(cacheKey) : null;
    if (cached?.source === text) {
      markdownHtmlCache.delete(cacheKey);
      markdownHtmlCache.set(cacheKey, cached);
      return cached.html;
    }
    const html = markdownRenderer.render(text, {
      localFileHref: localFileTarget,
      localImageHref: localImageTarget,
    }, { mode });
    if (cacheKey) {
      markdownHtmlCache.set(cacheKey, { source: text, html });
      while (markdownHtmlCache.size > 256) {
        markdownHtmlCache.delete(markdownHtmlCache.keys().next().value);
      }
    }
    return html;
  }

  function parsedInternalAnnotations(value) {
    if (typeof internalAnnotations.parse === 'function') return internalAnnotations.parse(value);
    return { body: String(value || ''), citations: [] };
  }

  function copyableOutputText(value) {
    if (typeof internalAnnotations.strip === 'function') return internalAnnotations.strip(value);
    return String(value || '');
  }

  function renderMemoryReferences(citations) {
    const groups = Array.isArray(citations) ? citations : [];
    if (!groups.length) return '';
    const entries = groups.flatMap((group) => Array.isArray(group?.entries) ? group.entries : []);
    const count = entries.length;
    const notes = entries.map((entry) => String(entry?.note || '').trim()).filter(Boolean);
    const items = notes.length
      ? `<ul>${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join('')}</ul>`
      : '<p>Saved context was used for this answer.</p>';
    return `<details class="memory-reference-card"><summary>Memory references${count ? ` · ${count}` : ''}</summary><div class="memory-reference-body">${items}</div></details>`;
  }

  const imagePathRe = /\.(?:jpe?g|png|webp|gif|heic|heif)$/i;
  const filePathRe = /\.(?:md|txt|json|csv|rtf|pdf|docx?|xlsx?|pptx?|odt|odp|ods|bash|c|cc|cfg|cpp|css|go|h|hpp|html|ini|java|js|jsx|lean|log|py|rs|sh|sql|tex|toml|ts|tsx|xml|ya?ml|zsh)$/i;

  function cleanTypedPath(value, suffixRe) {
    let text = String(value || '').trim();
    if ((text.startsWith('<') && text.endsWith('>')) || (/^(['"`]).*\1$/.test(text))) text = text.slice(1, -1).trim();
    text = text.replace(/[),.;]+$/g, '');
    return suffixRe.test(text) ? text : '';
  }

  function renderImageLine(line) {
    const match = String(line || '').match(/^\s*Image\s*:\s*(.+?)\s*$/i);
    const path = match && cleanTypedPath(match[1], imagePathRe);
    if (!path) return '';
    const target = localImageTarget(path);
    const src = typeof target === 'string' ? target : '';
    const fetchSrc = typeof target === 'object' ? target.fetchHref : '';
    const label = path.split(/[\\/]/).pop() || 'image';
    const sourceAttributes = src
      ? ` src="${escapeHtml(src)}"`
      : ` data-faryo-fetch-src="${escapeHtml(fetchSrc)}" aria-busy="true"`;
    return `<button class="chat-image-thumb" type="button" data-label="${escapeHtml(label)}"><img class="chat-image"${sourceAttributes} alt="${escapeHtml(label)}" loading="lazy"></button>`;
  }

  const protectedImageUrls = new Map();

  function releaseDetachedProtectedImages() {
    for (const [image, url] of protectedImageUrls) {
      if (image.isConnected) continue;
      URL.revokeObjectURL(url);
      protectedImageUrls.delete(image);
    }
  }

  async function fetchProtectedResource(href) {
    const target = new URL(String(href || ''), location.href);
    const localApiPaths = new Set([
      `${routeBase}/api/local-image`,
      `${routeBase}/api/local-file`,
      `${routeBase}/api/local-file/view`,
    ]);
    if (target.origin !== location.origin || !localApiPaths.has(target.pathname)) {
      throw new Error('Local resource URL was rejected');
    }
    target.searchParams.delete('token');
    const headers = ownerToken ? { 'X-Owner-Token': ownerToken } : {};
    const response = await fetch(target.pathname + target.search, {
      headers,
      cache: 'no-store',
      credentials: 'same-origin',
    });
    if (!response.ok) {
      const error = new Error(`Local resource failed ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response;
  }

  async function hydrateProtectedImages(root) {
    releaseDetachedProtectedImages();
    const images = [...(root?.querySelectorAll('img[data-faryo-fetch-src]') || [])];
    await Promise.all(images.map(async (image) => {
      if (image.dataset.faryoFetching === '1') return;
      image.dataset.faryoFetching = '1';
      try {
        const response = await fetchProtectedResource(image.dataset.faryoFetchSrc);
        const blob = await response.blob();
        if (!image.isConnected) return;
        const previous = protectedImageUrls.get(image);
        if (previous) URL.revokeObjectURL(previous);
        const url = URL.createObjectURL(blob);
        protectedImageUrls.set(image, url);
        image.src = url;
        image.removeAttribute('data-faryo-fetch-src');
        image.removeAttribute('aria-busy');
      } catch (_error) {
        image.removeAttribute('aria-busy');
        image.classList.add('resource-load-error');
      } finally {
        delete image.dataset.faryoFetching;
      }
    }));
  }

  async function openProtectedResource(link) {
    const popup = window.open('about:blank', '_blank');
    if (popup) {
      popup.opener = null;
      popup.document.title = 'Loading local file';
    }
    try {
      const response = await fetchProtectedResource(link.dataset.faryoFetchHref);
      const url = URL.createObjectURL(await response.blob());
      if (popup) popup.location.replace(url);
      else {
        const fallback = document.createElement('a');
        fallback.href = url;
        fallback.target = '_blank';
        fallback.rel = 'noopener noreferrer';
        fallback.click();
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
      popup?.close();
      setError(userErrorMessage(error));
    }
  }

  function showImageLightbox(src, label) {
    if (!src) return;
    let box = document.getElementById('imageLightbox');
    if (!box) {
      box = document.createElement('div');
      box.id = 'imageLightbox';
      box.className = 'image-lightbox hidden';
      box.innerHTML = '<img alt=""><div class="image-lightbox-caption"></div>';
      box.addEventListener('click', () => box.classList.add('hidden'));
      document.body.appendChild(box);
    }
    box.querySelector('img').src = src;
    box.querySelector('img').alt = label || 'Image preview';
    box.querySelector('.image-lightbox-caption').textContent = label || '';
    box.classList.remove('hidden');
  }

  function renderFileLine(line) {
    const match = String(line || '').match(/^\s*(?:(File|Attachment)\s*:\s*)?(.+?)\s*$/i);
    const path = match && cleanTypedPath(match[2], filePathRe);
    if (!path || (!match[1] && !/^(?:\/|~\/|\.{1,2}\/|[\w.-]+\/|[\w.-]+\.[A-Za-z0-9]{1,8}$)/.test(path))) return '';
    const target = localFileTarget(path);
    const href = typeof target === 'string' ? target : target.href;
    const fetchHref = typeof target === 'object' ? target.fetchHref : '';
    const label = path.split(/[\\/]/).pop() || 'file';
    const fetchAttribute = fetchHref ? ` data-faryo-fetch-href="${escapeHtml(fetchHref)}"` : '';
    return `<a class="file-link" href="${escapeHtml(href)}"${fetchAttribute}>File ${escapeHtml(label)}</a>`;
  }

  function renderTextWithFiles(text, renderOptions = {}) {
    const parsed = parsedInternalAnnotations(text);
    const originalLines = String(parsed.body || '').split('\n');
    let renderedText = '';
    if (typeof markdownRenderer.render === 'function' && markdownRenderer.ready?.()) {
      const rendered = [];
      let markdownLines = [];
      let fenceChar = '';
      const flushMarkdown = () => {
        if (!markdownLines.length) return;
        const mode = renderOptions.mode === 'streaming' ? 'streaming' : 'settled';
        rendered.push(`<div class="markdown-body">${renderMarkdownSegment(markdownLines.join('\n'), mode)}</div>`);
        markdownLines = [];
      };
      originalLines.forEach((line) => {
        const fenceMatch = line.trimStart().match(/^(`{3,}|~{3,})/);
        const insideFence = Boolean(fenceChar);
        const special = !insideFence && !fenceMatch && (renderImageLine(line) || renderFileLine(line));
        if (special) {
          flushMarkdown();
          rendered.push(special);
        } else {
          markdownLines.push(line);
        }
        if (fenceMatch) {
          const char = fenceMatch[1][0];
          if (!fenceChar) fenceChar = char;
          else if (fenceChar === char) fenceChar = '';
        }
      });
      flushMarkdown();
      renderedText = rendered.join('');
    } else {
      renderedText = originalLines.map((line) => renderImageLine(line) || renderFileLine(line) || escapeHtml(line)).join('\n');
    }
    return renderedText + renderMemoryReferences(parsed.citations);
  }

  function renderTextWithFilesSafely(text, renderOptions = {}) {
    try {
      return renderTextWithFiles(text, renderOptions);
    } catch (_error) {
      const parsed = parsedInternalAnnotations(text);
      return `<div class="rich-render-fallback" role="status"><strong>Rich text preview unavailable</strong><span>Showing safe plain text for this message.</span><pre>${escapeHtml(parsed.body || '')}</pre></div>${renderMemoryReferences(parsed.citations)}`;
    }
  }

  function compactRulesForCapture(capture) {
    const source = String(capture?.agentSource || capture?.source || '').toLowerCase();
    const rules = source === 'codex-cli' ? codexCompactRules : runtimeCompactRules;
    return {
      userPromptRe: rules.userPromptRe || runtimeCompactRules.userPromptRe,
      compactBlocks: rules.compactBlocks || runtimeCompactRules.compactBlocks,
      processSummaryCard: rules.processSummaryCard || runtimeCompactRules.processSummaryCard,
      approvalPendingRe: rules.approvalPendingRe || runtimeCompactRules.approvalPendingRe,
    };
  }

  function renderCompactOutput(text, rules, renderOptions = {}) {
    const mode = renderOptions.mode === 'streaming' ? 'streaming' : 'settled';
    const rawBlocks = rules.compactBlocks(text);
    if (!rawBlocks.length) rawBlocks.push({ kind: 'output', text: 'No output yet' });
    const models = typeof stableBlocks.plan === 'function'
      ? stableBlocks.plan(rawBlocks, { mode, revision: markdownRenderRevision, tailCount: 2 })
      : rawBlocks.map((block, index) => ({
        ...block,
        kind: String(block.kind || 'output'),
        text: String(block.text ?? ''),
        key: `fallback-${index}`,
        signature: `fallback-${index}-${String(block.text ?? '')}`,
        stable: false,
      }));
    for (const model of models) {
      model.copySource = model.kind === 'output'
        ? copyableOutputText(model.text)
        : model.kind === 'user'
          ? String(model.text || '').replace(rules.userPromptRe, '').trim()
          : '';
      model.renderSource = ['output', 'user'].includes(model.kind) ? copyableOutputText(model.text) : '';
    }
    const createNode = (model) => {
      if (model.kind === 'process') {
        const node = document.createElement('section');
        node.className = 'compact-process-line';
        node.textContent = rules.processSummaryCard(model.text);
        return node;
      }
      if (model.kind === 'status') {
        const node = document.createElement('section');
        node.className = 'compact-status-line';
        node.textContent = model.text;
        return node;
      }
      if (model.kind === 'plan') {
        const template = document.createElement('template');
        template.innerHTML = renderPlanBlock(model.text);
        return template.content.firstElementChild;
      }
      const node = document.createElement('section');
      const kindClass = /^[A-Za-z0-9_-]+$/.test(model.kind) ? model.kind : 'output';
      node.className = `compact-block ${kindClass}`;
      node.innerHTML = renderTextWithFilesSafely(model.text, renderOptions);
      return node;
    };
    let metrics;
    if (typeof stableBlocks.reconcile === 'function') {
      metrics = stableBlocks.reconcile(output, models, createNode);
    } else {
      const fragment = document.createDocumentFragment();
      for (const model of models) fragment.appendChild(createNode(model));
      output.replaceChildren(fragment);
      metrics = { created: models.length, reused: 0, removed: 0, stable: 0 };
    }
    const loadedQuestions = conversationHistory.initialized ? loadedHistoryTurns() : [];
    let loadedQuestionIndex = 0;
    copyFidelity?.beginRender();
    models.forEach((model, index) => {
      const node = output.children[index];
      if (!node) return;
      if (['output', 'user'].includes(model.kind)) {
        copyFidelity?.bindBlock(node, { source: model.copySource, renderSource: model.renderSource, kind: model.kind });
        node.dataset.faryoCopyBound = copyFidelity ? 'true' : 'false';
      }
      if (model.kind === 'user') {
        const historyTurn = loadedQuestions[loadedQuestionIndex++];
        if (historyTurn?.key) node.dataset.faryoQuestionKey = historyTurn.key;
        else delete node.dataset.faryoQuestionKey;
        node.dataset.faryoQuestionPreview = typeof questionNavigatorApi.previewText === 'function'
          ? questionNavigatorApi.previewText(model.text, 88)
          : String(model.text || '').replace(/^\s*›\s*/u, '').trim().slice(0, 88);
      } else {
        delete node.dataset.faryoQuestionKey;
        delete node.dataset.faryoQuestionPreview;
      }
    });
    const blocks = output.querySelectorAll('.compact-block.output');
    blocks.forEach((block, index) => {
      const existing = block.querySelector(':scope > .copy-output-block');
      if (index !== blocks.length - 1) {
        existing?.remove();
        return;
      }
      if (existing) return;
      const button = document.createElement('button');
      button.className = 'copy-output-block';
      button.type = 'button';
      button.setAttribute('aria-label', 'Copy this output');
      button.title = 'Copy this output';
      button.textContent = '⧉';
      block.appendChild(button);
    });
    output.dataset.compactCreated = String(metrics.created);
    output.dataset.compactReused = String(metrics.reused);
    output.dataset.compactStable = String(metrics.stable);
  }

  function renderPlainOutput(text, rules) {
    const parsed = parsedInternalAnnotations(text);
    const value = parsed.body || 'No output yet';
    let inUserInput = false;
    output.innerHTML = value.split('\n').map((line) => {
      const rendered = escapeHtml(line);
      const imageLine = renderImageLine(line);
      if (imageLine) return imageLine;
      const fileLine = renderFileLine(line);
      if (fileLine) return fileLine;
      if (rules.userPromptRe.test(line)) inUserInput = true;
      else if (!line.trim()) inUserInput = false;
      if (metaLineRe.test(line)) return `<span class="agent-meta-line">${rendered || ' '}</span>`;
      return inUserInput ? `<span class="user-input-line">${rendered || ' '}</span>` : rendered;
    }).join('\n');
    if (parsed.citations.length) output.insertAdjacentHTML('beforeend', `\n${renderMemoryReferences(parsed.citations)}`);
  }

  function renderOutput(capture) {
    const liveStateSnapshot = liveTerminalState();
    if (outputMode === 'compact') lastCompactCapture = capture;
    else lastFullCapture = capture;
    scheduleConversationHistoryRefresh(capture);
    capture = mergedConversationCapture(capture);
    const text = capture.text || 'No output yet';
    const rules = compactRulesForCapture(capture);
    output.dataset.captureSource = String(capture.captureSource || '');
    output.dataset.agentSource = String(capture.agentSource || '');
    if ($('detailsSource')) $('detailsSource').textContent = String(capture.captureSource || capture.source || 'unknown');
    needsConfirmUI = hasConfirmUI(text, rules);
    updateStatusLineAutoExpand();
    output.classList.toggle('compact-blocks', outputMode === 'compact');
    const isStructured = structuredCapture(capture);
    if (outputMode === 'compact') {
      try {
        renderCompactOutput(text, rules, {
          mode: isStructured ? 'settled' : 'streaming',
        });
        delete output.dataset.renderFallback;
      } catch (_error) {
        const parsed = parsedInternalAnnotations(text);
        output.dataset.renderFallback = 'true';
        const livePanel = output.querySelector('[data-faryo-transient="live"]');
        for (const child of Array.from(output.children)) {
          if (child !== livePanel) child.remove();
        }
        const template = document.createElement('template');
        template.innerHTML = `<section class="compact-capture-warning" role="status">Rich conversation layout failed. Safe plain text remains available and live updates will continue.</section><section class="compact-block output"><pre class="capture-render-fallback">${escapeHtml(parsed.body || '')}</pre>${renderMemoryReferences(parsed.citations)}</section>`;
        output.insertBefore(template.content, livePanel || null);
      }
    }
    else if (capture.html && !parsedInternalAnnotations(text).citations.length) output.innerHTML = decorateMetaLines(capture.html, text);
    else renderPlainOutput(text, rules);
    if (outputMode === 'compact' && capture.agentSource === 'codex-cli' && !isStructured) {
      output.insertAdjacentHTML('afterbegin', '<section class="compact-capture-warning" role="status">Structured Codex history is unavailable. Showing a terminal fallback; Markdown and formulas may be incomplete.</section>');
    }
    if (outputMode === 'compact') {
      syncLiveTerminal(capture.agentRunning && capture.liveText ? capture.liveText : '', liveStateSnapshot);
    }
    const indexedQuestions = isStructured && conversationHistory.initialized
      ? conversationHistory.questions
      : null;
    questionNavigatorController?.sync(outputMode === 'compact', indexedQuestions);
    void hydrateProtectedImages(output);
  }

  function resetRefreshState() {
    cancelActiveRefreshes();
    pendingDeferredCapture = null;
    questionNavigatorController?.reset();
  }

  function cancelActiveRefreshes() {
    captureRefreshRunId += 1;
    statusRefreshRunId += 1;
    if (activeCaptureRefreshController) activeCaptureRefreshController.abort();
    if (activeStatusRefreshController) activeStatusRefreshController.abort();
    activeCaptureRefreshController = activeStatusRefreshController = null;
    captureRefreshInFlight = statusRefreshInFlight = false;
    pendingCaptureRefreshLines = null;
  }

  function handlePageShow(event) {
    if (!seenInitialPageShow && !event.persisted) {
      seenInitialPageShow = true;
      return;
    }
    seenInitialPageShow = true;
    refreshVisibleNow();
  }

  function refreshVisibleNow() {
    if (document.hidden) return;
    if (headerStatusVisible()) refreshStatus({ silent: true }).catch(handleBackgroundError);
    refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError);
  }

  function currentCaptureLines() { return outputMode === 'compact' ? COMPACT_CAPTURE_LINES : FULL_CAPTURE_LINES; }

  function renderOutputModeButton() {
    for (const compactBtn of [$('refreshBtn'), $('detailsChatBtn')]) {
      if (!compactBtn) continue;
      compactBtn.textContent = 'Chat';
      compactBtn.classList.toggle('mode-active', outputMode === 'compact');
    }
    for (const fullBtn of [$('dockFullBtn'), $('detailsRawBtn')]) {
      if (!fullBtn) continue;
      fullBtn.textContent = outputMode === 'full' && fullLocked ? 'Locked' : 'Raw';
      fullBtn.classList.toggle('mode-active', outputMode === 'full');
    }
    if (promptShell) promptShell.style.borderColor = outputMode === 'full' && fullLocked ? 'var(--accent)' : '';
  }

  function closeDockMenu() {
    if (dockMenu) dockMenu.classList.add('hidden');
    $('dockPlusBtn')?.classList.remove('open');
    $('dockPlusBtn')?.setAttribute('aria-expanded', 'false');
  }

  function toggleDockMenu() {
    const open = dockMenu.classList.toggle('hidden');
    const nextOpen = !open;
    $('dockPlusBtn')?.classList.toggle('open', nextOpen);
    $('dockPlusBtn')?.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
  }

  function renderModeLoading(mode) {
    const compact = mode === 'compact';
    output.classList.toggle('compact-blocks', compact);
    output.dataset.captureSource = '';
    output.dataset.agentSource = '';
    output.innerHTML = compact
      ? '<section class="compact-block output"><div class="markdown-body">Loading conversation…</div></section>'
      : 'Loading raw terminal…';
    questionNavigatorController?.sync(false, null);
  }

  async function setOutputMode(mode) {
    const togglingFull = mode === 'full' && outputMode === 'full';
    const returningToChat = mode === 'compact' && outputMode !== 'compact';
    const wasNearBottom = isNearBottom();
    const targetCapture = mode === 'compact' ? lastCompactCapture : lastFullCapture;
    resetRefreshState();
    if (returningToChat) persistLivePanelPreference(selectedSession, false);
    fullLocked = togglingFull ? !fullLocked : false;
    outputMode = mode;
    renderOutputModeButton();
    if (targetCapture) renderOutput(targetCapture);
    else renderModeLoading(mode);
    if (wasNearBottom) scrollBottom(true);
    closeDockMenu();
    setFullRefresh(false);
    if (outputMode === 'compact') {
      startEventStream();
    } else {
      closeEventStream();
      setCaptureFallback(false);
      setLiveState(fullLocked ? 'fallback' : 'live');
    }
    if (togglingFull && fullLocked) return;
    await Promise.all([
      refreshStatus({ silent: true }),
      refreshCapture(currentCaptureLines(), { silent: true }),
    ]);
    setFullRefresh(outputMode === 'full' && !fullLocked);
  }

  function isImageFile(file) {
    return /^image\//i.test(file.type || '') || /\.(jpe?g|png|webp|gif|heic|heif)$/i.test(file.name || '');
  }

  function attachmentLabel(file) {
    const match = (file.name || '').match(/\.([^.]{1,5})$/);
    return match ? match[1].toUpperCase() : 'FILE';
  }

  function toggleClassState(selector, cls, key, force) {
    const enabled = force ?? localStorage.getItem(key) === '1';
    document.querySelector(selector).classList.toggle(cls, enabled);
    localStorage.setItem(key, enabled ? '1' : '0');
  }

  function renderAttachmentPreview() {
    attachmentPreview.textContent = '';
    attachmentPreview.classList.toggle('hidden', pendingAttachments.length === 0);
    for (const item of pendingAttachments) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `attachment-thumb ${item.kind === 'file' ? 'file' : ''} ${item.status || ''}`.trim();
      button.style.setProperty('--pct', item.progress || 0);
      button.title = ['compressing', 'uploading'].includes(item.status) ? 'Tap to cancel upload' : 'Tap to remove';
      if (item.url) {
        const img = document.createElement('img');
        img.alt = 'Uploaded image thumbnail';
        img.src = item.url;
        button.appendChild(img);
      } else {
        const label = document.createElement('span');
        label.className = 'file-label';
        label.textContent = item.label || 'FILE';
        button.appendChild(label);
      }
      if (['compressing', 'uploading'].includes(item.status)) {
        const pct = document.createElement('span');
        pct.className = 'upload-pct';
        pct.textContent = item.status === 'compressing' ? 'Prep' : (Number.isFinite(item.progress) ? `${item.progress}%` : '...');
        button.appendChild(pct);
      }
      const x = document.createElement('span');
      x.className = 'upload-x';
      x.textContent = '×';
      button.appendChild(x);
      button.addEventListener('click', () => removePendingAttachment(item));
      attachmentPreview.appendChild(button);
    }
    updateStatusLineAutoExpand();
    updateSendVisibility();
  }

  function hasConfirmUI(text, rules = runtimeCompactRules) {
    const tail = (text || '').split('\n').slice(-8).join('\n');
    return rules.approvalPendingRe.test(tail) || /(?:Select Model(?: and Effort)?|Update Model Permissions|Press enter to confirm or esc to go back)/i.test(tail);
  }

  function updateStatusLineAutoExpand() {
    const on = pendingAttachments.length > 0 || needsConfirmUI;
    const statusLine = document.querySelector('.status-line');
    statusLine?.classList.toggle('auto-expanded', on);
    statusLine?.classList.toggle('tui-controls-visible', needsConfirmUI);
    document.querySelector('.key-nav')?.setAttribute('aria-hidden', needsConfirmUI ? 'false' : 'true');
    document.querySelector('footer')?.classList.toggle('auto-expanded', on);
  }

  function removePendingAttachment(item) {
    if (item.xhr && item.status === 'uploading') item.xhr.abort();
    if (item.url) URL.revokeObjectURL(item.url);
    pendingAttachments = pendingAttachments.filter((entry) => entry !== item);
    renderAttachmentPreview();
  }

  function clearSubmittedAttachments(paths) {
    const submitted = new Set((paths || []).filter(Boolean));
    if (!submitted.size) return;
    for (const item of pendingAttachments) {
      if (submitted.has(item.path) && item.url) URL.revokeObjectURL(item.url);
    }
    pendingAttachments = pendingAttachments.filter((item) => !submitted.has(item.path));
    renderAttachmentPreview();
  }

  function jpegName(name) {
    return `${(name || 'image').replace(/\.[^.]*$/, '') || 'image'}.jpg`;
  }

  function loadImage(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Image could not be read')); };
      img.src = url;
    });
  }

  async function compressImage(file) {
    if (!/^image\/(jpeg|png|webp)$/i.test(file.type || '')) return { blob: file, name: file.name || 'image' };
    try {
      const img = await loadImage(file);
      const scale = Math.min(1, IMAGE_MAX_EDGE / Math.max(img.naturalWidth || img.width, img.naturalHeight || img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round((img.naturalWidth || img.width) * scale));
      canvas.height = Math.max(1, Math.round((img.naturalHeight || img.height) * scale));
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', IMAGE_JPEG_QUALITY));
      return blob && blob.size < file.size ? { blob, name: jpegName(file.name) } : { blob: file, name: file.name || 'image' };
    } catch (_) {
      return { blob: file, name: file.name || 'image' };
    }
  }

  async function uploadAttachmentItem(item) {
    item.status = item.kind === 'image' ? 'compressing' : 'uploading';
    item.progress = item.kind === 'image' ? 0 : 1;
    renderAttachmentPreview();
    const upload = item.kind === 'image' ? await compressImage(item.file) : { blob: item.file, name: item.file.name || 'attachment' };
    if (!pendingAttachments.includes(item)) { const err = new Error('Upload canceled'); err.canceled = true; throw err; }
    item.status = 'uploading';
    item.progress = Math.max(1, item.progress || 1);
    renderAttachmentPreview();
    const csrfHeaders = await gatewayCsrfHeaders();
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append('file', upload.blob, upload.name);
      const xhr = new XMLHttpRequest();
      item.xhr = xhr;
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        item.progress = Math.max(1, Math.min(99, Math.round((event.loaded / event.total) * 100)));
        renderAttachmentPreview();
      };
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
        if (xhr.status >= 200 && xhr.status < 300 && data && data.ok !== false) resolve(data);
        else reject(new Error((data && data.error) || `Upload failed ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error('Upload failed'));
      xhr.onabort = () => { const err = new Error('Upload canceled'); err.canceled = true; reject(err); };
      xhr.open('POST', `${routeBase}/api/attachment`);
      if (ownerToken) xhr.setRequestHeader('X-Owner-Token', ownerToken);
      for (const [name, value] of Object.entries(csrfHeaders)) xhr.setRequestHeader(name, value);
      xhr.send(form);
    });
  }

  async function refreshStatus(options = {}) {
    if (statusRefreshInFlight) return;
    statusRefreshInFlight = true;
    const runId = ++statusRefreshRunId;
    const controller = new AbortController();
    activeStatusRefreshController = controller;
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    if (!options.silent) setError('');
    try {
      const status = await api(apiPath('/api/status'), { signal: controller.signal });
      if (runId !== statusRefreshRunId) return;
      renderStatus(status);
    } catch (err) {
      if (err.name === 'AbortError') return;
      throw err;
    } finally {
      clearTimeout(timeoutId);
      if (activeStatusRefreshController === controller) activeStatusRefreshController = null;
      if (runId === statusRefreshRunId) statusRefreshInFlight = false;
    }
  }

  async function refreshCapture(lines = currentCaptureLines(), options = {}) {
    if (captureRefreshInFlight) {
      pendingCaptureRefreshLines = Math.max(pendingCaptureRefreshLines || 0, lines);
      return;
    }
    captureRefreshInFlight = true;
    const runId = ++captureRefreshRunId;
    const controller = new AbortController();
    activeCaptureRefreshController = controller;
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    if (!options.silent) setError('');
    try {
      const keepBottom = isNearBottom();
      const format = outputMode === 'compact' ? '' : '&format=html';
      const capture = await api(apiPath(`/api/capture?lines=${lines}${format}`), { signal: controller.signal });
      if (runId !== captureRefreshRunId) return;
      if (capture.sessionTitle) renderSessionLabel(capture.sessionTitle);
      if (Object.prototype.hasOwnProperty.call(capture, 'agentRunning')) {
        agentRunning = Boolean(capture.agentRunning);
        updatePetControl();
      }
      renderCaptureWhenSafe(capture, keepBottom);
    } catch (err) {
      if (err.name === 'AbortError') return;
      throw err;
    } finally {
      clearTimeout(timeoutId);
      if (activeCaptureRefreshController === controller) activeCaptureRefreshController = null;
      if (runId === captureRefreshRunId) {
        captureRefreshInFlight = false;
        const pendingLines = pendingCaptureRefreshLines;
        pendingCaptureRefreshLines = null;
        if (pendingLines) refreshCapture(pendingLines, { silent: true }).catch(handleBackgroundError);
      }
    }
  }

  async function postAction(path, body, options = {}) {
    setBusy(true);
    setError('');
    try {
      const payload = Object.assign({ session: selectedSession }, body || {});
      const data = await api(path, { ...options, method: 'POST', body: JSON.stringify(payload) });
      return data;
    } finally {
      setBusy(false);
    }
  }

  function isAmbiguousDeliveryError(error) {
    return error instanceof TypeError || error?.name === 'AbortError' || [502, 504].includes(Number(error?.status || 0));
  }

  async function sendDeliveryAttempt(payload) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      return await postAction('/api/send', payload, { signal: controller.signal });
    } catch (error) {
      if (error?.name !== 'AbortError') throw error;
      const timeoutError = new Error('Send confirmation timed out');
      timeoutError.name = 'AbortError';
      timeoutError.status = 504;
      throw timeoutError;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async function sendWithDeliveryRecovery(payload) {
    try {
      return await sendDeliveryAttempt(payload);
    } catch (error) {
      if (!isAmbiguousDeliveryError(error)) throw error;
      setError('Checking whether the message was delivered…', { timeoutMs: 0 });
      await new Promise((resolve) => setTimeout(resolve, 180));
      return sendDeliveryAttempt(payload);
    }
  }

  async function uploadAttachments(files) {
    const selected = Array.from(files || []).slice(0, MAX_ATTACHMENTS - pendingAttachments.length);
    if (!selected.length) { attachmentInput.value = ''; if (pendingAttachments.length >= MAX_ATTACHMENTS) setError(`Attach up to ${MAX_ATTACHMENTS} files`); return; }
    const items = selected.map((file) => {
      const kind = isImageFile(file) ? 'image' : 'file';
      return { file, kind, label: attachmentLabel(file), url: kind === 'image' ? URL.createObjectURL(file) : '', status: kind === 'image' ? 'compressing' : 'uploading', progress: 0 };
    });
    pendingAttachments.push(...items);
    renderAttachmentPreview();
    setBusy(true);
    setError('');
    try {
      await Promise.allSettled(items.map(async (item) => {
        try {
          const data = await uploadAttachmentItem(item);
          if (!pendingAttachments.includes(item)) return;
          item.path = data.path;
          item.kind = data.kind || item.kind;
          item.progress = 100;
          item.status = 'ready';
        } catch (err) {
          if (err.canceled || !pendingAttachments.includes(item)) return;
          item.status = 'error';
          setError(userErrorMessage(err));
        } finally {
          item.xhr = null;
          renderAttachmentPreview();
        }
      }));
      if ((files || []).length > selected.length) setError(`Attach up to ${MAX_ATTACHMENTS} files`);
    } finally {
      attachmentInput.value = '';
      setBusy(false);
    }
  }
  promptInput.addEventListener('paste', (event) => {
    const images = typeof clipboardImageApi.filesFromClipboard === 'function'
      ? clipboardImageApi.filesFromClipboard(event.clipboardData)
      : [];
    if (!images.length) return;
    event.preventDefault();
    const pastedText = typeof clipboardImageApi.plainTextFromClipboard === 'function'
      ? clipboardImageApi.plainTextFromClipboard(event.clipboardData)
      : '';
    if (pastedText && typeof clipboardImageApi.insertText === 'function') {
      const inserted = clipboardImageApi.insertText(
        promptInput.value,
        promptInput.selectionStart,
        promptInput.selectionEnd,
        pastedText,
      );
      promptInput.value = inserted.value;
      promptInput.setSelectionRange(inserted.selectionStart, inserted.selectionStart);
      promptInput.dispatchEvent(new Event('input', { bubbles: true }));
    }
    closeDockMenu();
    uploadAttachments(images).catch((err) => setError(userErrorMessage(err)));
  });
  function hasDraggedFiles(event) {
    return event.dataTransfer && Array.from(event.dataTransfer.types || []).includes('Files');
  }
  document.addEventListener('dragover', (event) => {
    if (!hasDraggedFiles(event)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = 'copy';
  }, true);
  document.addEventListener('drop', async (event) => {
    if (!hasDraggedFiles(event)) return;
    event.preventDefault();
    event.stopPropagation();
    try { await uploadAttachments(event.dataTransfer && event.dataTransfer.files); } catch (err) { setError(userErrorMessage(err)); }
  }, true);

  renderOutputModeButton();
  toggleClassState('header', 'collapsed', 'rdHeaderCollapsed'); toggleClassState('.app', 'header-collapsed', 'rdHeaderCollapsed'); syncStatusRefresh(false);
  $('sessionTitle').addEventListener('click', (event) => { if (event.target.closest('#homeBtn')) return; const on = !document.querySelector('header').classList.contains('collapsed'); toggleClassState('header', 'collapsed', 'rdHeaderCollapsed', on); toggleClassState('.app', 'header-collapsed', 'rdHeaderCollapsed', on); syncStatusRefresh(!on); });
  sessionMenu.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button?.hasAttribute('data-close-panel')) { closeSurfacePanels(); return; }
    const item = button?.dataset;
    if (item?.refresh) { refreshSessionMenu().catch((err) => setError(userErrorMessage(err))); return; }
    if (item?.route && item?.session) switchSession(item.route, item.session);
  });
  $('draftState').addEventListener('click', async (event) => {
    event.stopPropagation();
    if (!sessionMenu.classList.contains('hidden')) { closeSurfacePanels(); return; }
    const cache = cachedWorkbench();
    renderSessionMenu(cache, !cache);
    openSurfacePanel(sessionMenu, $('draftState'));
  });
  $('detailsBtn').addEventListener('click', (event) => { event.stopPropagation(); openSurfacePanel(detailsPanel, $('detailsBtn')); });
  detailsPanel.addEventListener('click', (event) => { if (event.target.closest('[data-close-panel]')) closeSurfacePanels(); });
  const changesButton = $('detailsChangesBtn');
  changesButton.disabled = true;
  changesPanelModulePromise.then(({ createChangesPanelController }) => {
    const changesPanelController = createChangesPanelController({
      view: window,
      routeBase,
      getSelectedSession: () => selectedSession,
      api,
      userErrorMessage,
      setError,
      openSurfacePanel,
      closeSurfacePanels,
    });
    changesPanelController.connect();
    changesButton.disabled = false;
  }).catch((error) => {
    changesButton.disabled = true;
    changesButton.title = 'Workspace changes are temporarily unavailable';
    console.debug('workspace changes module unavailable', error);
  });
  $('detailsDiagnosticsBtn').addEventListener('click', downloadDiagnostics);
  panelBackdrop.addEventListener('click', () => closeSurfacePanels());
  $('dockPlusBtn').addEventListener('click', (event) => {
    event.stopPropagation();
    toggleDockMenu();
  });
  document.addEventListener('click', (event) => {
    if (dockMenu.classList.contains('hidden')) return;
    if (event.target.closest('.composer')) return;
    closeDockMenu();
  });
  document.addEventListener('keydown', (event) => {
    trapSurfacePanelFocus(event);
    if (event.key === 'Escape') { closeDockMenu(); closeSurfacePanels(); }
  });
  $('refreshBtn').addEventListener('click', async () => {
    try {
      await setOutputMode('compact');
    } catch (err) {
      setError(userErrorMessage(err));
    }
  });
  $('dockFullBtn').addEventListener('click', async () => {
    try { await setOutputMode('full'); } catch (err) { setError(userErrorMessage(err)); }
  });
  $('detailsChatBtn').addEventListener('click', async () => {
    try { await setOutputMode('compact'); closeSurfacePanels(); } catch (err) { setError(userErrorMessage(err)); }
  });
  $('detailsRawBtn').addEventListener('click', async () => {
    try { await setOutputMode('full'); closeSurfacePanels(); } catch (err) { setError(userErrorMessage(err)); }
  });
  $('detailsRefreshBtn').addEventListener('click', async () => {
    try { await Promise.all([refreshStatus({ silent: true }), refreshCapture(currentCaptureLines(), { silent: true })]); }
    catch (err) { setError(userErrorMessage(err)); }
  });

  async function submitPrompt() {
    if (submitInFlight) return;
    const text = promptInput.value.trim();
    if (!text && !pendingAttachments.length) return;
    if (pendingAttachments.some((item) => ['compressing', 'uploading'].includes(item.status))) { setError('Attachments are still uploading'); return; }
    if (pendingAttachments.some((item) => item.status === 'error')) { setError('Remove failed attachments and try again'); return; }
    const readyAttachments = pendingAttachments.filter((item) => item.path);
    const attachmentText = readyAttachments.map((item) => `${item.kind === 'image' ? 'Image' : 'Attachment'}: ${item.path}`).join('\n');
    const browserText = promptInput.value;
    const outboundText = [text, attachmentText].filter(Boolean).join('\n');
    const submissionSession = selectedSession;
    if (!pendingSubmission || pendingSubmission.session !== submissionSession || pendingSubmission.browserText !== browserText || pendingSubmission.outboundText !== outboundText) {
      pendingSubmission = {
        id: newClientMessageId(),
        session: submissionSession,
        browserText,
        outboundText,
        attachmentPaths: readyAttachments.map((item) => item.path),
      };
      persistPendingSubmission(pendingSubmission, submissionSession);
    }
    const submission = { ...pendingSubmission, attachmentPaths: [...(pendingSubmission.attachmentPaths || [])] };
    submitInFlight = true;
    try {
      closeDockMenu();
      playPetSend();
      await sendWithDeliveryRecovery({ session: submission.session, text: submission.outboundText, clientMessageId: submission.id });
      clearDeliveredPromptDraft(submission);
      clearPendingSubmission(submission);
      clearSubmittedAttachments(submission.attachmentPaths);
      if (pendingSubmission?.id === submission.id) pendingSubmission = null;
      if (selectedSession === submission.session) {
        if (promptInput.value === submission.browserText) promptInput.value = '';
        persistPromptDraft();
        autosize();
        updateSendVisibility();
      }
      refreshStatus({ silent: true }).catch(handleBackgroundError);
      refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError);
      setTimeout(() => refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError), 500);
    } catch (err) {
      stopPetSend();
      updatePetControl();
      if (selectedSession === submission.session) persistPromptDraft();
      preserveFailedPromptDraft(submission);
      setError(userErrorMessage(err));
    } finally {
      submitInFlight = false;
    }
  }

  $('sendBtn').addEventListener('click', submitPrompt);
  promptInput.addEventListener('keydown', (event) => {
    if (handleCommandSuggestionKey(event)) return;
    if (event.key !== 'Enter' || !(event.ctrlKey || event.metaKey)) return;
    event.preventDefault();
    submitPrompt();
  });

  $('petControl').addEventListener('click', async () => {
    const wasRunning = agentRunning;
    try {
      stopPetSend();
      playPetStop();
      const data = await api('/api/interrupt', { method: 'POST', body: JSON.stringify({ session: selectedSession }) });
      agentRunning = data.interrupted ? false : wasRunning;
      if (!data.interrupted) {
        petStopping = false;
        updatePetControl();
      }
      refreshStatus({ silent: true }).catch(handleBackgroundError);
      refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError);
      setTimeout(() => refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError), 500);
    } catch (err) {
      petStopping = false;
      agentRunning = wasRunning;
      updatePetControl();
      setError(userErrorMessage(err));
    }
  });


  async function chooseTuiOption() {
    needsConfirmUI = false;
    updateStatusLineAutoExpand();
    try { await postAction('/api/approve'); refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError); setTimeout(() => refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError), 500); } catch (err) { setError(userErrorMessage(err)); }
  }
  $('approveSmallBtn').addEventListener('click', chooseTuiOption);
  const statusCollapseKey = 'rdStatusCollapsedV2';
  const storedStatusCollapse = localStorage.getItem(statusCollapseKey);
  const initialStatusCollapsed = storedStatusCollapse === null ? true : storedStatusCollapse === '1';
  toggleClassState('.status-line', 'collapsed', statusCollapseKey, initialStatusCollapsed);
  toggleClassState('footer', 'status-collapsed', statusCollapseKey, initialStatusCollapsed);
  $('versionToggle').addEventListener('click', () => {
    const on = !document.querySelector('.status-line').classList.contains('collapsed');
    toggleClassState('.status-line', 'collapsed', statusCollapseKey, on);
    toggleClassState('footer', 'status-collapsed', statusCollapseKey, on);
  });

  $('attachmentBtn').addEventListener('click', () => {
    if (pendingAttachments.length >= MAX_ATTACHMENTS) { setError(`Attach up to ${MAX_ATTACHMENTS} files`); return; }
    closeDockMenu();
    attachmentInput.click();
  });
  attachmentInput.addEventListener('change', async () => {
    try {
      await uploadAttachments(attachmentInput.files);
    } catch (err) {
      setError(userErrorMessage(err));
    }
  });

  async function navKey(path) {
    try { await postAction(path); refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError); setTimeout(() => refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError), 350); } catch (err) { setError(userErrorMessage(err)); }
  }
  $('upBtn').addEventListener('click', () => navKey('/api/up'));
  $('downBtn').addEventListener('click', () => navKey('/api/down'));

  // Fetch one complete metadata snapshot even when the persisted header state
  // is collapsed. Periodic status polling remains gated by header visibility;
  // lightweight capture/SSE metadata keeps `/rename` live after this point.
  refreshStatus().catch((err) => setError(userErrorMessage(err)));
  loadOwnerCapabilities().catch(handleBackgroundError);
  refreshCapture(currentCaptureLines()).catch((err) => setError(userErrorMessage(err)));
  startEventStream();
  document.documentElement.dataset.faryoAppReady = '1';
  window.addEventListener('pageshow', handlePageShow);
  window.addEventListener('pagehide', () => { cancelInitialLatestScroll(); cancelActiveRefreshes(); closeEventStream(); setCaptureFallback(false); setStatusRefresh(false); setFullRefresh(false); });
  document.addEventListener('visibilitychange', () => {
    setStatusRefresh(!document.hidden && headerStatusVisible());
    if (document.hidden) { cancelActiveRefreshes(); closeEventStream(); setCaptureFallback(false); setFullRefresh(false); }
    else {
      refreshVisibleNow();
      if (outputMode === 'compact') startEventStream();
      else setFullRefresh(!fullLocked);
    }
  });
})();
