import { h } from "preact";
import { useLayoutEffect, useRef } from "preact/hooks";

export interface CommandSuggestion {
  label: string;
  hint: string;
  description: string;
  category: string;
  aliases: string;
  risk: string;
}

export function CommandPalette({
  suggestions,
  selectedIndex,
  summary,
  onSelect,
}: {
  suggestions: CommandSuggestion[];
  selectedIndex: number;
  summary: string;
  onSelect(index: number): void;
}) {
  const visible = suggestions.length > 0;
  const root = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    root.current
      ?.querySelector<HTMLElement>('[role="option"][aria-selected="true"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex, suggestions]);
  return (
    <div
      ref={root}
      id="commandSuggest"
      class={`command-suggest${visible ? "" : " hidden"}`}
      role="listbox"
      aria-label="Command suggestions"
      aria-activedescendant={visible ? `command-option-${selectedIndex}` : ""}
      onMouseDown={(event) => event.preventDefault()}
    >
      {summary && <div class="command-suggest-summary">{summary}</div>}
      {suggestions.map((item, index) => {
        const selected = index === selectedIndex;
        return (
          <button
            id={`command-option-${index}`}
            key={`${item.label}-${index}`}
            type="button"
            role="option"
            aria-selected={selected}
            data-index={index}
            class={selected ? "selected" : ""}
            onClick={() => onSelect(index)}
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
  );
}
