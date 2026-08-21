export type ConversationMode = "compact" | "full";

export type ConversationPhase =
  "loading" | "starting" | "ready" | "empty" | "fallback" | "render_error";

export interface ConversationScope {
  session: string;
  generation: number;
  mode: ConversationMode;
}

export interface ConversationSnapshot extends ConversationScope {
  phase: ConversationPhase;
  captureRevision: number;
  captureSource: string;
  agentSource: string;
  updatePending: boolean;
}

export interface ConversationCapture {
  text?: unknown;
  captureSource?: unknown;
  agentSource?: unknown;
  source?: unknown;
}

export interface ConversationStore {
  get(): ConversationSnapshot;
  scope(): ConversationScope;
  accepts(scope?: ConversationScope | null): boolean;
  subscribe(listener: (snapshot: ConversationSnapshot) => void): () => void;
  switchSession(session: string): ConversationScope;
  setMode(mode: ConversationMode): ConversationScope;
  beginLoading(): void;
  beginStarting(updatePending?: boolean): void;
  commitCapture(
    capture: ConversationCapture,
    scope?: ConversationScope | null,
  ): boolean;
  markRenderError(): void;
}

function structuredCaptureSource(value: string): boolean {
  return (
    value === "codex-jsonl" ||
    value === "codex-app-server" ||
    value === "codex-empty"
  );
}

function frozenSnapshot(value: ConversationSnapshot): ConversationSnapshot {
  return Object.freeze({ ...value });
}

export function createConversationStore(
  initial: Partial<Pick<ConversationSnapshot, "session" | "mode">> = {},
): ConversationStore {
  let snapshot = frozenSnapshot({
    session: String(initial.session || ""),
    generation: 0,
    mode: initial.mode === "full" ? "full" : "compact",
    phase: "loading",
    captureRevision: 0,
    captureSource: "",
    agentSource: "",
    updatePending: false,
  });
  const listeners = new Set<(value: ConversationSnapshot) => void>();
  const publish = (patch: Partial<ConversationSnapshot>) => {
    snapshot = frozenSnapshot({ ...snapshot, ...patch });
    for (const listener of listeners) listener(snapshot);
  };
  const scope = (): ConversationScope => ({
    session: snapshot.session,
    generation: snapshot.generation,
    mode: snapshot.mode,
  });
  const accepts = (candidate?: ConversationScope | null): boolean =>
    !candidate ||
    (candidate.session === snapshot.session &&
      candidate.generation === snapshot.generation &&
      candidate.mode === snapshot.mode);

  return {
    get: () => snapshot,
    scope,
    accepts,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    switchSession(session) {
      const nextSession = String(session || "");
      if (nextSession === snapshot.session) return scope();
      publish({
        session: nextSession,
        generation: snapshot.generation + 1,
        phase: "loading",
        captureRevision: 0,
        captureSource: "",
        agentSource: "",
        updatePending: false,
      });
      return scope();
    },
    setMode(mode) {
      if (mode === snapshot.mode) return scope();
      publish({
        mode,
        generation: snapshot.generation + 1,
        phase: "loading",
        captureSource: "",
        agentSource: "",
        updatePending: false,
      });
      return scope();
    },
    beginLoading() {
      publish({ phase: "loading", updatePending: false });
    },
    beginStarting(updatePending = false) {
      publish({ phase: "starting", updatePending });
    },
    commitCapture(capture, candidateScope = null) {
      if (!accepts(candidateScope)) return false;
      const captureSource = String(
        capture.captureSource || capture.source || "",
      );
      const agentSource = String(capture.agentSource || "");
      const text = String(capture.text || "");
      const structured = structuredCaptureSource(captureSource);
      let phase: ConversationPhase = "ready";
      if (snapshot.mode === "compact" && structured && !text.trim()) {
        phase = "empty";
      } else if (
        snapshot.mode === "compact" &&
        agentSource === "codex-cli" &&
        !structured
      ) {
        phase = "fallback";
      }
      publish({
        phase,
        captureRevision: snapshot.captureRevision + 1,
        captureSource,
        agentSource,
        updatePending: false,
      });
      return true;
    },
    markRenderError() {
      publish({ phase: "render_error", updatePending: false });
    },
  };
}
