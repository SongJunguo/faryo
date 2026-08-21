export function createCaptureController(options = {}) {
  const view = options.view || globalThis;
  const compactLines = Number(options.compactLines || 320);
  const fullLines = Number(options.fullLines || 800);
  const fetchTimeoutMs = Number(options.fetchTimeoutMs || 12000);
  const fullRefreshMs = Number(options.fullRefreshMs || 10000);
  const fallbackRefreshMs = Number(options.fallbackRefreshMs || 2500);
  const safetyRefreshMs = Number(options.safetyRefreshMs || 12000);
  const eventIdleTimeoutMs = Number(options.eventIdleTimeoutMs || 28000);
  const eventRetryInitialMs = Number(options.eventRetryInitialMs || 1800);
  let refreshInFlight = false;
  let pendingRefreshLines = null;
  let activeRefreshController = null;
  let refreshRunId = 0;
  let eventController = null;
  let eventRunId = 0;
  let eventRetryTimer = null;
  let fallbackTimer = null;
  let safetyTimer = null;
  let fullTimer = null;
  let retryDelayMs = eventRetryInitialMs;
  let deliveredCapture = null;
  let deliveryRevision = 0;

  function currentScope() {
    return typeof options.getScope === "function" ? options.getScope() : null;
  }

  function scopeAccepted(scope) {
    return typeof options.acceptScope !== "function" || options.acceptScope(scope) !== false;
  }

  function sameCapture(left, right) {
    if (!left || !right) return false;
    return left.text === right.text
      && left.liveText === right.liveText
      && left.captureSource === right.captureSource
      && left.sessionId === right.sessionId
      && left.sessionTitle === right.sessionTitle
      && left.agentRunning === right.agentRunning
      && left.queuedSendNowAvailable === right.queuedSendNowAvailable
      && left.interactionRevision === right.interactionRevision;
  }

  function deliverCapture(capture, meta) {
    if (!scopeAccepted(meta.scope)) return false;
    if (meta.safety && sameCapture(deliveredCapture, capture)) return;
    deliveredCapture = capture;
    deliveryRevision += 1;
    options.onCapture(capture, meta);
    return true;
  }

  async function refresh(lines = options.currentLines(), requestOptions = {}) {
    if (refreshInFlight) {
      pendingRefreshLines = Math.max(pendingRefreshLines || 0, lines);
      return;
    }
    refreshInFlight = true;
    const runId = ++refreshRunId;
    const scope = currentScope();
    const deliveryRevisionAtStart = deliveryRevision;
    const controller = new view.AbortController();
    activeRefreshController = controller;
    const timeoutId = view.setTimeout(() => controller.abort(), fetchTimeoutMs);
    if (!requestOptions.silent) options.setError("");
    try {
      const capture = await options.loadCapture(lines, controller.signal);
      if (runId !== refreshRunId) return;
      if (requestOptions.safety && deliveryRevisionAtStart !== deliveryRevision) return;
      deliverCapture(capture, {
        source: "refresh",
        safety: Boolean(requestOptions.safety),
        scope,
      });
    } catch (error) {
      if (error.name === "AbortError") return;
      throw error;
    } finally {
      view.clearTimeout(timeoutId);
      if (activeRefreshController === controller) activeRefreshController = null;
      if (runId === refreshRunId) {
        refreshInFlight = false;
        const pendingLines = pendingRefreshLines;
        pendingRefreshLines = null;
        if (pendingLines) refresh(pendingLines, { silent: true }).catch(options.handleBackgroundError);
      }
    }
  }

  function setFullRefresh(on) {
    if (fullTimer) view.clearInterval(fullTimer);
    fullTimer = null;
    if (on && !options.isHidden()) {
      fullTimer = view.setInterval(() => {
        refresh(fullLines, { silent: true }).catch(options.handleBackgroundError);
      }, fullRefreshMs);
    }
  }

  function setFallback(on) {
    if (fallbackTimer) view.clearInterval(fallbackTimer);
    fallbackTimer = null;
    if (on && !options.isHidden() && options.getOutputMode() === "compact") {
      fallbackTimer = view.setInterval(() => {
        refresh(compactLines, { silent: true }).catch(options.handleBackgroundError);
      }, fallbackRefreshMs);
    }
  }

  function setSafetyRefresh(on) {
    if (safetyTimer) view.clearInterval(safetyTimer);
    safetyTimer = null;
    if (on && !options.isHidden() && options.getOutputMode() === "compact") {
      safetyTimer = view.setInterval(() => {
        refresh(compactLines, { silent: true, safety: true }).catch(options.handleBackgroundError);
      }, safetyRefreshMs);
    }
  }

  function applyEvent(event, scope) {
    if (event.type !== "capture") return;
    const capture = JSON.parse(event.data || "{}");
    if (!scopeAccepted(scope)) return;
    options.setLiveState("live");
    deliverCapture(capture, { source: "event", safety: false, scope });
  }

  function closeEventStream() {
    if (eventRetryTimer) view.clearTimeout(eventRetryTimer);
    eventRetryTimer = null;
    eventRunId += 1;
    eventController?.abort();
    eventController = null;
    setSafetyRefresh(false);
  }

  function retryEventStream(controller, runId, scope, error) {
    if (controller.signal.aborted || eventController !== controller || eventRunId !== runId) return;
    if (!scopeAccepted(scope)) {
      eventController = null;
      return;
    }
    eventController = null;
    options.setLiveState("reconnecting");
    options.refreshStatusIfVisible();
    setSafetyRefresh(false);
    setFallback(true);
    if (error && error.name !== "AbortError") options.debug?.("event stream reconnecting", error);
    const delay = retryDelayMs;
    retryDelayMs = Math.min(15000, Math.round(retryDelayMs * 1.7));
    if (options.getOutputMode() === "compact" && !options.isHidden()) {
      eventRetryTimer = view.setTimeout(startEventStream, delay);
    }
  }

  async function consumeEventStream(controller, runId, scope) {
    const response = await options.fetch(options.eventUrl(), {
      headers: options.ownerHeaders(),
      cache: "no-store",
      credentials: "same-origin",
      signal: controller.signal,
    });
    if (!response.ok) {
      const error = new Error(`Event stream failed ${response.status}`);
      error.status = response.status;
      throw error;
    }
    if (!response.body || typeof options.eventStreamParser?.createParser !== "function") {
      throw new Error("Streaming response is unavailable");
    }
    retryDelayMs = eventRetryInitialMs;
    setFallback(false);
    setSafetyRefresh(true);
    options.setLiveState("live");
    const parser = options.eventStreamParser.createParser((event) => applyEvent(event, scope));
    const reader = response.body.getReader();
    try {
      const decoder = new view.TextDecoder();
      while (eventController === controller && eventRunId === runId) {
        let timeoutId = null;
        const stalled = new Promise((_, reject) => {
          timeoutId = view.setTimeout(() => {
            const error = new Error("Event stream heartbeat timed out");
            error.name = "TimeoutError";
            reject(error);
          }, eventIdleTimeoutMs);
        });
        let chunk;
        try {
          chunk = await Promise.race([reader.read(), stalled]);
        } finally {
          if (timeoutId) view.clearTimeout(timeoutId);
        }
        if (chunk.done) break;
        parser.push(decoder.decode(chunk.value, { stream: true }));
      }
      parser.push(decoder.decode(), true);
      if (!controller.signal.aborted) throw new Error("Event stream ended");
    } finally {
      if (eventController === controller && eventRunId === runId) setSafetyRefresh(false);
      try {
        await reader.cancel();
      } catch (_error) {
        // The transport may already be gone. Reconnect handling below owns
        // the user-facing state, so cancellation failure is not actionable.
      }
    }
  }

  function startEventStream() {
    if (
      typeof options.fetch !== "function"
      || !view.ReadableStream
      || options.getOutputMode() !== "compact"
      || options.isHidden()
    ) {
      options.setLiveState("fallback");
      setSafetyRefresh(false);
      setFallback(options.getOutputMode() === "compact" && !options.isHidden());
      return;
    }
    closeEventStream();
    options.setLiveState("reconnecting");
    const controller = new view.AbortController();
    const runId = eventRunId;
    const scope = currentScope();
    eventController = controller;
    consumeEventStream(controller, runId, scope)
      .catch((error) => retryEventStream(controller, runId, scope, error));
  }

  function cancelRefresh() {
    refreshRunId += 1;
    activeRefreshController?.abort();
    activeRefreshController = null;
    refreshInFlight = false;
    pendingRefreshLines = null;
  }

  return {
    refresh,
    setFullRefresh,
    setFallback,
    setSafetyRefresh,
    startEventStream,
    closeEventStream,
    cancelRefresh,
    get refreshInFlight() { return refreshInFlight; },
  };
}
