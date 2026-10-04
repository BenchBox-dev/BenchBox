import { existsSync, readdirSync } from "node:fs";
import path from "node:path";

function firstFile(siteDir, directory, pattern) {
  const full = path.join(siteDir, directory);
  const names = existsSync(full) ? readdirSync(full).filter((name) => pattern.test(name)).sort() : [];
  if (names.length === 0) throw new Error(`no built page matches ${pattern} under ${full}`);
  return `/${directory}/${names[0]}`.replace(/\/+/g, "/");
}

export const PAGE_TEMPLATES = {
  "404.astro": () => ({ name: "404", route: "/no-such-page-for-parity.html", status: 404 }),
  "blog.astro": () => ({ name: "all posts", route: "/blog.html" }),
  "blog/[...slug].astro": () => ({ name: "blog post", route: "/blog/2026-05-18-v0-3-0-release-overview.html" }),
  "blog/[year].astro": (siteDir) => ({ name: "blog year", route: firstFile(siteDir, "blog", /^\d{4}\.html$/) }),
  "blog/archive.astro": () => ({ name: "blog archive", route: "/blog/archive.html" }),
  "blog/atom.xml.ts": null,
  "blog/author.astro": () => ({ name: "author index", route: "/blog/author.html" }),
  "blog/author/[author].astro": (siteDir) => ({ name: "author page", route: firstFile(siteDir, "blog/author", /\.html$/) }),
  "blog/drafts.astro": () => ({ name: "drafts", route: "/blog/drafts.html" }),
  "blog/inde[x].astro": () => ({ name: "blog index", route: "/blog/" }),
  "blog/tag.astro": () => ({ name: "tag index", route: "/blog/tag.html" }),
  "blog/tag/[tag].astro": (siteDir) => ({ name: "tag page", route: firstFile(siteDir, "blog/tag", /\.html$/) }),
  "docs/[...dir]/inde[x].astro": () => ({ name: "docs directory index", route: "/docs/usage/" }),
  "docs/blog.astro": () => ({ name: "redirect page", route: "/docs/blog.html", stripRefresh: true }),
  "docs/genindex.astro": () => ({ name: "redirect page genindex", route: "/docs/genindex.html", stripRefresh: true }),
  "docs/search.astro": () => ({ name: "redirect page search", route: "/docs/search.html", stripRefresh: true }),
  "index.astro": () => ({ name: "landing", route: "/" }),
  "prompts/inde[x].astro": () => ({ name: "prompts", route: "/prompts/" }),
};

export const CONTENT_TEMPLATES = [
  { name: "docs page", route: "/docs/usage/getting-started.html" },
  { name: "docs index", route: "/docs/" },
  { name: "generated query page", route: "/docs/benchmarks/queries/tpch/q1.html" },
  { name: "Explorer", route: "/results/", settle: "main tbody tr" },
];

export function pageSources(pagesDir) {
  const found = [];
  const walk = (directory, prefix) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (entry.isDirectory()) walk(path.join(directory, entry.name), `${prefix}${entry.name}/`);
      else found.push(`${prefix}${entry.name}`);
    }
  };
  walk(pagesDir, "");
  return found.sort();
}

export function templateRoutes(siteDir, pagesDir) {
  const sources = pageSources(pagesDir);
  const unmapped = sources.filter((source) => !Object.hasOwn(PAGE_TEMPLATES, source));
  if (unmapped.length > 0) throw new Error(`page templates without an axe route: ${unmapped.join(", ")}`);
  const stale = Object.keys(PAGE_TEMPLATES).filter((source) => !sources.includes(source));
  if (stale.length > 0) throw new Error(`axe routes for page templates that no longer exist: ${stale.join(", ")}`);
  const routes = sources.map((source) => PAGE_TEMPLATES[source]?.(siteDir)).filter(Boolean);
  return [...routes, ...CONTENT_TEMPLATES];
}
