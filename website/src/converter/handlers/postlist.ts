import { readFileSync } from "node:fs";
import path from "node:path";
import type { Link, Paragraph, PhrasingContent, Root, RootContent, Text } from "mdast";
import { ConverterError } from "../errors.ts";
import { parseFrontMatter, parseMarkdown } from "../parse.ts";
import { preprocess } from "../preprocess.ts";
import type { ConvertContext, DirectiveHandler } from "../types.ts";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const ROLE_SUFFIX = /\{[A-Za-z0-9_:.+-]+\}$/;
const DEFAULT_DATE_FORMAT = "%b %d, %Y";
const DEFAULT_ENTRY_FORMAT = "{date} - {title}";

type Post = { path: string; line: number; date: Date; title: string; route: string; excerpt: PhrasingContent[] };

function descending(a: string, b: string): number {
  return a < b ? 1 : a > b ? -1 : 0;
}

function parseDate(value: unknown, file: string, line: number): Date {
  const text = value instanceof Date ? value.toISOString().slice(0, 10) : String(value ?? "");
  const iso = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return new Date(Date.UTC(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3])));
  const named = text.match(/^([A-Za-z]{3,9})\.? (\d{1,2}), (\d{4})$/);
  const month = named ? MONTHS.findIndex((name) => name.toLowerCase().startsWith(named[1].toLowerCase().slice(0, 3))) : -1;
  if (!named || month < 0) throw new ConverterError(file, line, `blog post date ${JSON.stringify(text)} is not a recognised date`);
  return new Date(Date.UTC(Number(named[3]), month, Number(named[2])));
}

function formatDate(date: Date, format: string, at: { file: string; line: number }): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return format.replace(/%(.)/g, (_match, code: string) => {
    switch (code) {
      case "B":
        return MONTHS[date.getUTCMonth()];
      case "b":
        return MONTHS[date.getUTCMonth()].slice(0, 3);
      case "d":
        return pad(date.getUTCDate());
      case "m":
        return pad(date.getUTCMonth() + 1);
      case "Y":
        return String(date.getUTCFullYear());
      case "y":
        return pad(date.getUTCFullYear() % 100);
      case "%":
        return "%";
      default:
        throw new ConverterError(at.file, at.line, `postlist date format %${code} is not supported`);
    }
  });
}

function inlineOf(children: readonly PhrasingContent[]): PhrasingContent[] {
  const out: PhrasingContent[] = [];
  children.forEach((child, index) => {
    const next = children[index + 1];
    switch (child.type) {
      case "text": {
        const value = next?.type === "inlineCode" ? child.value.replace(ROLE_SUFFIX, "") : child.value;
        if (value !== "") out.push({ type: "text", value: value.replace(/\s*\n\s*/g, " ") });
        break;
      }
      case "inlineCode":
        out.push(child);
        break;
      case "break":
        out.push({ type: "text", value: " " });
        break;
      case "emphasis":
      case "strong":
        out.push({ ...child, children: inlineOf(child.children) });
        break;
      case "link":
      case "linkReference":
        out.push(...inlineOf(child.children));
        break;
      default:
        break;
    }
  });
  return out;
}

function firstParagraph(nodes: readonly RootContent[]): Paragraph | undefined {
  for (const node of nodes) {
    if (node.type === "paragraph" && inlineOf(node.children).length > 0) return node;
    if (node.type === "blockquote" || node.type === "list" || node.type === "listItem") {
      const found = firstParagraph(node.children);
      if (found) return found;
    }
  }
  return undefined;
}

function loadPost(context: ConvertContext, relative: string): Post | undefined {
  const source = readFileSync(path.join(context.docsRoot, relative), "utf-8");
  const tree: Root = parseMarkdown(preprocess(source));
  const front = parseFrontMatter(relative, tree);
  if (front.data.blogpost !== true) return undefined;
  const line = front.keyLines.get("date") ?? front.line;
  if (front.data.date === undefined) throw new ConverterError(relative, front.line, "blog post has no date");
  const resolved = context.resolveDoc(path.posix.relative("blog", relative), { file: context.file, line: 1 }, "postlist");
  const paragraph = firstParagraph(tree.children);
  return {
    path: relative,
    line,
    date: parseDate(front.data.date, relative, line),
    title: resolved.title,
    route: resolved.route,
    excerpt: paragraph ? inlineOf(paragraph.children) : [],
  };
}

function entryNodes(format: string, post: Post, dateFormat: string, at: { file: string; line: number }): PhrasingContent[] {
  const nodes: PhrasingContent[] = [];
  for (const part of format.split(/(\{[a-z]+\})/)) {
    if (part === "{date}") nodes.push({ type: "text", value: formatDate(post.date, dateFormat, at) });
    else if (part === "{title}") nodes.push({ type: "link", url: post.route, children: [{ type: "text", value: post.title }] } satisfies Link);
    else if (/^\{[a-z]+\}$/.test(part)) throw new ConverterError(at.file, at.line, `postlist format field ${part} is not supported`);
    else if (part !== "") nodes.push({ type: "text", value: part } satisfies Text);
  }
  return nodes;
}

export const postlistDirective: DirectiveHandler = {
  kind: "directive",
  names: ["postlist"],
  options: ["date", "format", "list-style", "excerpts"],
  argument: "none",
  handle(call, context) {
    const listStyle = call.options["list-style"] ?? "none";
    if (listStyle !== "none") throw new ConverterError(call.at.file, call.at.line, `postlist list-style ${JSON.stringify(listStyle)} is not supported`);
    if (call.body.trim() !== "") throw new ConverterError(call.at.file, call.at.line, "postlist does not take content");
    const dateFormat = call.options.date || DEFAULT_DATE_FORMAT;
    const format = call.options.format || DEFAULT_ENTRY_FORMAT;
    const excerpts = "excerpts" in call.options;
    const posts = context.index
      .paths()
      .filter((candidate) => {
        const info = context.index.get(candidate);
        return info?.collection === "blog" && candidate !== context.file;
      })
      .map((candidate) => loadPost(context, candidate))
      .filter((post): post is Post => post !== undefined)
      .sort((a, b) => b.date.getTime() - a.date.getTime() || descending(a.title, b.title) || descending(a.path, b.path));
    const out: RootContent[] = [];
    for (const post of posts) {
      out.push({ type: "paragraph", children: entryNodes(format, post, dateFormat, call.at) });
      if (excerpts && post.excerpt.length > 0) out.push({ type: "paragraph", children: post.excerpt });
    }
    return out;
  },
};
