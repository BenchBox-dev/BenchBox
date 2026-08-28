import type { ComponentChildren } from "preact";

export type StatusTone = "info" | "success" | "warning" | "danger" | "neutral";
export type StatusRole =
  | "trust"
  | "funding"
  | "validation"
  | "visibility"
  | "computed"
  | "comparison"
  | "ranking"
  | "generic";

interface StatusBadgeProps {
  /** Semantic role; rendered into data-role for testing and overrides. */
  role?: StatusRole;
  tone?: StatusTone;
  title?: string;
  /** Optional leading icon / dot. */
  leading?: ComponentChildren;
  class?: string;
  children: ComponentChildren;
}

const TONE_CLASS: Record<StatusTone, string> = {
  info: "tone-info",
  success: "tone-success",
  warning: "tone-warning",
  danger: "tone-danger",
  neutral: "tone-neutral",
};

export function StatusBadge({
  role = "generic",
  tone = "neutral",
  title,
  leading,
  class: extraClass = "",
  children,
}: StatusBadgeProps) {
  return (
    <span
      class={`badge ${TONE_CLASS[tone]} ${extraClass}`}
      data-role={role}
      data-tone={tone}
      title={title}
    >
      {leading ? <span class="mr-1">{leading}</span> : null}
      {children}
    </span>
  );
}

export default StatusBadge;
