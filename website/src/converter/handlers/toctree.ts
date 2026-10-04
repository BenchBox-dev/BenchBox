import type { List, ListItem, RootContent } from "mdast";
import { stemOf } from "../docs-index.ts";
import { UnknownConstructError, UnresolvedReferenceError } from "../errors.ts";
import type { DocInfo, TocNode, ToctreeBlock, ToctreeEntry } from "../model.ts";
import type { ConvertContext, DirectiveCall, DirectiveHandler } from "../types.ts";

const TITLED = /^([\s\S]+?)\s*<([^<>]*)>$/;
const URL_TARGET = /:\/\//;
const GLOB_CHARACTERS = /[*?[]/;
const FLAGS = ["hidden", "titlesonly", "includehidden", "reversed", "glob"];

type Item = { kind: "item"; title: string; url: string; children: Node[] };

type Pending = { kind: "toctree"; owner: DocInfo; block: ToctreeBlock };

type Node = Item | Pending;

type Resolve = { context: ConvertContext; titlesonly: boolean; includehidden: boolean };

function escapeClass(body: string): string {
  return body.replace(/\\/g, "\\\\");
}

function globToRegExp(pattern: string): RegExp {
  let source = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index];
    if (character === "*" && pattern[index + 1] === "*") {
      source += ".*";
      index += 1;
    } else if (character === "*") source += "[^/]*";
    else if (character === "?") source += "[^/]";
    else if (character === "[") {
      let close = index + 1;
      if (pattern[close] === "!") close += 1;
      if (pattern[close] === "]") close += 1;
      close = pattern.indexOf("]", close);
      if (close < 0) source += "\\[";
      else {
        const body = escapeClass(pattern.slice(index + 1, close));
        source += body.startsWith("!") ? `[^/${body.slice(1)}]` : body.startsWith("^") ? `[\\${body}]` : `[${body}]`;
        index = close;
      }
    } else source += character.replace(/[.+^${}()|\\\]]/g, "\\$&");
  }
  return new RegExp(`^${source}$`);
}

function docnameJoin(current: string, target: string): string {
  const segments = target.startsWith("/") ? target.slice(1).split("/") : [...current.split("/").slice(0, -1), ...target.split("/")];
  const resolved: string[] = [];
  for (const segment of segments) {
    if (segment === "..") resolved.pop();
    else if (segment !== "." && segment !== "") resolved.push(segment);
  }
  return resolved.join("/");
}

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function parseEntries(call: DirectiveCall, context: ConvertContext): ToctreeEntry[] {
  const glob = "glob" in call.options;
  const current = stemOf(context.file);
  const byDocname = new Map(context.index.paths().map((path) => [stemOf(path), path]));
  const available = new Set([...byDocname.keys()].filter((docname) => docname !== current));
  const entries: ToctreeEntry[] = [];
  call.body.split("\n").forEach((raw, offset) => {
    const text = raw.trim();
    if (text === "") return;
    const at = { file: context.file, line: call.bodyAt.line + offset };
    const titled = text.match(TITLED);
    const url = URL_TARGET.test(text);
    if (glob && GLOB_CHARACTERS.test(text) && !titled && !url) {
      const matcher = globToRegExp(docnameJoin(current, text));
      const matches = [...available].filter((docname) => matcher.test(docname)).sort(compare);
      if (matches.length === 0 && context.pass === "emit") throw new UnresolvedReferenceError(at.file, at.line, `toctree:${text}`, "glob matches no documents");
      for (const docname of matches) {
        available.delete(docname);
        entries.push({ kind: "doc", path: byDocname.get(docname) as string });
      }
      return;
    }
    const title = titled ? titled[1] : undefined;
    const target = titled ? titled[2] : text;
    if (target === "self") entries.push(title === undefined ? { kind: "self" } : { kind: "self", title });
    else if (url) entries.push({ kind: "url", url: target, title: title ?? target });
    else {
      const resolved = context.resolveDoc(target, at, "toctree");
      available.delete(stemOf(resolved.path));
      entries.push(title === undefined ? { kind: "doc", path: resolved.path } : { kind: "doc", path: resolved.path, title });
    }
  });
  return "reversed" in call.options ? entries.reverse() : entries;
}

function item(title: string, url: string): Item {
  return { kind: "item", title, url, children: [] };
}

function tocOf(info: DocInfo, nodes: readonly TocNode[]): Node[] {
  return nodes.map((node): Node =>
    node.kind === "toctree"
      ? { kind: "toctree", owner: info, block: info.toctrees[node.block] }
      : { kind: "item", title: node.title, url: node.anchor === "" ? info.route : `${info.route}#${node.anchor}`, children: tocOf(info, node.children) },
  );
}

