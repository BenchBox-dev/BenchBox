import type { ComponentChildren } from "preact";

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
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      class={`inline-flex rounded-md panel-muted p-0.5 ${extraClass}`}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-disabled={option.disabled || undefined}
            disabled={option.disabled}
            title={option.title}
            onClick={() => !option.disabled && onChange(option.value)}
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
