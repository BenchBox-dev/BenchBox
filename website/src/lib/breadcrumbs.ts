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

export function pathAncestors(pathname: string, indexTitles: ReadonlyMap<string, string>): Crumb[] {
  const segments = pathname.replace(/^\/docs\//, "").split("/").slice(0, -1);
  const crumbs: Crumb[] = [];
  for (let depth = 1; depth <= segments.length; depth += 1) {
    const directory = segments.slice(0, depth).join("/");
    const label = indexTitles.get(directory);
    if (label !== undefined) crumbs.push({ label, href: `/docs/${directory}/index.html` });
  }
  return crumbs;
}

export function docsTrail(
  sidebar: readonly TrailEntry[],
  title: string,
  pathname: string,
  indexTitles: ReadonlyMap<string, string> = new Map(),
): Crumb[] {
  if (pathname === "/docs" || pathname === "/docs/" || pathname === "/docs/index.html") return [];
  const groups = ancestorsOf(sidebar);
  const crumbs: Crumb[] = [DOCS_ROOT];
  if (groups === undefined) {
    const own = pathname.endsWith("/index.html") ? pathname : undefined;
    crumbs.push(...pathAncestors(pathname, indexTitles).filter((crumb) => crumb.href !== own));
    crumbs.push({ label: title });
    return crumbs;
  }
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
