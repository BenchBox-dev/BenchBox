import type { Html, Text } from "mdast";
import { ConverterError } from "../errors.ts";
import type { SourcePosition } from "../model.ts";
import type { ConvertContext, SyntaxHandler } from "../types.ts";

const SAFE_ELEMENTS = new Set([
  "a", "abbr", "b", "bdi", "bdo", "blockquote", "br", "caption", "cite", "code", "col", "colgroup", "dd", "del", "details", "dfn", "div", "dl", "dt", "em",
  "figcaption", "figure", "hr", "i", "img", "ins", "kbd", "li", "mark", "ol", "p", "pre", "q", "s", "samp", "small", "span", "strong", "sub", "summary", "sup",
  "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul", "var", "wbr",
]);

const TAG = /<\/?([A-Za-z][A-Za-z0-9-]*)(?:\s[^<>]*)?\/?>/g;
const SPAN_WITH_ID = /<span\b[^<>]*\bid\s*=[^<>]*>/gi;
const BARE_SPAN = /^<span id="([^"<>\s]+)">$/;
const UNSAFE_ATTRIBUTE = /\son[a-z]+\s*=|javascript:|\sstyle\s*=/i;

function registerSpanIds(value: string, at: SourcePosition, context: ConvertContext): void {
  for (const tag of value.matchAll(SPAN_WITH_ID)) {
    const bare = tag[0].match(BARE_SPAN);
    if (!bare) throw new ConverterError(at.file, at.line, `raw html ${JSON.stringify(tag[0])} must be a bare <span id="..."> anchor`);
    context.recordRawId(bare[1], at);
  }
}

function convert(node: Html, at: SourcePosition, context: ConvertContext, inline: boolean): (Html | Text)[] {
  const tags = [...node.value.matchAll(TAG)];
  const names = tags.map((tag) => tag[1].toLowerCase());
  if (tags.length > 0 && names.every((name) => SAFE_ELEMENTS.has(name))) {
    if (UNSAFE_ATTRIBUTE.test(node.value)) throw new ConverterError(at.file, at.line, `raw html ${JSON.stringify(node.value)} has an unsafe attribute`);
    registerSpanIds(node.value, at, context);
    return [node];
  }
  if (inline && tags.length === 1 && tags[0][0] === node.value && !node.value.startsWith("</")) return [{ type: "text", value: node.value }];
  throw new ConverterError(at.file, at.line, `raw html ${JSON.stringify(node.value)} is neither a known html element nor a placeholder`);
}

export const rawHtmlSyntax: SyntaxHandler<"raw-html"> = {
  kind: "syntax",
  name: "raw-html",
  handle(node, at, context) {
    return convert(node, at, context, false);
  },
};

export const rawHtmlInlineSyntax: SyntaxHandler<"raw-html-inline"> = {
  kind: "syntax",
  name: "raw-html-inline",
  handle(node, at, context) {
    return convert(node, at, context, true);
  },
};
