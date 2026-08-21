import { h } from "preact";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";

import type {
  InteractionAction,
  InteractionHostOptions,
  InteractionOption,
  PendingInteraction,
} from "./interaction-types";

const KIND_LABELS: Record<string, string> = {
  approval: "Approval",
  user_input: "Question",
  generic_tui: "Codex menu",
  model_select: "Model",
  permissions_select: "Permissions",
  reasoning_select: "Reasoning",
  resume_directory: "Resume",
  usage_select: "Usage",
  workspace_trust: "Workspace trust",
};

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
  const [questionAnswers, setQuestionAnswers] = useState<
    Record<string, string>
  >({});
  const activeInteractionId = useRef(interaction?.id || "");

  useLayoutEffect(() => {
    activeInteractionId.current = interaction?.id || "";
    setLocalInteraction(interaction);
    setQuestionAnswers({});
    setPending(false);
  }, [interaction]);

  const actions = new Set(localInteraction?.actions || []);

  async function respond(request: {
    action?: InteractionAction;
    optionId?: string;
    answers?: Record<string, string[]>;
  }) {
    if (!localInteraction || pending) return;
    const activeId = localInteraction.id;
    setPending(true);
    try {
      const response = await options.onRespond({
        interactionId: activeId,
        ...request,
      });
      if (!response.ignored && activeInteractionId.current === activeId) {
        const nextInteraction = response.interaction || null;
        activeInteractionId.current = nextInteraction?.id || "";
        setLocalInteraction(nextInteraction);
      }
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
  const questions = localInteraction.questions || [];
  const isQuestionForm =
    localInteraction.responseKind === "questions" && questions.length > 0;
  const questionFormComplete =
    isQuestionForm &&
    questions.every((question) =>
      Boolean(questionAnswers[question.id]?.trim()),
    );
  const details = localInteraction.details || {};
  const command = typeof details.command === "string" ? details.command : "";
  const detailPath = [details.cwd, details.path].find(
    (value) => typeof value === "string" && value,
  ) as string | undefined;
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
        {(command || detailPath) && (
          <div class="interaction-request-details">
            {command && <pre>{command}</pre>}
            {detailPath && <small>{detailPath}</small>}
          </div>
        )}
        {isQuestionForm ? (
          <form
            class="interaction-questions"
            aria-busy={pending}
            onSubmit={(event) => {
              event.preventDefault();
              if (!questionFormComplete) return;
              void respond({
                answers: Object.fromEntries(
                  questions.map((question) => [
                    question.id,
                    [(questionAnswers[question.id] || "").trim()],
                  ]),
                ),
              });
            }}
          >
            {questions.map((question) => (
              <fieldset key={question.id}>
                <legend>
                  <span>{question.header}</span>
                  <strong>{question.question}</strong>
                </legend>
                {question.options.map((option) => (
                  <label class="interaction-question-option" key={option.label}>
                    <input
                      type="radio"
                      name={`question-${question.id}`}
                      value={option.label}
                      checked={questionAnswers[question.id] === option.label}
                      onChange={() =>
                        setQuestionAnswers((current) => ({
                          ...current,
                          [question.id]: option.label,
                        }))
                      }
                    />
                    <span>
                      <strong>{option.label}</strong>
                      {option.description && (
                        <small>{option.description}</small>
                      )}
                    </span>
                  </label>
                ))}
                {question.isOther && (
                  <input
                    class="interaction-question-other"
                    type={question.isSecret ? "password" : "text"}
                    autoComplete="off"
                    placeholder="Type another answer"
                    value={
                      question.options.some(
                        (option) =>
                          option.label === questionAnswers[question.id],
                      )
                        ? ""
                        : questionAnswers[question.id] || ""
                    }
                    onInput={(event) =>
                      setQuestionAnswers((current) => ({
                        ...current,
                        [question.id]: event.currentTarget.value,
                      }))
                    }
                  />
                )}
              </fieldset>
            ))}
            <button
              class="interaction-submit-answers"
              type="submit"
              disabled={pending || !questionFormComplete}
            >
              Submit answers
            </button>
          </form>
        ) : (
          <div class="interaction-options" role="listbox" aria-busy={pending}>
            {localInteraction.options.map((option) => (
              <OptionRow
                key={option.id}
                option={option}
                invoke={(selected) => void respond({ optionId: selected.id })}
              />
            ))}
          </div>
        )}
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
            {actions.has("choose") && (
              <button
                class="interaction-choose"
                type="button"
                disabled={pending}
                aria-label="Choose the highlighted Codex option"
                title="Press Enter to choose the highlighted Codex option"
                onClick={() => void respond({ action: "choose" })}
              >
                Choose highlighted
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
