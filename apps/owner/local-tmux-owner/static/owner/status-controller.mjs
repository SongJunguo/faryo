export function createStatusController(options = {}) {
  const view = options.view || globalThis;
  const timeoutMs = Number(options.timeoutMs || 12000);
  let refreshInFlight = false;
  let activeRefreshController = null;
  let refreshRunId = 0;

  function currentScope() {
    return typeof options.getScope === "function" ? options.getScope() : null;
  }

  function scopeAccepted(scope) {
    return (
      typeof options.acceptScope !== "function" ||
      options.acceptScope(scope) !== false
    );
  }

  async function refresh(requestOptions = {}) {
    if (refreshInFlight) return null;
    refreshInFlight = true;
    const runId = ++refreshRunId;
    const scope = currentScope();
    const controller = new view.AbortController();
    activeRefreshController = controller;
    const timeoutId = view.setTimeout(() => controller.abort(), timeoutMs);
    if (!requestOptions.silent) options.setError?.("");
    try {
      const status = await options.loadStatus(controller.signal);
      if (runId !== refreshRunId || !scopeAccepted(scope)) return null;
      options.onStatus(status, { scope });
      return status;
    } catch (error) {
      if (error.name === "AbortError") return null;
      throw error;
    } finally {
      view.clearTimeout(timeoutId);
      if (activeRefreshController === controller)
        activeRefreshController = null;
      if (runId === refreshRunId) refreshInFlight = false;
    }
  }

  function cancel() {
    refreshRunId += 1;
    activeRefreshController?.abort();
    activeRefreshController = null;
    refreshInFlight = false;
  }

  return {
    refresh,
    cancel,
    get refreshInFlight() {
      return refreshInFlight;
    },
  };
}
