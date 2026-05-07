import type { ComponentChildren } from "preact";

interface EmptyStateProps {
  title: ComponentChildren;
  description?: ComponentChildren;
  action?: ComponentChildren;
  /** When true, render in compact form (single line + action). */
  compact?: boolean;
  class?: string;
}

export function EmptyState({ title, description, action, compact = false, class: extraClass = "" }: EmptyStateProps) {
  if (compact) {
    return (
      <div class={`flex items-center justify-between gap-3 panel-muted px-4 py-3 ${extraClass}`} role="status">
        <div class="text-sm text-[var(--bb-data-fg-muted)]">
          <span class="font-medium text-[var(--bb-data-fg-primary)]">{title}</span>
          {description ? <span class="ml-2">{description}</span> : null}
        </div>
        {action}
      </div>
    );
  }
  return (
    <div class={`flex flex-col items-center gap-2 panel-muted p-8 text-center ${extraClass}`} role="status">
      <h3 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">{title}</h3>
      {description ? <p class="text-sm text-[var(--bb-data-fg-muted)] max-w-prose">{description}</p> : null}
      {action ? <div class="mt-2">{action}</div> : null}
    </div>
  );
}

export default EmptyState;
