import { smarten } from "../lib/smartypants.ts";
import type { DocsIndex } from "./docs-index.ts";
import type { ToctreeEntry } from "./model.ts";

export type SidebarItem = { label: string; link: string; items?: SidebarItem[] };

export type SidebarGroup = { label: string | null; items: SidebarItem[] };

export type SidebarManifest = { groups: SidebarGroup[]; order: Record<string, number> };

export const ROOT_DOCUMENT = "index.md";

type Walk = { index: DocsIndex; order: Map<string, number> };

function claim(walk: Walk, path: string): void {
  if (!walk.order.has(path)) walk.order.set(path, walk.order.size);
}

function itemFor(walk: Walk, entry: ToctreeEntry, trail: string[]): SidebarItem | undefined {
  if (entry.kind === "self") return undefined;
  if (entry.kind === "url") return { label: smarten(entry.title), link: entry.url };
  const info = walk.index.get(entry.path);
  if (!info) return undefined;
  claim(walk, info.path);
  const item: SidebarItem = { label: entry.title === undefined ? info.title : smarten(entry.title), link: info.route };
  if (trail.includes(info.path)) return item;
  const children = info.toctrees
    .flatMap((block) => block.entries)
    .map((child) => itemFor(walk, child, [...trail, info.path]))
    .filter((child): child is SidebarItem => child !== undefined);
  if (children.length > 0) item.items = children;
  return item;
}

export function buildSidebar(index: DocsIndex): SidebarManifest {
  const walk: Walk = { index, order: new Map() };
  const root = index.get(ROOT_DOCUMENT);
  const groups: SidebarGroup[] = [];
  if (root) {
    claim(walk, root.path);
    for (const block of root.toctrees) {
      const items = block.entries.map((entry) => itemFor(walk, entry, [root.path])).filter((item): item is SidebarItem => item !== undefined);
      groups.push({ label: block.caption === undefined ? null : smarten(block.caption), items });
    }
  }
  const order: Record<string, number> = {};
  for (const [path, position] of [...walk.order.entries()].sort((a, b) => a[1] - b[1])) order[path] = position;
  return { groups, order };
}

export type StarlightSidebarEntry = { label: string; link: string } | { label: string; collapsed: boolean; items: StarlightSidebarEntry[] };

function toStarlight(item: SidebarItem): StarlightSidebarEntry {
  if (!item.items) return { label: item.label, link: item.link };
  return { label: item.label, collapsed: true, items: [{ label: item.label, link: item.link }, ...item.items.map(toStarlight)] };
}

export function toStarlightSidebar(manifest: SidebarManifest): StarlightSidebarEntry[] {
  return manifest.groups.map((group, position) => ({
    label: group.label ?? `Section ${position + 1}`,
    collapsed: false,
    items: group.items.map(toStarlight),
  }));
}
