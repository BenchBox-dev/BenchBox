import path from "node:path";
import { docutilsSlug } from "../lib/docutils-slug.ts";

const DOCS_ROOT = path.resolve(process.cwd(), "..", "docs");

type MdNode = {
  type: string;
  value?: string;
  depth?: number;
  data?: { hProperties?: Record<string, string> };
  lang?: string | null;
  url?: string;
  children?: MdNode[];
};

function routeFor(file: string): string {
  const relative = path.relative(DOCS_ROOT, file).split(path.sep).join("/");
  const stem = relative.replace(/\.(md|rst)$/, "");
  return stem.startsWith("blog/") ? `/${stem}.html` : `/docs/${stem}.html`;
}

function rewrite(url: string, file: string): string {
  if (/^([a-z][a-z0-9+.-]*:|\/\/|#)/i.test(url)) return url;
  const [target, fragment] = url.split("#");
  const absolute = path.resolve(path.dirname(file), target);
  if (/\.md$/.test(target)) return routeFor(absolute) + (fragment ? `#${fragment}` : "");
  if (/\.(png|jpe?g|gif|svg|webp)$/i.test(target)) return `/_images/${path.basename(target)}`;
  return url;
}

function textOf(node: MdNode): string {
  return node.value ?? (node.children ?? []).map(textOf).join("");
}

function walk(node: MdNode, file: string): void {
  if (node.children) {
    node.children = node.children.filter((child) => !(child.type === "code" && /^\{[a-z-]+\}/.test(child.lang ?? "")));
    node.children.forEach((child) => walk(child, file));
  }
  if (node.type === "heading") node.data = { hProperties: { id: docutilsSlug(textOf(node)) } };
  if ((node.type === "link" || node.type === "image") && node.url) node.url = rewrite(node.url, file);
}

export function mystLite() {
  return (tree: MdNode, vfile: { path?: string }) => {
    if (vfile.path) walk(tree, vfile.path);
  };
}
