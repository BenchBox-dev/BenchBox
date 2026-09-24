import type { ComponentChildren } from "preact";
import { Breadcrumb, type Crumb } from "@/components/Breadcrumb";

/** Shared type ramp so a page that builds its own hero still matches. */
export const PAGE_HEADER_CLASSES = {
  eyebrow: "text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-subtle)]",
  title: "text-3xl font-bold text-[var(--bb-data-fg-primary)]",
  subtitle: "max-w-3xl text-sm text-[var(--bb-data-fg-muted)]",
} as const;

interface PageHeaderProps {
  /** Breadcrumb trail. Omit on pages that are not below an index. */
  crumbs?: Crumb[];
  /** Short label above the title, e.g. the section a detail page belongs to. */
  eyebrow?: string;
  title: ComponentChildren;
  /** One line of prose saying what the page is for. */
  subtitle?: ComponentChildren;
  /** Counts and scope chips describing what is currently on the page. */
  meta?: ComponentChildren;
  /** Controls that change what the page shows: switchers, filters, views. */
  actions?: ComponentChildren;
}

/**
 * One header treatment for every explorer page.
 *
 * Each page previously built its own: different heading sizes, some in an
 * elevated panel and some not, breadcrumbs on two of five, controls sometimes
 * beside the title and sometimes below it. The shape here is fixed - trail,
 * eyebrow, title, subtitle, scope, controls - and pages choose which parts
 * they have rather than how they look.
 */
export function PageHeader({ crumbs, eyebrow, title, subtitle, meta, actions }: PageHeaderProps) {
  return (
    <header class="mb-6" data-testid="page-header">
      {crumbs && crumbs.length > 0 && <Breadcrumb crumbs={crumbs} />}
      <div class={`flex flex-wrap items-start justify-between gap-x-6 gap-y-3 ${crumbs ? "mt-5" : ""}`}>
        <div class="min-w-0">
          {eyebrow && <p class={PAGE_HEADER_CLASSES.eyebrow}>{eyebrow}</p>}
          <h1 class={`${PAGE_HEADER_CLASSES.title} ${eyebrow ? "mt-1" : ""}`}>{title}</h1>
          {subtitle && <p class={`mt-2 ${PAGE_HEADER_CLASSES.subtitle}`}>{subtitle}</p>}
          {meta && (
            <div
              class="mt-3 flex flex-wrap items-center gap-2 text-sm text-[var(--bb-data-fg-muted)]"
              data-testid="page-header-meta"
            >
              {meta}
            </div>
          )}
        </div>
        {actions && <div class="flex flex-wrap items-center gap-3">{actions}</div>}
      </div>
    </header>
  );
}
