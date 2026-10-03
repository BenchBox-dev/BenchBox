import { readFileSync } from "node:fs";
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
  align?: (string | null)[];
  children?: MdNode[];
};

type Parse = (source: string) => MdNode;

const DROPPED_DIRECTIVES = new Set(["tags", "toctree"]);

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

function titleOf(file: string): string {
  const match = readFileSync(file, "utf-8").match(/^# (.+)$/m);
  if (!match) throw new Error(`myst-lite: no H1 title in ${file}`);
  return match[1].trim();
}

function docLink(content: string, file: string): MdNode {
  const labelled = content.match(/^(.*\S)\s*<([^<>]+)>$/s);
  const target = (labelled ? labelled[2] : content).trim();
  const base = target.startsWith("/") ? DOCS_ROOT : path.dirname(file);
  const absolute = path.resolve(base, target.replace(/^\//, "").replace(/\.md$/, "") + ".md");
  return {
    type: "link",
    url: routeFor(absolute),
    children: [{ type: "text", value: labelled ? labelled[1].trim() : titleOf(absolute) }],
  };
}

function expandRoles(children: MdNode[], file: string): MdNode[] {
  const out: MdNode[] = [];
  for (let i = 0; i < children.length; i += 1) {
    const node = children[i];
    const next = children[i + 1];
    const role = node.type === "text" ? node.value?.match(/\{([a-z:-]+)\}$/) : null;
    if (!role || next?.type !== "inlineCode") {
      out.push(node);
      continue;
    }
    if (role[1] !== "doc") throw new Error(`myst-lite: unsupported role {${role[1]}} in ${file}`);
    const before = (node.value ?? "").slice(0, role.index);
    if (before) out.push({ type: "text", value: before });
    out.push(docLink(next.value ?? "", file));
    i += 1;
  }
  return out;
}

function parseListTable(body: string, parse: Parse, file: string): MdNode {
  const lines = body.split("\n");
  const options = new Map<string, string>();
  let index = 0;
  for (; index < lines.length && /^:[a-z-]+:/.test(lines[index]); index += 1) {
    const option = lines[index].match(/^:([a-z-]+):\s*(.*)$/);
    if (option) options.set(option[1], option[2].trim());
  }
  for (const key of options.keys()) {
    if (key !== "header-rows" && key !== "widths") throw new Error(`myst-lite: unsupported list-table option :${key}: in ${file}`);
  }
  const headerRows = Number(options.get("header-rows") ?? "0");
  if (headerRows !== 0 && headerRows !== 1) throw new Error(`myst-lite: unsupported :header-rows: ${headerRows} in ${file}`);
  const rows: string[][] = [];
  for (const line of lines.slice(index)) {
    if (!line.trim()) continue;
    const row = line.match(/^\* - (.*)$/);
    const cell = line.match(/^ {2}- (.*)$/);
    if (row) rows.push([row[1]]);
    else if (cell && rows.length) rows[rows.length - 1].push(cell[1]);
    else throw new Error(`myst-lite: unsupported list-table line "${line}" in ${file}`);
  }
  if (!rows.length || rows.some((row) => row.length !== rows[0].length)) {
    throw new Error(`myst-lite: list-table rows are empty or ragged in ${file}`);
  }
  const tableRows = rows.map((row) => ({
    type: "tableRow",
    children: row.map((cell) => ({ type: "tableCell", children: parse(cell).children?.[0]?.children ?? [] })),
  }));
  return { type: "table", align: rows[0].map(() => null), children: tableRows };
}

function transformDirectives(children: MdNode[], parse: Parse, file: string): MdNode[] {
  const out: MdNode[] = [];
  for (const child of children) {
    const name = child.type === "code" ? (child.lang ?? "").match(/^\{([a-z-]+)\}/)?.[1] : undefined;
    if (!name) out.push(child);
    else if (name === "list-table") out.push(parseListTable(child.value ?? "", parse, file));
    else if (!DROPPED_DIRECTIVES.has(name)) throw new Error(`myst-lite: unsupported directive {${name}} in ${file}`);
  }
  return out;
}

function walk(node: MdNode, file: string, parse: Parse): void {
  if (node.children) {
    node.children = expandRoles(transformDirectives(node.children, parse, file), file);
    node.children.forEach((child) => walk(child, file, parse));
  }
  if (node.type === "heading") node.data = { hProperties: { id: docutilsSlug(textOf(node)) } };
  if ((node.type === "link" || node.type === "image") && node.url) node.url = rewrite(node.url, file);
}

export function mystLite(this: { parse: Parse }) {
  const parse = this.parse.bind(this);
  return (tree: unknown, vfile: { path?: string }) => {
    if (vfile.path) walk(tree as MdNode, vfile.path, parse);
  };
}
