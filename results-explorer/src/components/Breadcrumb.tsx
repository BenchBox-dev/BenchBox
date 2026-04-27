interface Crumb {
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  crumbs: Crumb[];
}

export function Breadcrumb({ crumbs }: BreadcrumbProps) {
  return (
    <nav class="flex items-center gap-1 text-sm text-gray-500" aria-label="Breadcrumb">
      {crumbs.map((crumb, i) => (
        <span key={crumb.label} class="flex items-center gap-1">
          {i > 0 && <span class="text-gray-400">/</span>}
          {crumb.href ? (
            <a href={crumb.href} class="hover:text-gray-700 no-underline">
              {crumb.label}
            </a>
          ) : (
            <span class="font-medium text-gray-900">{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
