(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const outputWrap = $('outputWrap');
  const output = $('output');
  const promptInput = $('promptInput');
  const attachmentInput = $('attachmentInput');
  const attachmentPreview = $('attachmentPreview');
  const errorBox = $('errorBox');
  const phasePill = $('phasePill');
  const bottomBtn = $('bottomBtn');
  const dockMenu = $('dockMenu');
  const sessionMenu = $('sessionMenu');
  const commandSuggest = $('commandSuggest');
  const promptShell = document.querySelector('.prompt-shell');
  const metaLineRe = /^\s*(gpt|o\d|claude)[\w.\- ]*·\s+/;
  const codexCompactRules = window.FaryoCodexCompactRules || {};
  const claudeCompactRules = window.FaryoClaudeCompactRules || {};
  const mathRenderer = window.FaryoMath || {};
  const markdownRenderer = window.FaryoMarkdown || {};
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
    'Tap Confirm to approve',
    'Raw shows terminal',
    'Tap Raw again to lock',
    'Tap ↓ for latest',
    '⧉ copies last output',
    'Tap title to fold header',
    'Tap version to fold footer',
    'Tap folder to switch sessions',
    'Set font on home',
  ];
  const COMMAND_SUGGESTIONS = ['/permissions', '/model', '/rename', '/new', 'codex', 'codex resume', 'codex --yolo', 'claude', 'claude --dangerously-skip-permissions', 'claude --resume'];
  let captureRefreshInFlight = false, pendingCaptureRefreshLines = null, pendingDeferredCapture = null, activeCaptureRefreshController = null, captureRefreshRunId = 0;
  let statusRefreshInFlight = false, activeStatusRefreshController = null, statusRefreshRunId = 0, statusRefreshTimer = null;
  let eventSource = null, eventRetryTimer = null, captureFallbackTimer = null, eventRetryDelayMs = 1800, liveState = 'fallback';
  let petSending = false, petSendTimer = null, petStopping = false, petStopTimer = null, agentRunning = false, lastPetPhase = '';
  let outputActivity = 0, outputActivityTimer = null, lastCaptureSignature = '', lastCapture = null;
  let outputMode = 'compact', fullLocked = false, fullRefreshTimer = null, preserveErrorUntil = 0, seenInitialPageShow = false, needsConfirmUI = false, errorTimer = null, currentPromptTip = '';
  let compactOutputSources = [];
  let pendingAttachments = [];
  const routeMatch = location.pathname.match(/^\/(hp|pc|txy)(?:\/|$)/);
  const routeBase = routeMatch ? `/${routeMatch[1]}` : '';
  const params = new URLSearchParams(location.search);
  const ownerToken = params.get('token') || '';
  let selectedSession = params.get('session') || '';
  let submitInFlight = false, pendingSubmission = null;

  function promptDraftKey(session = selectedSession) { return `faryoPromptDraft:${routeBase || 'owner'}:${session || 'default'}`; }
  function pendingSubmissionKey(session = selectedSession) { return `${promptDraftKey(session)}:pending`; }
  function persistPromptDraft() {
    try {
      if (promptInput.value) sessionStorage.setItem(promptDraftKey(), promptInput.value);
      else sessionStorage.removeItem(promptDraftKey());
    } catch (_err) {}
  }
  function persistPendingSubmission() {
    try {
      if (pendingSubmission) sessionStorage.setItem(pendingSubmissionKey(), JSON.stringify(pendingSubmission));
      else sessionStorage.removeItem(pendingSubmissionKey());
    } catch (_err) {}
  }
  function restorePromptDraft() {
    try {
      promptInput.value = sessionStorage.getItem(promptDraftKey()) || '';
      const restored = JSON.parse(sessionStorage.getItem(pendingSubmissionKey()) || 'null');
      pendingSubmission = restored?.browserText === promptInput.value ? restored : null;
      if (!pendingSubmission) sessionStorage.removeItem(pendingSubmissionKey());
    } catch (_err) {
      pendingSubmission = null;
    }
  }
  function newClientMessageId() {
    if (window.crypto?.randomUUID) return `web-${window.crypto.randomUUID()}`;
    return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
  }

  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone;
  document.documentElement.classList.toggle('standalone', Boolean(isStandalone));
  restorePromptDraft();
  promptInput.addEventListener('input', () => {
    if (pendingSubmission?.browserText !== promptInput.value) {
      pendingSubmission = null;
      persistPendingSubmission();
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
  window.addEventListener('faryo-math-ready', () => {
    if (lastCapture && outputMode === 'compact') renderOutput(lastCapture);
  });

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
  function commandMatches() { const q = promptInput.value.trimStart().toLowerCase(); if (/^cd(\s.*)?$/.test(q)) return recentDirCommands().filter((v) => v.toLowerCase().startsWith(q) && v.toLowerCase() !== q).slice(0, 5); return (/^\/[a-z]*$/.test(q) || (q.length >= 2 && ('codex'.startsWith(q) || 'claude'.startsWith(q))) || /^(?:codex|claude)(?:\s+[-\w]+){0,3}\s*$/.test(q)) ? COMMAND_SUGGESTIONS.filter((v) => v.startsWith(q) && v !== q).slice(0, 5) : []; }
  function applyCommandSuggestion(value) { promptInput.value = value; promptInput.focus(); promptInput.setSelectionRange(value.length, value.length); autosize(); updateSendVisibility(); renderCommandSuggestions(); return true; }
  function renderCommandSuggestions() { const items = commandMatches(); if (!commandSuggest) return; commandSuggest.classList.toggle('hidden', !items.length); commandSuggest.innerHTML = items.map((v) => `<button type="button" data-value="${escapeHtml(v)}">${escapeHtml(v)}</button>`).join(''); }
  function handleCommandSuggestionKey(event) { const [value] = commandMatches(); if ((event.key === 'Tab' || event.key === 'Enter') && value) { event.preventDefault(); return applyCommandSuggestion(value); } if (event.key === 'Escape') commandSuggest?.classList.add('hidden'); return false; }
  commandSuggest?.addEventListener('mousedown', (event) => event.preventDefault());
  commandSuggest?.addEventListener('click', (event) => { const value = event.target.closest('button')?.dataset.value; if (value) applyCommandSuggestion(value); });
  for (const id of ['petControl', 'dockPlusBtn']) $(id)?.addEventListener('pointerdown', (event) => event.preventDefault());

  function updateSendVisibility() {
    const ready = promptInput.value.trim() || pendingAttachments.length > 0;
    const docked = !document.documentElement.classList.contains('keyboard-open');
    $('sendBtn')?.classList.toggle('hidden', !ready);
    $('dockPlusBtn')?.classList.toggle('hidden', Boolean(ready && docked));
    updatePetControl();
  }
  updateSendVisibility();

  function isNearBottom() { return outputWrap.scrollHeight - outputWrap.scrollTop - outputWrap.clientHeight < 80; }
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
    const previousScrollTop = outputWrap.scrollTop;
    pendingDeferredCapture = null;
    renderOutput(capture);
    if (keepBottom) scrollBottom(true);
    else requestAnimationFrame(() => {
      outputWrap.scrollTop = previousScrollTop;
      updateBottomButton();
    });
  }

  function scrollBottom(force = false) {
    if (force || isNearBottom()) {
      requestAnimationFrame(() => {
        outputWrap.scrollTop = outputWrap.scrollHeight;
        updateBottomButton();
      });
    }
  }

  outputWrap.addEventListener('scroll', updateBottomButton, { passive: true });
  bottomBtn.addEventListener('click', () => { if (!applyDeferredCapture(true)) scrollBottom(true); });
  output.addEventListener('click', async (event) => {
    const copy = event.target.closest('.copy-output-block');
    if (copy) {
      const block = copy.closest('.compact-block.output');
      const sourceIndex = Number(block?.dataset.sourceIndex);
      const source = Number.isInteger(sourceIndex) && sourceIndex >= 0 ? compactOutputSources[sourceIndex] : '';
      const clone = !source && block ? block.cloneNode(true) : null;
      clone && clone.querySelector('.copy-output-block')?.remove();
      const text = source || clone?.innerText || '';
      try { await navigator.clipboard.writeText(text.trim()); copy.textContent = '✓'; setTimeout(() => { if (copy.isConnected) copy.textContent = '⧉'; }, 900); }
      catch (err) { setError('Copy failed'); }
      return;
    }
    const image = event.target.closest('.chat-image-thumb');
    if (image) {
      showImageLightbox(image.dataset.src || '', image.dataset.label || '');
      return;
    }
    const markdownImage = event.target.closest('.chat-markdown-image');
    if (markdownImage) {
      showImageLightbox(markdownImage.currentSrc || markdownImage.src || '', markdownImage.alt || 'Image preview');
      return;
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    document.getElementById('imageLightbox')?.classList.add('hidden');
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
    for (const id of ['sendBtn', 'refreshBtn', 'dockFullBtn', 'dockPlusBtn', 'approveSmallBtn', 'attachmentBtn', 'upBtn', 'downBtn']) {
      const el = $(id);
      if (el) el.disabled = isBusy;
    }
  }

  function handleBackgroundError(err) {
    if (!err || err.name === 'AbortError') return;
    console.debug('background refresh failed', err);
  }

  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (ownerToken) headers['X-Owner-Token'] = ownerToken;
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

  function apiPath(path) {
    return selectedSession && path.startsWith('/api/') ? path + (path.includes('?') ? '&' : '?') + `session=${encodeURIComponent(selectedSession)}` : path;
  }

  function setLiveState(state) {
    liveState = state;
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
    const path = apiPath(`/api/events?lines=${COMPACT_CAPTURE_LINES}`);
    return routeBase + (ownerToken ? path + (path.includes('?') ? '&' : '?') + `token=${encodeURIComponent(ownerToken)}` : path);
  }

  function closeEventStream() {
    if (eventRetryTimer) clearTimeout(eventRetryTimer);
    eventRetryTimer = null;
    if (eventSource) eventSource.close();
    eventSource = null;
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

  function startEventStream() {
    if (!window.EventSource || outputMode !== 'compact' || document.hidden) { setLiveState('fallback'); setCaptureFallback(outputMode === 'compact' && !document.hidden); return; }
    closeEventStream();
    setLiveState('reconnecting');
    const source = new EventSource(eventUrl());
    eventSource = source;
    source.onopen = () => { eventRetryDelayMs = 1800; setCaptureFallback(false); setLiveState('live'); };
    source.addEventListener('capture', (event) => {
      const keepBottom = isNearBottom();
      setLiveState('live');
      const capture = JSON.parse(event.data || '{}');
      if (Object.prototype.hasOwnProperty.call(capture, 'agentRunning')) {
        const nextRunning = Boolean(capture.agentRunning);
        if (nextRunning !== agentRunning) {
          agentRunning = nextRunning;
          updatePetControl();
        }
      }
      if (outputMode !== 'compact') return;
      renderCaptureWhenSafe(capture, keepBottom);
    });
    source.onerror = () => {
      if (eventSource !== source) return;
      setLiveState('reconnecting');
      source.close();
      eventSource = null;
      if (headerStatusVisible()) refreshStatus({ silent: true }).catch(handleBackgroundError);
      setCaptureFallback(true);
      const delay = eventRetryDelayMs;
      eventRetryDelayMs = Math.min(15000, Math.round(eventRetryDelayMs * 1.7));
      if (outputMode === 'compact' && !document.hidden) eventRetryTimer = setTimeout(startEventStream, delay);
    };
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

  function formatWeeklyElapsedDays(rateLimit) {
    const resetSeconds = Number(rateLimit.resetsAt);
    const windowMinutes = Number(rateLimit.windowDurationMins);
    if (!Number.isFinite(resetSeconds) || !Number.isFinite(windowMinutes)) return null;
    const windowMs = windowMinutes * 60 * 1000;
    const startMs = resetSeconds * 1000 - windowMs;
    const elapsedMs = Math.min(Math.max(Date.now() - startMs, 0), windowMs);
    return (elapsedMs / 86400000).toFixed(1);
  }

  function weeklyElapsedPercent(rateLimit) {
    const resetSeconds = Number(rateLimit.resetsAt);
    const windowMinutes = Number(rateLimit.windowDurationMins);
    if (!Number.isFinite(resetSeconds) || !Number.isFinite(windowMinutes) || windowMinutes <= 0) return null;
    const windowMs = windowMinutes * 60 * 1000;
    const startMs = resetSeconds * 1000 - windowMs;
    const elapsedMs = Math.min(Math.max(Date.now() - startMs, 0), windowMs);
    return Math.round((elapsedMs / windowMs) * 100);
  }

  function renderQuotaStatus(rateLimit) {
    const button = $('quotaTop') || $('statusLeft');
    const usageFill = $('quotaFill');
    const weekFill = $('quotaWeekFill');
    const percent = Number(rateLimit.usedPercent);
    const scopedPercent = Number(rateLimit.scopedPercent);
    if (Number.isFinite(scopedPercent)) {
      button.style.setProperty('--quota-pct', Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : 0);
      button.style.setProperty('--quota-week-pct', Math.max(0, Math.min(100, scopedPercent)));
      usageFill.setAttribute('aria-hidden', 'true');
      weekFill.setAttribute('aria-hidden', 'true');
      button.title = `Week ${percent}% · ${rateLimit.scopedLabel || 'Model'} ${scopedPercent}%`;
      button.setAttribute('aria-label', button.title);
      return;
    }
    const days = formatWeeklyElapsedDays(rateLimit);
    const weekPercent = weeklyElapsedPercent(rateLimit);
    if (!Number.isFinite(percent)) {
      button.style.setProperty('--quota-pct', 0);
      button.style.setProperty('--quota-week-pct', Number.isFinite(weekPercent) ? weekPercent : 0);
      button.title = 'Quota unknown';
      button.setAttribute('aria-label', 'Quota unknown');
      return;
    }
    const clamped = Math.max(0, Math.min(100, percent));
    button.style.setProperty('--quota-pct', clamped);
    button.style.setProperty('--quota-week-pct', Number.isFinite(weekPercent) ? Math.max(0, Math.min(100, weekPercent)) : 0);
    usageFill.setAttribute('aria-hidden', 'true');
    weekFill.setAttribute('aria-hidden', 'true');
    button.title = `Weekly quota ${percent}%${days ? ` · day ${days}` : ''}`;
    button.setAttribute('aria-label', button.title);
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

  function renderStatus(data) {
    const model = data.model || `tmux:${data.session || 'unknown'}`;
    const ownerLabel = data.ownerLabel || 'TMUX';
    const contextUsage = data.contextUsage || {};
    const contextText = Number.isFinite(contextUsage.percent) ? `Ctx ${contextUsage.percent}%` : 'Ctx --';
    const weeklyRateLimit = data.weeklyRateLimit || {};
    const sessionLabel = data.sessionTitle || data.sessionId || 'session unknown';
    const modelLabel = compactModelLabel(model, data.fastStatus);
    $('ownerText').textContent = ownerLabel;
    $('topicText').textContent = leadingText(sessionLabel, 18);
    $('sessionTitle').title = `${ownerLabel} · ${sessionLabel}`;
    $('ctxText').textContent = contextText;
    $('modelText').textContent = modelLabel;
    $('modelText').title = model;
    $('subTitle').title = `${contextText} · ${model}${data.fastStatus ? ` · fast:${data.fastStatus}` : ''}`;
    renderQuotaStatus(weeklyRateLimit);
    selectedSession = data.session || selectedSession;
    updateFolderLabel(data);
    updateStatusPill(data.gitStatus);
    agentRunning = Boolean(data.agentRunning);
    updatePetControl();
  }

  function switchSession(route, session) {
    const next = new URL(routeBase === `/${route}` ? location.href : `/${route}/`, location.origin);
    next.searchParams.set('session', session);
    if (ownerToken) next.searchParams.set('token', ownerToken);
    if (routeBase !== `/${route}`) return location.assign(`${next.pathname}${next.search}${location.hash}`);
    persistPromptDraft();
    persistPendingSubmission();
    selectedSession = session;
    pendingSubmission = null;
    restorePromptDraft();
    autosize();
    updateSendVisibility();
    history.replaceState(null, '', `${next.pathname}${next.search}${location.hash}`); sessionMenu.classList.add('hidden'); resetRefreshState(); closeEventStream(); lastCaptureSignature = ''; refreshStatus({ silent: true }).catch(handleBackgroundError); refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError); if (outputMode === 'compact') startEventStream();
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
    sessionMenu.innerHTML = `<div class="session-menu-title">Running sessions</div>${list || current || '<div class="session-empty">No cached sessions</div>'}${refresh}`;
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

  function authenticatedApiPath(path) {
    const scoped = apiPath(path);
    return ownerToken ? scoped + (scoped.includes('?') ? '&' : '?') + `token=${encodeURIComponent(ownerToken)}` : scoped;
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
    const src = routeBase + authenticatedApiPath(`/api/local-image?path=${encodeURIComponent(path)}`);
    const label = path.split(/[\\/]/).pop() || 'image';
    return `<button class="chat-image-thumb" type="button" data-src="${escapeHtml(src)}" data-label="${escapeHtml(label)}"><img class="chat-image" src="${escapeHtml(src)}" alt="${escapeHtml(label)}" loading="lazy"></button>`;
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
    const href = routeBase + authenticatedApiPath(`/api/local-file/view?path=${encodeURIComponent(path)}`);
    const label = path.split(/[\\/]/).pop() || 'file';
    return `<a class="file-link" href="${escapeHtml(href)}">File ${escapeHtml(label)}</a>`;
  }

  function renderTextWithFiles(text, mathOptions = {}) {
    const originalLines = String(text || '').split('\n');
    const prepared = typeof mathRenderer.prepareText === 'function' ? mathRenderer.prepareText(text, mathOptions) : String(text || '');
    const preparedLines = prepared.split('\n');
    if (typeof markdownRenderer.render === 'function' && markdownRenderer.ready?.()) {
      const rendered = [];
      let markdownLines = [];
      let fenceChar = '';
      const flushMarkdown = () => {
        if (!markdownLines.length) return;
        rendered.push(`<div class="markdown-body">${markdownRenderer.render(markdownLines.join('\n'), {
          localFileHref: (path, line = 0, column = 0) => {
            const location = `/api/local-file/view?path=${encodeURIComponent(path)}${line ? `&line=${line}` : ''}${column ? `&column=${column}` : ''}`;
            return routeBase + authenticatedApiPath(location);
          },
          localImageHref: (path) => routeBase + authenticatedApiPath(`/api/local-image?path=${encodeURIComponent(path)}`),
        })}</div>`);
        markdownLines = [];
      };
      originalLines.forEach((line, index) => {
        const fenceMatch = line.trimStart().match(/^(`{3,}|~{3,})/);
        const insideFence = Boolean(fenceChar);
        const special = !insideFence && !fenceMatch && (renderImageLine(line) || renderFileLine(line));
        if (special) {
          flushMarkdown();
          rendered.push(special);
        } else {
          markdownLines.push(preparedLines[index] ?? line);
        }
        if (fenceMatch) {
          const char = fenceMatch[1][0];
          if (!fenceChar) fenceChar = char;
          else if (fenceChar === char) fenceChar = '';
        }
      });
      flushMarkdown();
      return rendered.join('');
    }
    return originalLines.map((line, index) => renderImageLine(line) || renderFileLine(line) || escapeHtml(preparedLines[index] ?? line)).join('\n');
  }

  function compactRulesForCapture(capture) {
    const source = String(capture?.agentSource || capture?.source || '').toLowerCase();
    const rules = source === 'claude-code' ? claudeCompactRules : (source === 'codex-cli' ? codexCompactRules : runtimeCompactRules);
    return {
      userPromptRe: rules.userPromptRe || runtimeCompactRules.userPromptRe,
      compactBlocks: rules.compactBlocks || runtimeCompactRules.compactBlocks,
      processSummaryCard: rules.processSummaryCard || runtimeCompactRules.processSummaryCard,
      approvalPendingRe: rules.approvalPendingRe || runtimeCompactRules.approvalPendingRe,
    };
  }

  function renderCompactOutput(text, rules, mathOptions = {}) {
    compactOutputSources = [];
    output.innerHTML = rules.compactBlocks(text).map((block) => {
      if (block.kind === 'process') return `<section class="compact-process-line">${escapeHtml(rules.processSummaryCard(block.text))}</section>`;
      if (block.kind === 'status') return `<section class="compact-status-line">${escapeHtml(block.text)}</section>`;
      if (block.kind === 'plan') return renderPlanBlock(block.text);
      const sourceIndex = block.kind === 'output' ? compactOutputSources.push(block.text) - 1 : -1;
      const sourceAttr = sourceIndex >= 0 ? ` data-source-index="${sourceIndex}"` : '';
      return `<section class="compact-block ${block.kind}"${sourceAttr}>${renderTextWithFiles(block.text, mathOptions)}</section>`;
    }).join('') || '<section class="compact-block output">No output yet</section>';
    const blocks = output.querySelectorAll('.compact-block.output');
    blocks[blocks.length - 1]?.insertAdjacentHTML('beforeend', '<button class="copy-output-block" type="button" aria-label="Copy this output" title="Copy this output">⧉</button>');
    mathRenderer.renderOutput?.(output);
  }

  function renderPlainOutput(text, rules) {
    const value = text || 'No output yet';
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
  }

  function renderOutput(capture) {
    lastCapture = capture;
    const text = capture.text || 'No output yet';
    const rules = compactRulesForCapture(capture);
    output.dataset.captureSource = String(capture.captureSource || '');
    output.dataset.agentSource = String(capture.agentSource || '');
    needsConfirmUI = hasConfirmUI(text, rules);
    updateStatusLineAutoExpand();
    output.classList.toggle('compact-blocks', outputMode === 'compact');
    if (outputMode === 'compact') renderCompactOutput(text, rules, { terminal: capture.captureSource !== 'codex-app-server' });
    else if (capture.html) output.innerHTML = decorateMetaLines(capture.html, text);
    else renderPlainOutput(text, rules);
    if (outputMode === 'compact' && capture.agentSource === 'codex-cli' && capture.captureSource !== 'codex-app-server') {
      output.insertAdjacentHTML('afterbegin', '<section class="compact-capture-warning" role="status">Structured Codex history is unavailable. Showing a terminal fallback; Markdown and formulas may be incomplete.</section>');
    }
    if (outputMode === 'compact' && capture.agentRunning && capture.liveText) {
      output.insertAdjacentHTML('beforeend', `<section class="compact-live-terminal"><div class="compact-live-title"><span class="live-dot"></span>Live from tmux</div><pre>${escapeHtml(String(capture.liveText))}</pre></section>`);
    }
  }

  function resetRefreshState() {
    cancelActiveRefreshes();
    pendingDeferredCapture = null;
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
    const compactBtn = $('refreshBtn');
    const fullBtn = $('dockFullBtn');
    if (compactBtn) {
      compactBtn.textContent = 'Chat';
      compactBtn.classList.toggle('mode-active', outputMode === 'compact');
    }
    if (fullBtn) { fullBtn.textContent = outputMode === 'full' && fullLocked ? 'Locked' : 'Raw'; fullBtn.classList.toggle('mode-active', outputMode === 'full'); }
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

  async function setOutputMode(mode) {
    const togglingFull = mode === 'full' && outputMode === 'full';
    const wasNearBottom = isNearBottom();
    resetRefreshState();
    fullLocked = togglingFull ? !fullLocked : false;
    outputMode = mode;
    renderOutputModeButton();
    if (lastCapture) { renderOutput(lastCapture); if (wasNearBottom) scrollBottom(true); }
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
    document.querySelector('.status-line')?.classList.toggle('auto-expanded', on);
    document.querySelector('footer')?.classList.toggle('auto-expanded', on);
  }

  function removePendingAttachment(item) {
    if (item.xhr && item.status === 'uploading') item.xhr.abort();
    if (item.url) URL.revokeObjectURL(item.url);
    pendingAttachments = pendingAttachments.filter((entry) => entry !== item);
    renderAttachmentPreview();
  }

  function clearPendingAttachments() {
    for (const item of pendingAttachments) if (item.url) URL.revokeObjectURL(item.url);
    pendingAttachments = [];
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

  async function postAction(path, body) {
    setBusy(true);
    setError('');
    try {
      const payload = Object.assign({ session: selectedSession }, body || {});
      const data = await api(path, { method: 'POST', body: JSON.stringify(payload) });
      return data;
    } finally {
      setBusy(false);
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
  $('sessionTitle').addEventListener('click', () => { const on = !document.querySelector('header').classList.contains('collapsed'); toggleClassState('header', 'collapsed', 'rdHeaderCollapsed', on); toggleClassState('.app', 'header-collapsed', 'rdHeaderCollapsed', on); syncStatusRefresh(!on); });
  sessionMenu.addEventListener('click', (event) => { const item = event.target.closest('button')?.dataset; if (item?.refresh) { refreshSessionMenu().catch((err) => setError(userErrorMessage(err))); return; } if (item?.route && item?.session) switchSession(item.route, item.session); });
  $('draftState').addEventListener('click', async (event) => {
    event.stopPropagation();
    if (!sessionMenu.classList.contains('hidden')) { sessionMenu.classList.add('hidden'); return; }
    const cache = cachedWorkbench();
    renderSessionMenu(cache, !cache);
    sessionMenu.classList.remove('hidden');
  });
  $('dockPlusBtn').addEventListener('click', (event) => {
    event.stopPropagation();
    toggleDockMenu();
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('#sessionMenu,#draftState')) sessionMenu.classList.add('hidden');
    if (dockMenu.classList.contains('hidden')) return;
    if (event.target.closest('.composer')) return;
    closeDockMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { closeDockMenu(); sessionMenu.classList.add('hidden'); }
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

  async function submitPrompt() {
    if (submitInFlight) return;
    const text = promptInput.value.trim();
    if (!text && !pendingAttachments.length) return;
    if (pendingAttachments.some((item) => ['compressing', 'uploading'].includes(item.status))) { setError('Attachments are still uploading'); return; }
    if (pendingAttachments.some((item) => item.status === 'error')) { setError('Remove failed attachments and try again'); return; }
    const attachmentText = pendingAttachments.filter((item) => item.path).map((item) => `${item.kind === 'image' ? 'Image' : 'Attachment'}: ${item.path}`).join('\n');
    const browserText = promptInput.value;
    const outboundText = [text, attachmentText].filter(Boolean).join('\n');
    if (!pendingSubmission || pendingSubmission.browserText !== browserText || pendingSubmission.outboundText !== outboundText) {
      pendingSubmission = { id: newClientMessageId(), browserText, outboundText };
      persistPendingSubmission();
    }
    submitInFlight = true;
    try {
      closeDockMenu();
      playPetSend();
      await postAction('/api/send', { text: outboundText, clientMessageId: pendingSubmission.id });
      if (promptInput.value === browserText) promptInput.value = '';
      clearPendingAttachments();
      pendingSubmission = null;
      persistPendingSubmission();
      persistPromptDraft();
      autosize();
      updateSendVisibility();
      refreshStatus({ silent: true }).catch(handleBackgroundError);
      refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError);
      setTimeout(() => refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError), 500);
    } catch (err) {
      stopPetSend();
      updatePetControl();
      persistPromptDraft();
      persistPendingSubmission();
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


  async function approve() {
    try { await postAction('/api/approve'); refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError); setTimeout(() => refreshCapture(currentCaptureLines(), { silent: true }).catch(handleBackgroundError), 500); } catch (err) { setError(userErrorMessage(err)); }
  }
  $('approveSmallBtn').addEventListener('click', approve);
  toggleClassState('.status-line', 'collapsed', 'rdStatusCollapsed'); toggleClassState('footer', 'status-collapsed', 'rdStatusCollapsed');
  $('versionToggle').addEventListener('click', () => { const on = !document.querySelector('.status-line').classList.contains('collapsed'); toggleClassState('.status-line', 'collapsed', 'rdStatusCollapsed', on); toggleClassState('footer', 'status-collapsed', 'rdStatusCollapsed', on); });

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

  if (headerStatusVisible()) refreshStatus().catch((err) => setError(userErrorMessage(err)));
  refreshCapture(currentCaptureLines()).catch((err) => setError(userErrorMessage(err)));
  startEventStream();
  window.addEventListener('pageshow', handlePageShow);
  window.addEventListener('pagehide', () => { cancelActiveRefreshes(); closeEventStream(); setCaptureFallback(false); setStatusRefresh(false); setFullRefresh(false); });
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
