export function isAmbiguousDeliveryError(error) {
  return error instanceof TypeError
    || error?.name === "AbortError"
    || [502, 504].includes(Number(error?.status || 0));
}

export function createComposerDelivery(options = {}) {
  const storage = options.storage;
  const routeKey = String(options.routeKey || "owner");
  const crypto = options.crypto || globalThis.crypto;
  const AbortControllerType = options.AbortController || globalThis.AbortController;
  const timeoutMs = Number(options.timeoutMs || 12000);
  let pendingSubmission = null;
  if (!storage) throw new TypeError("Composer delivery requires session storage");

  function draftKey(session) {
    return `faryoPromptDraft:${routeKey}:${session || "default"}`;
  }

  function pendingKey(session) {
    return `${draftKey(session)}:pending`;
  }

  function persistDraft(session, value) {
    try {
      if (value) storage.setItem(draftKey(session), value);
      else storage.removeItem(draftKey(session));
    } catch (_error) {}
  }

  function persistPending(submission = pendingSubmission, session = submission?.session) {
    const targetSession = session || options.getSession();
    try {
      if (submission) storage.setItem(pendingKey(targetSession), JSON.stringify(submission));
      else storage.removeItem(pendingKey(targetSession));
    } catch (_error) {}
  }

  function clearPending(submission) {
    if (!submission?.session) return;
    persistPending(null, submission.session);
    if (pendingSubmission?.id === submission.id) pendingSubmission = null;
  }

  function clearDeliveredDraft(submission) {
    try {
      const key = draftKey(submission.session);
      if (storage.getItem(key) === submission.browserText) storage.removeItem(key);
    } catch (_error) {}
  }

  function preserveFailedDraft(submission) {
    try {
      const key = draftKey(submission.session);
      if (storage.getItem(key) === null) storage.setItem(key, submission.browserText);
      if (storage.getItem(key) === submission.browserText) {
        pendingSubmission = { ...submission };
        persistPending(pendingSubmission, submission.session);
      }
    } catch (_error) {}
  }

  function restore(session) {
    let inputValue = "";
    try {
      inputValue = storage.getItem(draftKey(session)) || "";
      const restored = JSON.parse(storage.getItem(pendingKey(session)) || "null");
      pendingSubmission = restored?.browserText === inputValue
        && (!restored.session || restored.session === session)
        ? { ...restored, session }
        : null;
      if (pendingSubmission && restored.session !== session) persistPending(pendingSubmission, session);
      if (!pendingSubmission) storage.removeItem(pendingKey(session));
    } catch (_error) {
      pendingSubmission = null;
    }
    return { inputValue, pendingSubmission };
  }

  function newClientMessageId() {
    if (crypto?.randomUUID) return `web-${crypto.randomUUID()}`;
    return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
  }

  function prepareSubmission(values) {
    const reusable = pendingSubmission
      && pendingSubmission.session === values.session
      && pendingSubmission.browserText === values.browserText
      && pendingSubmission.outboundText === values.outboundText;
    if (!reusable) {
      pendingSubmission = {
        id: newClientMessageId(),
        session: values.session,
        browserText: values.browserText,
        outboundText: values.outboundText,
        attachmentPaths: [...(values.attachmentPaths || [])],
      };
      persistPending(pendingSubmission, values.session);
    }
    return {
      ...pendingSubmission,
      attachmentPaths: [...(pendingSubmission.attachmentPaths || [])],
    };
  }

  function discardPendingIfChanged(browserText, session = options.getSession()) {
    if (!pendingSubmission || pendingSubmission.browserText === browserText) return false;
    const staleSession = pendingSubmission.session || session;
    pendingSubmission = null;
    persistPending(null, staleSession);
    return true;
  }

  async function attempt(payload) {
    const controller = new AbortControllerType();
    const timeoutId = options.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await options.sendAction(payload, { signal: controller.signal });
    } catch (error) {
      if (error?.name !== "AbortError") throw error;
      const timeoutError = new Error("Send confirmation timed out");
      timeoutError.name = "AbortError";
      timeoutError.status = 504;
      throw timeoutError;
    } finally {
      options.clearTimeout(timeoutId);
    }
  }

  async function send(payload) {
    try {
      return await attempt(payload);
    } catch (error) {
      if (!isAmbiguousDeliveryError(error)) throw error;
      options.onChecking?.();
      await new Promise((resolve) => options.setTimeout(resolve, 180));
      return attempt(payload);
    }
  }

  return {
    draftKey,
    pendingKey,
    persistDraft,
    persistPending,
    clearPending,
    clearDeliveredDraft,
    preserveFailedDraft,
    restore,
    prepareSubmission,
    discardPendingIfChanged,
    send,
    get pendingSubmission() { return pendingSubmission; },
  };
}
