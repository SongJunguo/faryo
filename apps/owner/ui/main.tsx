import { h, render } from "preact";

import { mountComposerShell } from "./ComposerShell";
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
  const draw = () =>
    render(
      <InteractionHost
        interaction={current}
        options={options}
        confirmation={confirmation}
        onConfirmCommand={settleConfirmation}
      />,
      container,
    );
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
