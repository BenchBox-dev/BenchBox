import type { ComponentChildren } from "preact";
import { useRef } from "preact/hooks";

export interface SegmentedOption<T extends string> {
  value: T;
  label: ComponentChildren;
  disabled?: boolean;
  title?: string;
}

interface SegmentedControlProps<T extends string> {
  /** Accessible label for the group. Required. */
  ariaLabel: string;
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
  class?: string;
}

const SIZE_CLASS = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-3 py-1.5 text-sm",
} as const;

export function SegmentedControl<T extends string>({
  ariaLabel,
  options,
  value,
  onChange,
  size = "md",
  class: extraClass = "",
}: SegmentedControlProps<T>) {
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  optionRefs.current.length = options.length;

  const enabledOptions = options
    .map((option, index) => ({ option, index }))
    .filter(({ option }) => !option.disabled);
  const selectedIndex = options.findIndex((option) => option.value === value && !option.disabled);
  const focusableIndex = selectedIndex >= 0 ? selectedIndex : enabledOptions[0]?.index;

  const selectAndFocus = (index: number) => {
    const option = options[index];
    if (!option || option.disabled) return;
    optionRefs.current[index]?.focus();
    onChange(option.value);
  };

  const moveFocus = (direction: 1 | -1, fromIndex: number) => {
    if (enabledOptions.length === 0) return;
    const currentEnabledIndex = enabledOptions.findIndex(({ index }) => index === fromIndex);
    const nextEnabledIndex =
      (currentEnabledIndex + direction + enabledOptions.length) % enabledOptions.length;
    selectAndFocus(enabledOptions[nextEnabledIndex]!.index);
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
        const firstEnabledOption = enabledOptions[0];
        if (firstEnabledOption) {
          selectAndFocus(firstEnabledOption.index);
        }
        break;
      }
      case "End": {
        event.preventDefault();
        const lastEnabledOption = enabledOptions[enabledOptions.length - 1];
        if (lastEnabledOption) {
          selectAndFocus(lastEnabledOption.index);
        }
        break;
      }
      default:
        break;
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      class={`inline-flex rounded-md panel-muted p-0.5 ${extraClass}`}
    >
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-disabled={option.disabled || undefined}
            disabled={option.disabled}
            tabIndex={index === focusableIndex ? 0 : -1}
            title={option.title}
            ref={(node) => {
              optionRefs.current[index] = node;
            }}
            onClick={() => !option.disabled && onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event as KeyboardEvent, index)}
            class={`rounded transition-colors ${SIZE_CLASS[size]} ${
              selected
                ? "bg-[var(--bb-surface-data)] text-[var(--bb-data-fg-primary)] shadow-sm font-medium"
                : "text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)]"
            } ${option.disabled ? "opacity-60 cursor-not-allowed" : ""}`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export default SegmentedControl;
