import type { ComponentChildren } from "preact";
import { useRef } from "preact/hooks";

export interface TabItem<T extends string> {
  value: T;
  label: ComponentChildren;
  disabled?: boolean;
  count?: number;
}

interface TabsProps<T extends string> {
  ariaLabel: string;
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  /** id of the tabpanel controlled by this tablist (for aria-controls). */
  controls?: string;
  class?: string;
}

export function Tabs<T extends string>({
  ariaLabel,
  items,
  value,
  onChange,
  controls,
  class: extraClass = "",
}: TabsProps<T>) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const selectAndFocus = (index: number) => {
    const item = items[index];
    if (!item || item.disabled) return;
    tabRefs.current[index]?.focus();
    onChange(item.value);
  };

  const moveFocus = (direction: 1 | -1, fromIndex: number) => {
    const enabled = items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => !item.disabled);
    if (enabled.length === 0) return;
    const currentEnabledIdx = enabled.findIndex(({ index }) => index === fromIndex);
    const nextEnabledIdx =
      (currentEnabledIdx + direction + enabled.length) % enabled.length;
    selectAndFocus(enabled[nextEnabledIdx]!.index);
  };

  const onKeyDown = (event: KeyboardEvent, currentIndex: number) => {
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        moveFocus(1, currentIndex);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        moveFocus(-1, currentIndex);
        break;
      case "Home": {
        event.preventDefault();
        const first = items.findIndex((item) => !item.disabled);
        if (first >= 0) selectAndFocus(first);
        break;
      }
      case "End": {
        event.preventDefault();
        const last = items.reduce((lastIndex, item, index) => (item.disabled ? lastIndex : index), -1);
        if (last >= 0) selectAndFocus(last);
        break;
      }
      default:
        break;
    }
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      class={`flex flex-wrap items-center gap-1 border-b border-[var(--bb-data-border)] ${extraClass}`}
    >
      {items.map((item, index) => {
        const selected = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={controls}
            aria-disabled={item.disabled || undefined}
            disabled={item.disabled}
            tabIndex={selected ? 0 : -1}
            ref={(node) => {
              tabRefs.current[index] = node;
            }}
            onClick={() => !item.disabled && onChange(item.value)}
            onKeyDown={(event) => onKeyDown(event as KeyboardEvent, index)}
            class={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              selected
                ? "border-[var(--bb-accent-hover)] text-[var(--bb-data-fg-primary)]"
                : "border-transparent text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)]"
            } ${item.disabled ? "opacity-60 cursor-not-allowed" : ""}`}
          >
            <span>{item.label}</span>
            {typeof item.count === "number" ? (
              <span class="ml-1.5 text-xs text-[var(--bb-data-fg-subtle)]">({item.count})</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export default Tabs;
