interface Crumb {
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  crumbs: Crumb[];
}

export function Breadcrumb({ crumbs }: BreadcrumbProps) {
  return (
    <nav class="flex items-center gap-1 text-sm text-[var(--bb-data-fg-muted)]" aria-label="Breadcrumb">
      {crumbs.map((crumb, i) => (
        <span key={crumb.label} class="flex items-center gap-1">
          {i > 0 && <span class="text-[var(--bb-data-fg-subtle)]">/</span>}
          {crumb.href ? (
            <a href={crumb.href} class="no-underline hover:text-[var(--bb-data-fg-primary)]">
              {crumb.label}
            </a>
          ) : (
            <span class="font-medium text-[var(--bb-data-fg-primary)]">{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
