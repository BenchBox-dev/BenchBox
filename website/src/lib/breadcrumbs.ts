export type Crumb = { label: string; href?: string };

export type TrailLink = { type: "link"; label: string; href: string; isCurrent: boolean };

export type TrailGroup = { type: "group"; label: string; entries: TrailEntry[] };

export type TrailEntry = TrailLink | TrailGroup;

export const DOCS_ROOT: Crumb = { label: "Docs", href: "/docs/" };

function ancestorsOf(entries: readonly TrailEntry[], found: TrailGroup[] = []): TrailGroup[] | undefined {
  for (const entry of entries) {
    if (entry.type === "link" && entry.isCurrent) return found;
    if (entry.type === "group") {
      const inner = ancestorsOf(entry.entries, [...found, entry]);
      if (inner) return inner;
    }
  }
  return undefined;
}

function selfLink(group: TrailGroup): TrailLink | undefined {
  const first = group.entries[0];
  return first?.type === "link" && first.label === group.label ? first : undefined;
}

export function docsTrail(sidebar: readonly TrailEntry[], title: string, pathname: string): Crumb[] {
  if (pathname === "/docs" || pathname === "/docs/" || pathname === "/docs/index.html") return [];
  const groups = ancestorsOf(sidebar) ?? [];
  const crumbs: Crumb[] = [DOCS_ROOT];
  for (const group of groups) {
    const link = selfLink(group);
    if (link?.isCurrent) continue;
    crumbs.push(link ? { label: group.label, href: link.href } : { label: group.label });
  }
  crumbs.push({ label: title });
  return crumbs;
}

export function blogTrail(title: string, isIndex: boolean): Crumb[] {
  if (isIndex) return [];
  return [{ label: "Blog", href: "/blog/" }, { label: title }];
}
