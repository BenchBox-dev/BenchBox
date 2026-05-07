import type { ComponentChildren, JSX } from "preact";

// Preact convention: callers pass `class` (not `className`).
type NativeInputProps = Omit<
  JSX.IntrinsicElements["input"],
  "type" | "onChange" | "onInput" | "size" | "checked" | "className"
>;

interface CheckboxProps extends NativeInputProps {
  label: ComponentChildren;
  /** Description rendered below the label, also linked via aria-describedby. */
  description?: ComponentChildren;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

let idCounter = 0;
function nextId(prefix: string) {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

export function Checkbox({
  label,
  description,
  checked,
  onChange,
  disabled,
  class: extraClass = "",
  id,
  ...rest
}: CheckboxProps) {
  const inputId = id || nextId("bb-checkbox");
  const descId = description ? `${inputId}-desc` : undefined;
  return (
    <label class={`inline-flex items-start gap-2 text-sm ${extraClass}`}>
      <input
        id={inputId}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-describedby={descId}
        onChange={(event) => {
          if (disabled) return;
          onChange((event.currentTarget as HTMLInputElement).checked);
        }}
        class="mt-0.5 h-4 w-4 rounded border-[var(--bb-data-border-strong)] accent-[var(--bb-accent-hover)] disabled:opacity-60"
        {...rest}
      />
      <span class="flex flex-col">
        <span class="text-[var(--bb-data-fg-primary)]">{label}</span>
        {description ? (
          <span id={descId} class="text-xs text-[var(--bb-data-fg-muted)]">
            {description}
          </span>
        ) : null}
      </span>
    </label>
  );
}

export default Checkbox;