function pendingUnder(nodes: readonly Node[]): Pending[] {
  return nodes.flatMap((node) => (node.kind === "toctree" ? [node] : pendingUnder(node.children)));
}

function resolvePending(nodes: readonly Node[], parents: readonly string[], options: Resolve): Node[] {
  return nodes.flatMap((node): Node[] => {
    if (node.kind === "item") return [{ ...node, children: resolvePending(node.children, parents, options) }];
    if (node.block.hidden && !options.includehidden) return [];
    return entriesOf(node.owner, node.block, parents, options);
  });
}

function entriesOf(owner: DocInfo, block: ToctreeBlock, parents: readonly string[], options: Resolve): Node[] {
  const out: Node[] = [];
  for (const entry of block.entries) {
    if (entry.kind === "url") out.push(item(entry.title, entry.url));
    else if (entry.kind === "self") out.push(item(entry.title ?? owner.title, owner.route));
    else if (!parents.includes(entry.path)) {
      const info = options.context.index.get(entry.path);
      if (!info) throw new UnresolvedReferenceError(block.at.file, block.at.line, `toctree:${entry.path}`, "is not a document");
      const toc = info.toc.length > 0 ? tocOf(info, info.toc) : [item(info.title, info.route)];
      const top = toc.filter((node): node is Item => node.kind === "item");
      if (entry.title !== undefined && toc.length === 1 && top.length === 1) top[0].title = entry.title;
      if (options.titlesonly) for (const node of top) node.children = pendingUnder(node.children);
      out.push(...resolvePending(toc, [info.path, ...parents], options));
    }
  }
  return out;
}

function toList(nodes: readonly Node[], level: number, maxdepth: number): List | undefined {
  const items = nodes.filter((node): node is Item => node.kind === "item");
  if (items.length === 0) return undefined;
  return {
    type: "list",
    ordered: false,
    spread: false,
    children: items.map((node): ListItem => {
      const row: ListItem = { type: "listItem", spread: false, children: [{ type: "paragraph", children: [{ type: "link", url: node.url, children: [{ type: "text", value: node.title }] }] }] };
      const nested = maxdepth > 0 && level >= maxdepth ? undefined : toList(node.children, level + 1, maxdepth);
      if (nested) row.children.push(nested);
      return row;
    }),
  };
}

function checkOptions(call: DirectiveCall): number | undefined {
  const fail = (option: string, detail: string): UnknownConstructError => new UnknownConstructError(call.at.file, call.at.line, `directive-option:toctree:${option}`, detail);
  for (const flag of FLAGS) if (flag in call.options && call.options[flag] !== "") throw fail(flag, `toctree :${flag}: is a flag and takes no value`);
  if ("caption" in call.options && call.options.caption.trim() === "") throw fail("caption", "toctree :caption: needs a value");
  if (call.options.maxdepth === undefined) return undefined;
  if (!/^-?\d+$/.test(call.options.maxdepth.trim())) throw fail("maxdepth", `toctree :maxdepth: must be an integer, got ${JSON.stringify(call.options.maxdepth)}`);
  return Number(call.options.maxdepth.trim());
}

export const toctreeDirective: DirectiveHandler = {
  kind: "directive",
  names: ["toctree"],
  options: ["maxdepth", "caption", ...FLAGS],
  argument: "none",
  handle(call, context) {
    const maxdepth = checkOptions(call);
    const block: ToctreeBlock = {
      at: call.at,
      hidden: "hidden" in call.options,
      titlesonly: "titlesonly" in call.options,
      includehidden: "includehidden" in call.options,
      entries: parseEntries(call, context),
    };
    if (call.options.caption) block.caption = call.options.caption.trim();
    if (maxdepth !== undefined) block.maxdepth = maxdepth;
    context.addToctree(block);
    if (block.hidden || context.pass === "collect") return [];
    const owner = context.index.get(context.file);
    if (!owner) throw new UnresolvedReferenceError(call.at.file, call.at.line, `toctree:${context.file}`, "is not a document");
    const nodes = entriesOf(owner, block, [], { context, titlesonly: block.titlesonly, includehidden: block.includehidden });
    const out: RootContent[] = [];
    if (block.caption) out.push({ type: "paragraph", children: [{ type: "strong", children: [{ type: "text", value: block.caption }] }] });
    const list = toList(nodes, 1, maxdepth ?? -1);
    if (list) out.push(list);
    return out;
  },
};
