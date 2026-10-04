import type { Heading, Paragraph } from "mdast";
import { visit } from "unist-util-visit";
import { parseMarkdown } from "./parse.ts";

const LABEL_CONTENT = /^\(([^)\s][^)]*)\)=\s*$/;
const ATTRS_CONTENT = /^\{([#.][^{}]*|[A-Za-z_][\w-]*=[^{}]*)\}\s*$/;
const COMMENT_CONTENT = /^%/;
const CANDIDATE = /^[ \t>]*(?:(?:[-*+]|\d+[.)])[ \t]+)*[({%]/m;
const CONTAINER_PREFIX = /^((?:[ \t]*>[ \t]?)*)([ \t]*)(.*)$/;

export const LABEL_MARKER = /^<!--benchbox-label (.+) -->$/;

export const ATTRS_MARKER = /^<!--benchbox-attrs (.+) -->$/;

export const MISPLACED_MARKER = /^<!--benchbox-misplaced (.+) -->$/;

export const COMMENT_MARKER = "<!--benchbox-comment-->";

function markerFor(content: string): { marker: string; kind: string } | undefined {
  const label = content.match(LABEL_CONTENT);
  if (label) return { marker: `<!--benchbox-label ${label[1]} -->`, kind: "label" };
  const attrs = content.match(ATTRS_CONTENT);
  if (attrs) return { marker: `<!--benchbox-attrs ${attrs[1].trim()} -->`, kind: "attrs-block" };
  if (COMMENT_CONTENT.test(content)) return { marker: COMMENT_MARKER, kind: "comment" };
  return undefined;
}

function rewrite(lines: string[], node: Paragraph | Heading): void {
  const start = node.position?.start;
  const end = node.position?.end;
  if (!start || !end) return;
  const last = node.type === "heading" ? end.line - 1 : end.line;
  const base = start.column - 1;
  for (let line = start.line; line <= last; line += 1) {
    const raw = lines[line - 1];
    let prefix: string;
    let content: string;
    if (line === start.line) {
      prefix = raw.slice(0, base);
      content = raw.slice(base);
    } else {
      const parts = raw.match(CONTAINER_PREFIX) as RegExpMatchArray;
      prefix = parts[1] + parts[2];
      content = parts[3];
    }
    const found = markerFor(content);
    if (!found) continue;
    const continuation = line !== start.line && prefix.length - base >= 4;
    lines[line - 1] = continuation ? `${prefix}<!--benchbox-misplaced ${found.kind} -->` : `${prefix}${found.marker}`;
  }
}

export function preprocess(source: string): string {
  if (!CANDIDATE.test(source)) return source;
  const tree = parseMarkdown(source);
  const lines = source.split("\n");
  visit(tree, (node) => {
    if (node.type === "paragraph") rewrite(lines, node);
    else if (node.type === "heading" && node.position && node.position.end.line > node.position.start.line) rewrite(lines, node);
  });
  return lines.join("\n");
}
