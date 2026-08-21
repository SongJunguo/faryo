import { h } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";

import type {
  InteractionAction,
  InteractionHostOptions,
  InteractionOption,
  PendingInteraction,
} from "./interaction-types";

const KIND_LABELS: Record<string, string> = {
  approval: "Approval",
  generic_tui: "Codex menu",
  model_select: "Model",
  permissions_select: "Permissions",
  reasoning_select: "Reasoning",
  resume_directory: "Resume",
  usage_select: "Usage",
  workspace_trust: "Workspace trust",
};

function requestId(): string {
  return globalThis.crypto?.randomUUID
    ? `ixr-${globalThis.crypto.randomUUID()}`
    : `ixr-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
}

function OptionRow({
  option,
  invoke,
}: {
  option: InteractionOption;
  invoke(option: InteractionOption): void;
}) {
  return (
    <button
      type="button"
      class={`interaction-option${option.selected ? " selected" : ""}`}
      disabled={option.disabled}
      aria-current={option.selected ? "true" : undefined}
      onClick={() => invoke(option)}
    >
      <span class="interaction-option-marker" aria-hidden="true">
        {option.selected ? "›" : ""}
      </span>
      <span class="interaction-option-copy">
        <strong>{option.label}</strong>
        {option.description && <small>{option.description}</small>}
      </span>
      {option.current && <span class="interaction-current">Current</span>}
    </button>
  );
}

export function InteractionHost({
  interaction,
  options,
  confirmation,
  onConfirmCommand,
}: {
  interaction: PendingInteraction | null;
  options: InteractionHostOptions;
  confirmation?: {
    command: string;
    description: string;
    risk: string;
  } | null;
  onConfirmCommand?(confirmed: boolean): void;
}) {
  const [pending, setPending] = useState(false);
  const [localInteraction, setLocalInteraction] = useState(interaction);

  useEffect(() => {
    setLocalInteraction(interaction);
    setPending(false);
  }, [interaction?.id]);

  const actions = useMemo(
    () => new Set(localInteraction?.actions || []),
    [localInteraction?.id],
  );

  async function respond(request: {
    action?: InteractionAction;
    optionId?: string;
  }) {
    if (!localInteraction || pending) return;
    const activeId = localInteraction.id;
    setPending(true);
    try {
      const response = await options.onRespond({
        interactionId: activeId,
        ...request,
      });
      setLocalInteraction(response.interaction || null);
    } catch (error) {
      options.onError?.(error);
    } finally {
      setPending(false);
    }
  }

  useEffect(() => {
    if (!localInteraction) return undefined;
    const listener = (event: KeyboardEvent) => {
      if (pending) return;
      const action = (
        {
          ArrowUp: "previous",
          ArrowDown: "next",
          Enter: "choose",
          Escape: "cancel",
        } as const
      )[event.key];
      if (!action || !actions.has(action)) return;
      event.preventDefault();
      void respond({ action });
    };
    document.addEventListener("keydown", listener, { capture: true });
    return () =>
      document.removeEventListener("keydown", listener, { capture: true });
  }, [localInteraction?.id, pending, actions]);

  useEffect(() => {
    if (!confirmation || localInteraction) return undefined;
    const listener = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onConfirmCommand?.(false);
    };
    document.addEventListener("keydown", listener, { capture: true });
    return () =>
      document.removeEventListener("keydown", listener, { capture: true });
  }, [confirmation?.command, localInteraction?.id]);

  if (!localInteraction && confirmation) {
    return (
      <div class="interaction-backdrop" data-interaction-kind="command_confirm">
        <section
          class="interaction-sheet interaction-confirm-sheet"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="interactionTitle"
          aria-describedby="interactionPrompt"
        >
          <div class="interaction-heading">
            <span>Confirm command</span>
            <strong id="interactionTitle">Run this Codex command once?</strong>
            <p id="interactionPrompt">
              {confirmation.description ||
                "This command is not a normal chat message."}
            </p>
          </div>
          <pre class="interaction-confirm-command">{confirmation.command}</pre>
          <div class="interaction-confirm-risk">
            Risk: {confirmation.risk || "unclassified"}. Faryo will submit it
            once and will not retry Enter blindly.
          </div>
          <div class="interaction-actions">
            <button type="button" onClick={() => onConfirmCommand?.(false)}>
              Cancel
            </button>
            <button
              class="interaction-confirm-run"
              type="button"
              onClick={() => onConfirmCommand?.(true)}
            >
              Run once
            </button>
          </div>
        </section>
      </div>
    );
  }

  if (!localInteraction) return null;
  const kindLabel = KIND_LABELS[localInteraction.kind] || "Codex interaction";
  return (
    <div
      class="interaction-backdrop"
      data-interaction-kind={localInteraction.kind}
    >
      <section
        class="interaction-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="interactionTitle"
        aria-describedby="interactionPrompt"
      >
        <div class="interaction-heading">
          <span>{kindLabel}</span>
          <strong id="interactionTitle">{localInteraction.title}</strong>
          <p id="interactionPrompt">{localInteraction.prompt}</p>
        </div>
        <div class="interaction-options" role="listbox" aria-busy={pending}>
          {localInteraction.options.map((option) => (
            <OptionRow
              key={option.id}
              option={option}
              invoke={(selected) => void respond({ optionId: selected.id })}
            />
          ))}
        </div>
        <div class="interaction-actions">
          <div class="interaction-nav-actions">
            {actions.has("previous") && (
              <button
                type="button"
                disabled={pending}
                onClick={() => void respond({ action: "previous" })}
              >
                ↑ Previous
              </button>
            )}
            {actions.has("next") && (
              <button
                type="button"
                disabled={pending}
                onClick={() => void respond({ action: "next" })}
              >
                ↓ Next
              </button>
            )}
          </div>
          {actions.has("cancel") && (
            <button
              class="interaction-cancel"
              type="button"
              disabled={pending}
              onClick={() => void respond({ action: "cancel" })}
            >
              Cancel
            </button>
          )}
        </div>
        {pending && (
          <div class="interaction-pending" role="status">
            Applying selection…
          </div>
        )}
      </section>
    </div>
  );
}

export { requestId };
