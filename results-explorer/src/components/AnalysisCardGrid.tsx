import type { ComponentChildren } from "preact";

/**
 * The expandable card shell shared by every "More views" / "Analysis" grid
 * in the results explorer: a `<details>` that shows a thumbnail preview
 * while closed and the full view while open, spanning the full grid width
 * when open so the full chart has room to breathe.
 *
 * `id` drives the `summary-chart-preview-{id}` / `summary-chart-full-{id}`
 * testids and, by convention, the chart/card registry id. `anchorId` is the
 * DOM id used for deep links (`cardAnchors` on the benchmark page); pages
 * that do not support deep links can omit it.
 */
export interface AnalysisCardProps {
  id: string;
  anchorId?: string;
  title: ComponentChildren;
  isOpen: boolean;
  onToggle: (open: boolean) => void;
  /** Rendered inside the `<summary>` only while the card is closed. */
  renderThumbnail: () => ComponentChildren;
  /** Rendered inside the full-view panel only while the card is open. */
  renderFull: () => ComponentChildren;
  /** Extra controls above the full view, e.g. a palette toggle. Open-only. */
  fullHeaderExtra?: ComponentChildren;
  /** Rendered after the full view, e.g. an exclusion-count footnote. Open-only. */
  footer?: ComponentChildren;
}

export function AnalysisCard({
  id,
  anchorId,
  title,
  isOpen,
  onToggle,
  renderThumbnail,
  renderFull,
  fullHeaderExtra,
  footer,
}: AnalysisCardProps) {
  return (
    <details
      id={anchorId}
      class={`summary-chart-details scroll-mt-24 rounded-lg border border-[var(--bb-data-border)]
        bg-[var(--bb-surface-data)] ${isOpen ? "sm:col-span-2 xl:col-span-4" : ""}`}
      open={isOpen}
      onToggle={(event) => {
        onToggle((event.currentTarget as HTMLDetailsElement).open);
      }}
      data-testid={`summary-chart-preview-${id}`}
    >
      <summary
        class="cursor-pointer list-none p-4 outline-none focus-visible:ring-2
          focus-visible:ring-[var(--bb-focus-ring)] focus-visible:ring-inset"
      >
        {/* The preview exists to say what the card contains before it is
            opened. Once the full view is rendered below, keeping the
            thumbnail draws the same content twice, and only one of the two
            carries readable detail. */}
        <div class={`flex flex-col ${isOpen ? "" : "min-h-[13rem]"}`}>
          <div>
            <h3 class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">{title}</h3>
          </div>
          {!isOpen && renderThumbnail()}
          <span class="mt-auto pt-3 text-xs font-medium text-[var(--bb-accent)]">
            {isOpen ? "Close full chart" : "Open full chart ↗"}
          </span>
        </div>
      </summary>
      <div
        class="border-t border-[var(--bb-data-border)] p-4"
        data-testid={`summary-chart-full-${id}`}
        data-chart-container
      >
        {isOpen && (
          <>
            {fullHeaderExtra}
            {renderFull()}
            {footer}
          </>
        )}
      </div>
    </details>
  );
}

export interface AnalysisCardGridProps {
  /** DOM id for the heading, referenced by the section's `aria-labelledby`. */
  headingId: string;
  title?: ComponentChildren;
  headingLevel?: "h2" | "h3";
  /** Right-aligned count/status text next to the title, e.g. "4 additional analyses". */
  count?: ComponentChildren;
  description?: ComponentChildren;
  testId?: string;
  children: ComponentChildren;
}

/** The "More views" / "Analysis" section header plus the card grid itself. */
export function AnalysisCardGrid({
  headingId,
  title = "More views",
  headingLevel = "h2",
  count,
  description,
  testId = "summary-more-views",
  children,
}: AnalysisCardGridProps) {
  const Heading = headingLevel;
  return (
    <section class="card" aria-labelledby={headingId} data-testid={testId}>
      <div class="mb-4 flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-[var(--bb-data-border)] pb-4">
        <Heading id={headingId} class="text-lg font-semibold text-[var(--bb-data-fg-primary)]">
          {title}
        </Heading>
        {count !== undefined && <p class="ml-auto text-sm font-medium text-[var(--bb-accent)]">{count}</p>}
        {description !== undefined && <p class="text-sm text-[var(--bb-data-fg-muted)]">{description}</p>}
      </div>
      <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{children}</div>
    </section>
  );
}
