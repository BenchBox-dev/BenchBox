import type { Html, List, Paragraph, PhrasingContent, RootContent } from "mdast";
import { ConverterError } from "../errors.ts";
import type { SourcePosition } from "../model.ts";
import type { SyntaxHandler } from "../types.ts";

type Line = PhrasingContent[];

type Entry = { term: Line; definitions: Line[] };

const DEFINITION_START = /^:(\s+|$)/;
const BULLET = /^[-*+]\s+/;
const OTHER_BLOCK = /^(#{1,6}\s|>|`{3,}|~{3,}|\d{1,9}[.)]\s)/;

function splitLines(children: readonly PhrasingContent[]): Line[] {
  const lines: Line[] = [[]];
  for (const child of children) {
    if (child.type !== "text") {
      lines[lines.length - 1].push(child);
      continue;
    }
    child.value.split("\n").forEach((part, index) => {
      if (index > 0) lines.push([]);
      if (part !== "") lines[lines.length - 1].push({ type: "text", value: part });
    });
  }
  return lines;
}

function startsDefinition(line: Line): boolean {
  const first = line[0];
  return first?.type === "text" && DEFINITION_START.test(first.value);
}

function stripMarker(line: Line): Line {
  const [first, ...rest] = line;
  if (first?.type !== "text") return line;
  const value = first.value.replace(DEFINITION_START, "");
  return value === "" ? rest : [{ type: "text", value }, ...rest];
}

function joinLines(first: Line, next: Line): Line {
  return [...first, { type: "text", value: "\n" }, ...next];
}

function group(lines: readonly Line[]): { preamble: Line | undefined; entries: Entry[] } {
  const entries: Entry[] = [];
  let preamble: Line | undefined;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const current = entries[entries.length - 1];
    const nextIsDefinition = index + 1 < lines.length && startsDefinition(lines[index + 1]);
    if (startsDefinition(line) && current) current.definitions.push(stripMarker(line));
    else if (nextIsDefinition) entries.push({ term: line, definitions: [] });
    else if (current && current.definitions.length > 0) {
      const last = current.definitions.length - 1;
      current.definitions[last] = joinLines(current.definitions[last], line);
    } else preamble = preamble ? joinLines(preamble, line) : line;
  }
  return { preamble, entries };
}

function escapeText(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\{/g, "&#123;").replace(/\}/g, "&#125;");
}

function escapeAttribute(value: string): string {
  return escapeText(value).replace(/"/g, "&quot;");
}

const WRAPPERS: Record<string, string> = { strong: "strong", emphasis: "em", delete: "del" };

function inlineHtml(children: readonly PhrasingContent[], at: SourcePosition): string {
  return children
    .map((child): string => {
      if (child.type === "text") return escapeText(child.value.replace(/\n/g, " "));
      if (child.type === "inlineCode") return `<code>${escapeText(child.value)}</code>`;
      if (child.type === "html") return child.value;
      if (child.type === "break") return "<br />";
      if (child.type === "link") {
        const title = child.title ? ` title="${escapeAttribute(child.title)}"` : "";
        return `<a href="${escapeAttribute(child.url)}"${title}>${inlineHtml(child.children, at)}</a>`;
      }
      if (child.type in WRAPPERS) {
        const name = WRAPPERS[child.type];
        return `<${name}>${inlineHtml((child as { children: PhrasingContent[] }).children, at)}</${name}>`;
      }
      throw new ConverterError(at.file, at.line, `deflist: unsupported ${child.type} inside a term`);
    })
    .join("");
}

export function mergeDefinitionLists(nodes: RootContent[]): RootContent[] {
  const out: RootContent[] = [];
  for (const node of nodes) {
    const previous = out[out.length - 1];
    if (previous?.type === "html" && previous.value === "</dl>" && node.type === "html" && node.value === "<dl>") out.pop();
    else out.push(node);
  }
  return out;
}

function tag(value: string): Html {
  return { type: "html", value };
}

function paragraph(children: Line): Paragraph {
  return { type: "paragraph", children };
}

function definitionBody(definition: Line, at: SourcePosition): RootContent {
  const first = definition[0];
  if (first?.type !== "text") return paragraph(definition);
  if (OTHER_BLOCK.test(first.value)) throw new ConverterError(at.file, at.line, `deflist: a definition that starts with ${JSON.stringify(first.value.slice(0, 3))} is not supported`);
  const bullet = first.value.match(BULLET);
  if (!bullet) return paragraph(definition);
  const rest = first.value.slice(bullet[0].length);
  const content: Line = rest === "" ? definition.slice(1) : [{ type: "text", value: rest }, ...definition.slice(1)];
  const list: List = { type: "list", ordered: false, spread: false, children: [{ type: "listItem", spread: false, children: [paragraph(content)] }] };
  return list;
}

export const deflistSyntax: SyntaxHandler<"deflist"> = {
  kind: "syntax",
  name: "deflist",
  handle(node, at) {
    const { preamble, entries } = group(splitLines(node.children));
    const out: RootContent[] = [];
    if (preamble) out.push(paragraph(preamble));
    out.push(tag("<dl>"));
    for (const entry of entries) {
      out.push(tag(`<dt>${inlineHtml(entry.term, at)}</dt>`));
      for (const definition of entry.definitions) out.push(tag("<dd>"), definitionBody(definition, at), tag("</dd>"));
    }
    out.push(tag("</dl>"));
    return out;
  },
};
