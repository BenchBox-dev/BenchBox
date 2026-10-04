import { SITE_ORIGIN } from "./header-links.ts";

export const SITE_NAME = "BenchBox";
export const SITE_DESCRIPTION = "BenchBox makes database benchmarking easy: CLI, Python library, or MCP for AI assistants.";
export const SOCIAL_IMAGE = `${SITE_ORIGIN}/hero.png`;
export const SOCIAL_IMAGE_ALT = "BenchBox - Database Benchmarking Toolkit";

export type MetaTag = { tag: "meta" | "link"; attrs: Record<string, string> };

export type PageMetaInput = {
  title: string;
  description?: string;
  pathname: string;
  type?: "website" | "article";
};

export function canonicalPath(pathname: string): string {
  if (pathname === "/" || pathname === "/index.html") return "/";
  if (pathname === "/results/") return pathname;
  if (pathname.endsWith(".html")) return pathname;
  if (pathname.endsWith("/")) return `${pathname}index.html`;
  return `${pathname}.html`;
}

export function canonicalUrl(pathname: string): string {
  return `${SITE_ORIGIN}${canonicalPath(pathname)}`;
}

export function sitemapPathForFile(file: string): string {
  if (file === "index.html") return "/";
  if (file === "results/index.html") return "/results/";
  return `/${file}`;
}

export function renderSitemap(paths: readonly string[]): string {
  const urls = [...paths].sort().map((entry) => `  <url><loc>${escapeXml(`${SITE_ORIGIN}${entry}`)}</loc></url>`);
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join("\n")}\n</urlset>\n`;
}

export function renderRobots(): string {
  return `User-agent: *\nAllow: /\n\nSitemap: ${SITE_ORIGIN}/sitemap.xml\n`;
}

export function pageMeta(input: PageMetaInput): MetaTag[] {
  const url = canonicalUrl(input.pathname);
  const description = input.description?.trim() || SITE_DESCRIPTION;
  const meta = (key: "name" | "property", name: string, content: string): MetaTag => ({ tag: "meta", attrs: { [key]: name, content } });
  return [
    { tag: "link", attrs: { rel: "canonical", href: url } },
    meta("name", "description", description),
    meta("property", "og:site_name", SITE_NAME),
    meta("property", "og:type", input.type ?? "website"),
    meta("property", "og:title", input.title),
    meta("property", "og:description", description),
    meta("property", "og:url", url),
    meta("property", "og:image", SOCIAL_IMAGE),
    meta("property", "og:image:alt", SOCIAL_IMAGE_ALT),
    meta("name", "twitter:card", "summary_large_image"),
    meta("name", "twitter:title", input.title),
    meta("name", "twitter:description", description),
    meta("name", "twitter:image", SOCIAL_IMAGE),
  ];
}

function escapeXml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
