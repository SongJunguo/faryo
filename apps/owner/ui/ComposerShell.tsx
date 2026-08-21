import { h, render } from "preact";
import type { JSX } from "preact";
import { useLayoutEffect, useState } from "preact/hooks";

import { CommandPalette } from "./CommandPalette";
import type { CommandSuggestion } from "./CommandPalette";
import { Composer } from "./Composer";

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
  updateSuggestions(suggestions: CommandSuggestion[], summary?: string): void;
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
  let suggestionSignature = "";
  const listeners = new Set<(value: ComposerView) => void>();
  const publish = (next: ComposerView) => {
    value = next;
    for (const listener of listeners) listener(value);
  };
  return {
    get: () => value,
    setControls(next: Pick<ComposerView, "sendVisible" | "plusVisible">) {
      publish({ ...value, ...next });
    },
    setSuggestions(suggestions: CommandSuggestion[], summary = "") {
      const nextSignature = suggestions
        .map((item) => `${item.label}\0${item.hint}`)
        .join("\n");
      const selectedIndex =
        nextSignature === suggestionSignature
          ? Math.min(value.selectedIndex, Math.max(0, suggestions.length - 1))
          : 0;
      suggestionSignature = nextSignature;
      publish({ ...value, suggestions, selectedIndex, summary });
    },
    moveSelection(delta: number) {
      if (!value.suggestions.length) return;
      const selectedIndex =
        (value.selectedIndex + delta + value.suggestions.length) %
        value.suggestions.length;
      publish({ ...value, selectedIndex });
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
  function handleKeyDown(
    event: JSX.TargetedKeyboardEvent<HTMLTextAreaElement>,
  ) {
    const current = store.get();
    if (
      (event.key === "ArrowDown" || event.key === "ArrowUp") &&
      current.suggestions.length
    ) {
      event.preventDefault();
      store.moveSelection(event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (
      (event.key === "Tab" || event.key === "Enter") &&
      current.suggestions.length
    ) {
      event.preventDefault();
      options.onSuggestionSelect(current.selectedIndex);
      return;
    }
    if (event.key === "Escape" && current.suggestions.length) {
      event.preventDefault();
      store.setSuggestions([]);
    }
  }
  return (
    <div class="command-dock">
      <CommandPalette
        suggestions={view.suggestions}
        selectedIndex={view.selectedIndex}
        summary={view.summary}
        onSelect={options.onSuggestionSelect}
      />
      <Composer
        sendVisible={view.sendVisible}
        plusVisible={view.plusVisible}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
}

export type { CommandSuggestion };

export function mountComposerShell(
  container: HTMLElement,
  options: ComposerShellOptions,
): ComposerShellController {
  const store = createComposerStore();
  renderComposer(container, store, options);
  return {
    updateSuggestions(suggestions, summary = "") {
      store.setSuggestions(suggestions, summary);
    },
    updateControls(values) {
      store.setControls(values);
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
