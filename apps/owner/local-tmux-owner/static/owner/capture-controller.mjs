export function createCaptureController(options = {}) {
  const view = options.view || globalThis;
  const compactLines = Number(options.compactLines || 320);
  const fullLines = Number(options.fullLines || 800);
  const fetchTimeoutMs = Number(options.fetchTimeoutMs || 12000);
  const fullRefreshMs = Number(options.fullRefreshMs || 10000);
  const fallbackRefreshMs = Number(options.fallbackRefreshMs || 2500);
  let refreshInFlight = false;
  let pendingRefreshLines = null;
  let activeRefreshController = null;
  let refreshRunId = 0;
  let eventController = null;
  let eventRunId = 0;
  let eventRetryTimer = null;
  let fallbackTimer = null;
  let fullTimer = null;
  let retryDelayMs = 1800;

  async function refresh(lines = options.currentLines(), requestOptions = {}) {
    if (refreshInFlight) {
      pendingRefreshLines = Math.max(pendingRefreshLines || 0, lines);
      return;
    }
    refreshInFlight = true;
    const runId = ++refreshRunId;
    const controller = new view.AbortController();
    activeRefreshController = controller;
    const timeoutId = view.setTimeout(() => controller.abort(), fetchTimeoutMs);
    if (!requestOptions.silent) options.setError("");
    try {
      const capture = await options.loadCapture(lines, controller.signal);
      if (runId !== refreshRunId) return;
      options.onCapture(capture, { source: "refresh" });
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

  function applyEvent(event) {
    if (event.type !== "capture") return;
    const capture = JSON.parse(event.data || "{}");
    options.setLiveState("live");
    options.onCapture(capture, { source: "event" });
  }

  function closeEventStream() {
    if (eventRetryTimer) view.clearTimeout(eventRetryTimer);
    eventRetryTimer = null;
    eventRunId += 1;
    eventController?.abort();
    eventController = null;
  }

  function retryEventStream(controller, runId, error) {
    if (controller.signal.aborted || eventController !== controller || eventRunId !== runId) return;
    eventController = null;
    options.setLiveState("reconnecting");
    options.refreshStatusIfVisible();
    setFallback(true);
    if (error && error.name !== "AbortError") options.debug?.("event stream reconnecting", error);
    const delay = retryDelayMs;
    retryDelayMs = Math.min(15000, Math.round(retryDelayMs * 1.7));
    if (options.getOutputMode() === "compact" && !options.isHidden()) {
      eventRetryTimer = view.setTimeout(startEventStream, delay);
    }
  }

  async function consumeEventStream(controller, runId) {
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
    retryDelayMs = 1800;
    setFallback(false);
    options.setLiveState("live");
    const parser = options.eventStreamParser.createParser(applyEvent);
    const reader = response.body.getReader();
    const decoder = new view.TextDecoder();
    while (eventController === controller && eventRunId === runId) {
      const chunk = await reader.read();
      if (chunk.done) break;
      parser.push(decoder.decode(chunk.value, { stream: true }));
    }
    parser.push(decoder.decode(), true);
    if (!controller.signal.aborted) throw new Error("Event stream ended");
  }

  function startEventStream() {
    if (
      typeof options.fetch !== "function"
      || !view.ReadableStream
      || options.getOutputMode() !== "compact"
      || options.isHidden()
    ) {
      options.setLiveState("fallback");
      setFallback(options.getOutputMode() === "compact" && !options.isHidden());
      return;
    }
    closeEventStream();
    options.setLiveState("reconnecting");
    const controller = new view.AbortController();
    const runId = eventRunId;
    eventController = controller;
    consumeEventStream(controller, runId)
      .catch((error) => retryEventStream(controller, runId, error));
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
    startEventStream,
    closeEventStream,
    cancelRefresh,
    get refreshInFlight() { return refreshInFlight; },
  };
}
