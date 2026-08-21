import { Component, h, render } from "preact";
import { useLayoutEffect, useState } from "preact/hooks";

import type {
  ConversationSnapshot,
  ConversationStore,
} from "./ConversationStore";
import { ErrorBoundary } from "./ErrorBoundary";

class LegacyTranscriptSurface extends Component {
  override shouldComponentUpdate(): boolean {
    return false;
  }

  override render() {
    return (
      <pre id="output" class="output">
        {null}
      </pre>
    );
  }
}

function TranscriptNotice({ snapshot }: { snapshot: ConversationSnapshot }) {
  if (snapshot.phase === "ready") return null;
  let title = "Loading conversation…";
  let detail = "Faryo is connecting to this session.";
  let tone = snapshot.phase;
  if (snapshot.phase === "starting") {
    title = snapshot.updatePending
      ? "Checking for a Codex update…"
      : "Starting Codex…";
    detail = snapshot.updatePending
      ? "Faryo will install an available official Codex update, then open this conversation automatically."
      : "The session is open. Faryo will connect automatically when startup finishes.";
  } else if (snapshot.phase === "empty") {
    title = "No messages yet";
    detail = "Ask Codex to start this conversation.";
  } else if (snapshot.phase === "fallback") {
    title = "Structured Codex history is unavailable";
    detail =
      "Showing a terminal fallback; Markdown and formulas may be incomplete.";
  } else if (snapshot.phase === "render_error") {
    title = "Rich conversation layout failed";
    detail =
      "Safe plain text remains available and live updates will continue.";
  } else if (snapshot.mode === "full") {
    title = "Loading raw terminal…";
    detail = "Raw view keeps the current terminal evidence.";
  }
  return (
    <section
      id="transcriptNotice"
      class={`transcript-notice transcript-notice-${tone}`}
      role="status"
    >
      <strong>{title}</strong>
      <span>{detail}</span>
    </section>
  );
}

function TranscriptShell({ store }: { store: ConversationStore }) {
  const [snapshot, setSnapshot] = useState(store.get());
  useLayoutEffect(
    () =>
      store.subscribe((next) => {
        setSnapshot((current) =>
          current.session === next.session &&
          current.generation === next.generation &&
          current.mode === next.mode &&
          current.phase === next.phase &&
          current.updatePending === next.updatePending
            ? current
            : next,
        );
      }),
    [store],
  );
  return (
    <div
      class="transcript-shell"
      data-conversation-phase={snapshot.phase}
      data-conversation-generation={snapshot.generation}
      data-conversation-mode={snapshot.mode}
    >
      <ErrorBoundary
        surface="transcript"
        fallback={
          <section class="transcript-notice transcript-notice-render_error">
            <strong>Conversation status unavailable</strong>
            <span>The transcript remains available below.</span>
          </section>
        }
      >
        <TranscriptNotice snapshot={snapshot} />
      </ErrorBoundary>
      <LegacyTranscriptSurface />
    </div>
  );
}

export interface TranscriptShellController {
  output: HTMLElement;
  destroy(): void;
}

export function mountTranscriptShell(
  container: HTMLElement,
  store: ConversationStore,
): TranscriptShellController {
  render(<TranscriptShell store={store} />, container);
  const output = container.querySelector<HTMLElement>("#output");
  if (!output) throw new Error("Transcript surface was not mounted");
  return {
    output,
    destroy() {
      render(null, container);
    },
  };
}
