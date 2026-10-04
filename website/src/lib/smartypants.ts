import type { Root, Text } from "mdast";
import remarkSmartypants from "remark-smartypants";
import { unified } from "unified";
import { visit } from "unist-util-visit";

export const SMARTYPANTS = { backticks: false, dashes: "oldschool", ellipses: true, quotes: true } as const;

const OPENING_CONTEXT = /[\s([{<–—“‘-]/;
const CLOSING: Readonly<Record<string, string>> = { "“": "”", "‘": "’" };

export function closeQuotesAfterWords(value: string): string {
  let out = "";
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    const closing = CLOSING[character];
    out += closing !== undefined && index > 0 && !OPENING_CONTEXT.test(value[index - 1]) ? closing : character;
  }
  return out;
}

export function docutilsQuotes() {
  return (tree: Root): void => {
    visit(tree, "text", (node: Text) => {
      node.value = closeQuotesAfterWords(node.value);
    });
  };
}

const processor = unified().use(remarkSmartypants, SMARTYPANTS).use(docutilsQuotes);

export function smarten(text: string): string {
  const tree: Root = { type: "root", children: [{ type: "paragraph", children: [{ type: "text", value: text }] }] };
  const result = processor.runSync(tree) as Root;
  const paragraph = result.children[0];
  return paragraph.type === "paragraph" ? paragraph.children.map((child) => (child as Text).value ?? "").join("") : text;
}
