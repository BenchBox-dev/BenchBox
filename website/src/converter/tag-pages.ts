import { TAG_CATEGORIES } from "./tag-categories.ts";

export const TAGS_DIRECTORY = "_tags";

export type TaggedDocument = { path: string; tags: readonly string[] };

export type VirtualSource = { relative: string; raw: string };

const CATEGORY_TAG = /^[a-z0-9-]+$/;

export function displayTag(tag: string): string {
  return tag.replace(/\\n/g, "\n").replace(/^"+|"+$/g, "").trim().replace(/\s+/g, " ");
}

export function tagBasename(tag: string): string {
  return tag
    .replace(/[\s\W]+/g, "-")
    .toLowerCase()
    .replace(/^-+|-+$/g, "");
}

function compareCodepoints(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function groupByTag(documents: readonly TaggedDocument[]): Map<string, { name: string; paths: string[] }> {
  const groups = new Map<string, { name: string; paths: string[] }>();
  for (const document of documents) {
    for (const raw of document.tags) {
      const name = displayTag(raw);
      if (name === "") continue;
      const basename = tagBasename(name);
      if (basename === "") continue;
      const group = groups.get(basename) ?? { name, paths: [] };
      group.paths.push(document.path);
      groups.set(basename, group);
    }
  }
  for (const group of groups.values()) group.paths.sort(compareCodepoints);
  return groups;
}

function tagPage(name: string, basename: string, paths: readonly string[]): string {
  const lines = [`(sphx_tag_${basename})=`, `# Tagged with: ${name}`, "", "**Pages with this tag**", ""];
  for (const path of paths) lines.push(`- {doc}\`../${path.replace(/\.(md|rst)$/, "")}\``);
  lines.push("");
  return lines.join("\n");
}

function categoryPage(title: string, entries: readonly string[]): string {
  const lines = [`# ${title}`, ""];
  if (entries.length === 0) lines.push("*No tags in this category yet.*");
  else lines.push("```{toctree}", ":maxdepth: 1", "", ...entries, "```");
  lines.push("");
  return lines.join("\n");
}

function indexPage(): string {
  return [
    "(tagoverview)=",
    "",
    "# Browse by Tag",
    "",
    "Select a category to browse tags:",
    "",
    "```{toctree}",
    ":maxdepth: 2",
    "",
    ...TAG_CATEGORIES.map((category) => `${category.title} <cat-${category.slug}>`),
    "```",
    "",
  ].join("\n");
}

export function generateTagSources(documents: readonly TaggedDocument[]): VirtualSource[] {
  const groups = groupByTag(documents);
  if (groups.size === 0) return [];
  const sources: VirtualSource[] = [];
  for (const [basename, group] of [...groups.entries()].sort((a, b) => compareCodepoints(a[0], b[0]))) {
    sources.push({ relative: `${TAGS_DIRECTORY}/${basename}.md`, raw: tagPage(group.name, basename, group.paths) });
  }
  for (const category of TAG_CATEGORIES) {
    const entries = category.tags
      .filter((tag) => CATEGORY_TAG.test(tag) && groups.has(tag))
      .map((tag) => `${tag} (${groups.get(tag)?.paths.length ?? 0}) <${tag}>`);
    sources.push({ relative: `${TAGS_DIRECTORY}/cat-${category.slug}.md`, raw: categoryPage(category.title, entries) });
  }
  sources.push({ relative: `${TAGS_DIRECTORY}/tagsindex.md`, raw: indexPage() });
  return sources;
}

export function rstTags(raw: string): string[] {
  const block: string[] = [];
  let reading = false;
  for (const untrimmed of raw.split("\n")) {
    const line = untrimmed.trim();
    if (line.includes(".. tags::")) {
      reading = true;
      block.push(...(line.split(".. tags::")[1] ?? "").split(","));
    } else {
      if (reading && line === "" && !(block.length === 1 && block[0] === "")) break;
      if (reading) block.push(...line.split(","));
    }
  }
  return block.map(displayTag).filter(Boolean);
}
