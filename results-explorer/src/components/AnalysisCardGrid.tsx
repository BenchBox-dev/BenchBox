import type { ComponentChildren } from "preact";

export interface AnalysisCardProps {
  id: string;
  anchorId?: string;
  title: ComponentChildren;
  isOpen: boolean;
  onToggle: (open: boolean) => void;
  renderThumbnail: () => ComponentChildren;
  renderFull: () => ComponentChildren;
  fullHeaderExtra?: ComponentChildren;
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
  headingId: string;
  title?: ComponentChildren;
  headingLevel?: "h2" | "h3";
  count?: ComponentChildren;
  description?: ComponentChildren;
  testId?: string;
  children: ComponentChildren;
}

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
