import { h, type ComponentChildren, type JSX } from "preact";

export type PanelTone = "data" | "muted" | "elevated" | "hero" | "hero-muted";

interface PanelProps {
  tone?: PanelTone;
  /** Pads content. Set to false for tables / charts that manage their own padding. */
  padded?: boolean;
  /** HTML tag to render as (default `section`). */
  as?: keyof JSX.IntrinsicElements;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  role?: JSX.AriaRole;
  class?: string;
  children: ComponentChildren;
}

const TONE_CLASS: Record<PanelTone, string> = {
  data: "panel",
  muted: "panel-muted",
  elevated: "panel-elevated",
  hero: "surface-hero rounded-lg",
  "hero-muted": "surface-hero-muted rounded-lg",
};

export function Panel({
  tone = "data",
  padded = true,
  as = "section",
  ariaLabel,
  ariaLabelledBy,
  role,
  class: extraClass = "",
  children,
}: PanelProps) {
  const composed = [TONE_CLASS[tone], padded ? "p-6" : "", extraClass].filter(Boolean).join(" ");
  const surfaceAttr = tone === "hero" || tone === "hero-muted" ? "hero" : "data";
  return h(
    as,
    {
      class: composed,
      "data-surface": surfaceAttr,
      role,
      "aria-label": ariaLabel,
      "aria-labelledby": ariaLabelledBy,
    },
    children,
  );
}

export interface DataCardProps {
  title?: ComponentChildren;
  description?: ComponentChildren;
  actions?: ComponentChildren;
  /** When `true` (default), wraps in a Panel; when `false` returns content as-is. */
  withPanel?: boolean;
  tone?: PanelTone;
  class?: string;
  children: ComponentChildren;
}

export function DataCard({
  title,
  description,
  actions,
  withPanel = true,
  tone = "data",
  class: extraClass = "",
  children,
}: DataCardProps) {
  const body = (
    <div class="flex flex-col gap-4">
      {(title || description || actions) && (
        <header class="flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && (
              <h2 class="text-lg font-semibold text-[var(--bb-data-fg-primary)]">{title}</h2>
            )}
            {description && (
              <p class="text-sm text-[var(--bb-data-fg-muted)]">{description}</p>
            )}
          </div>
          {actions && <div class="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div>{children}</div>
    </div>
  );
  if (!withPanel) return body;
  return (
    <Panel tone={tone} class={extraClass}>
      {body}
    </Panel>
  );
}

export default Panel;
