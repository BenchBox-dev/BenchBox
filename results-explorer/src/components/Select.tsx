import type { ComponentChildren, JSX } from "preact";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

// Preact convention: callers pass `class` (not `className`).
type NativeSelectProps = Omit<
  JSX.IntrinsicElements["select"],
  "size" | "onChange" | "onInput" | "value" | "className"
>;

interface SelectProps extends NativeSelectProps {
  ariaLabel: string;
  options: SelectOption[];
  value: string;
  onChange: (value: string) => void;
  size?: "sm" | "md";
  /** Optional leading element rendered before the native control (e.g. icon). */
  leading?: ComponentChildren;
}

const SIZE_CLASS = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-3 py-1.5 text-sm",
} as const;

export function Select({
  ariaLabel,
  options,
  value,
  onChange,
  size = "md",
  leading,
  class: extraClass = "",
  ...rest
}: SelectProps) {
  const composed = [
    "rounded-md border bg-[var(--bb-surface-data)] text-[var(--bb-data-fg-primary)]",
    "border-[var(--bb-data-border-strong)] hover:border-[var(--bb-data-fg-subtle)]",
    SIZE_CLASS[size],
    extraClass,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <label class="inline-flex items-center gap-2">
      {leading}
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange((event.currentTarget as HTMLSelectElement).value)}
        class={composed}
        {...rest}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export default Select;
