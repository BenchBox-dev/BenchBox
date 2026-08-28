import type { ComponentChildren } from "preact";

interface ErrorStateProps {
  title: ComponentChildren;
  /** Short description; rendered below the title. */
  description?: ComponentChildren;
  /** Optional pre-formatted detail block (e.g. server message, exception). */
  detail?: string;
  action?: ComponentChildren;
  class?: string;
}

export function ErrorState({ title, description, detail, action, class: extraClass = "" }: ErrorStateProps) {
  return (
    <div role="alert" class={`flex flex-col gap-3 rounded-lg p-6 tone-danger ${extraClass}`}>
      <div class="flex flex-col gap-1">
        <h3 class="text-base font-semibold">{title}</h3>
        {description ? <p class="text-sm">{description}</p> : null}
      </div>
      {detail ? (
        <pre class="overflow-x-auto rounded panel-muted px-3 py-2 text-xs text-[var(--bb-data-fg-primary)]">{detail}</pre>
      ) : null}
      {action ? <div>{action}</div> : null}
    </div>
  );
}

export default ErrorState;
