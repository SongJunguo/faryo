import { h, render } from "preact";

import { mountComposerShell } from "./ComposerShell";
import { ErrorBoundary } from "./ErrorBoundary";
import { InteractionHost } from "./InteractionHost";
import { mountStatusShell } from "./StatusShell";
import type {
  InteractionHostController,
  InteractionHostOptions,
  PendingInteraction,
} from "./interaction-types";

export function mountInteractionHost(
  container: HTMLElement,
  options: InteractionHostOptions,
): InteractionHostController {
  let current: PendingInteraction | null = null;
  let confirmation: {
    command: string;
    description: string;
    risk: string;
  } | null = null;
  let resolveConfirmation: ((confirmed: boolean) => void) | null = null;
  const settleConfirmation = (confirmed: boolean) => {
    const resolve = resolveConfirmation;
    resolveConfirmation = null;
    confirmation = null;
    draw();
    resolve?.(confirmed);
  };
  const draw = () => {
    const boundaryKey =
      current?.id || (confirmation ? "command-confirm" : "empty");
    render(
      <ErrorBoundary
        key={boundaryKey}
        surface="interaction"
        fallback={
          <div
            class="interaction-backdrop"
            data-interaction-kind="render_error"
          >
            <section
              class="interaction-sheet interaction-confirm-sheet"
              role="alert"
            >
              <div class="interaction-heading">
                <span>Codex interaction</span>
                <strong>Interaction view unavailable</strong>
                <p>
                  Reload this session to rebuild the current menu from the real
                  Codex TUI. The transcript remains available behind this panel.
                </p>
              </div>
              <div class="interaction-actions">
                <button type="button" onClick={() => window.location.reload()}>
                  Reload session
                </button>
              </div>
            </section>
          </div>
        }
      >
        <InteractionHost
          interaction={current}
          options={options}
          confirmation={confirmation}
          onConfirmCommand={settleConfirmation}
        />
      </ErrorBoundary>,
      container,
    );
  };
  draw();
  return {
    update(interaction) {
      if (interaction && confirmation) settleConfirmation(false);
      current = interaction;
      draw();
    },
    confirmCommand(values) {
      if (resolveConfirmation) settleConfirmation(false);
      current = null;
      confirmation = values;
      draw();
      return new Promise<boolean>((resolve) => {
        resolveConfirmation = resolve;
      });
    },
    destroy() {
      resolveConfirmation?.(false);
      resolveConfirmation = null;
      confirmation = null;
      current = null;
      render(null, container);
    },
  };
}

declare global {
  interface Window {
    FaryoOwnerUI?: {
      mountInteractionHost: typeof mountInteractionHost;
      mountComposerShell: typeof mountComposerShell;
      mountStatusShell: typeof mountStatusShell;
    };
  }
}

window.FaryoOwnerUI = {
  mountComposerShell,
  mountInteractionHost,
  mountStatusShell,
};
