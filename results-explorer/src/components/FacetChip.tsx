import type { ComponentChildren } from "preact";

interface FacetChipProps {
  selected: boolean;
  onToggle: () => void;
  children: ComponentChildren;
  count?: number;
  disabled?: boolean;
  title?: string;
}

export function FacetChip({ selected, onToggle, children, count, disabled, title }: FacetChipProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={selected}
      aria-disabled={disabled || undefined}
      disabled={disabled}
      title={title}
      onClick={() => !disabled && onToggle()}
      class={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors ${
        selected
          ? "border-[var(--bb-accent-hover)] bg-[var(--bb-tone-info-bg)] text-[var(--bb-tone-info-fg)]"
          : "border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] text-[var(--bb-data-fg-muted)] hover:border-[var(--bb-data-fg-subtle)] hover:text-[var(--bb-data-fg-primary)]"
      } ${disabled ? "opacity-60 cursor-not-allowed" : ""}`}
    >
      <span>{children}</span>
      {typeof count === "number" ? <span class="text-[10px] opacity-80">{count}</span> : null}
    </button>
  );
}

export default FacetChip;
