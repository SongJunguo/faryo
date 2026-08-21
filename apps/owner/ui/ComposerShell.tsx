import { h, render } from "preact";
import { useLayoutEffect, useState } from "preact/hooks";

export interface CommandSuggestion {
  label: string;
  hint: string;
  description: string;
  category: string;
  aliases: string;
  risk: string;
}

interface ComposerView {
  suggestions: CommandSuggestion[];
  selectedIndex: number;
  summary: string;
  sendVisible: boolean;
  plusVisible: boolean;
}

export interface ComposerShellOptions {
  onSuggestionSelect(index: number): void;
}

export interface ComposerShellController {
  updateSuggestions(
    suggestions: CommandSuggestion[],
    selectedIndex: number,
    summary?: string,
  ): void;
  updateControls(values: { sendVisible: boolean; plusVisible: boolean }): void;
  destroy(): void;
}

function createComposerStore() {
  let value: ComposerView = {
    suggestions: [],
    selectedIndex: 0,
    summary: "",
    sendVisible: false,
    plusVisible: true,
  };
  const listeners = new Set<(value: ComposerView) => void>();
  return {
    get: () => value,
    set(next: Partial<ComposerView>) {
      value = { ...value, ...next };
      for (const listener of listeners) listener(value);
    },
    subscribe(listener: (value: ComposerView) => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

type ComposerStore = ReturnType<typeof createComposerStore>;

function ComposerShell({
  store,
  options,
}: {
  store: ComposerStore;
  options: ComposerShellOptions;
}) {
  const [view, setView] = useState(store.get());
  useLayoutEffect(() => store.subscribe(setView), [store]);
  const hasSuggestions = view.suggestions.length > 0;
  return (
    <div class="command-dock">
      <div
        id="commandSuggest"
        class={`command-suggest${hasSuggestions ? "" : " hidden"}`}
        role="listbox"
        aria-label="Command suggestions"
        aria-activedescendant={
          hasSuggestions ? `command-option-${view.selectedIndex}` : ""
        }
        onMouseDown={(event) => event.preventDefault()}
      >
        {view.summary && (
          <div class="command-suggest-summary">{view.summary}</div>
        )}
        {view.suggestions.map((item, index) => {
          const selected = index === view.selectedIndex;
          return (
            <button
              id={`command-option-${index}`}
              key={`${item.label}-${index}`}
              type="button"
              role="option"
              aria-selected={selected}
              data-index={index}
              class={selected ? "selected" : ""}
              onClick={() => options.onSuggestionSelect(index)}
            >
              <span class="command-suggest-main">
                <strong>
                  {item.label}
                  {item.hint}
                </strong>
                <small>{item.description}</small>
              </span>
              <span class="command-suggest-meta">
                {item.category}
                {item.aliases}
                {item.risk && <span class="command-risk">{item.risk}</span>}
              </span>
            </button>
          );
        })}
      </div>
      <div class="prompt-shell">
        <div
          id="petControl"
          class="pet-control pet-offline"
          aria-label="Faryo offline; tap to interrupt"
        />
        <textarea id="promptInput" placeholder="Ask Faryo" rows={1} />
        <button
          id="dockPlusBtn"
          class={`dock-plus${view.plusVisible ? "" : " hidden"}`}
          type="button"
          aria-label="Open input tools"
          aria-expanded="false"
          aria-controls="dockMenu"
        >
          +
        </button>
        <button
          id="sendBtn"
          class={`dock-send${view.sendVisible ? "" : " hidden"}`}
          type="button"
          aria-label="Send"
        >
          ↑
        </button>
      </div>
    </div>
  );
}

export function mountComposerShell(
  container: HTMLElement,
  options: ComposerShellOptions,
): ComposerShellController {
  const store = createComposerStore();
  renderComposer(container, store, options);
  return {
    updateSuggestions(suggestions, selectedIndex, summary = "") {
      store.set({ suggestions, selectedIndex, summary });
    },
    updateControls(values) {
      store.set(values);
    },
    destroy() {
      render(null, container);
    },
  };
}

function renderComposer(
  container: HTMLElement,
  store: ComposerStore,
  options: ComposerShellOptions,
) {
  // Kept behind this helper so mount remains synchronous before legacy
  // adapters query the stable element ids.
  render(<ComposerShell store={store} options={options} />, container);
}
