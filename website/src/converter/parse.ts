import type { Root } from "mdast";
import remarkFrontmatter from "remark-frontmatter";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import { unified } from "unified";
import { parse as parseYaml } from "yaml";
import { ConverterError } from "./errors.ts";

const parser = unified().use(remarkParse).use(remarkFrontmatter, ["yaml"]).use(remarkGfm, { singleTilde: false });

export function parseMarkdown(source: string): Root {
  return parser.parse(source);
}

export type FrontMatter = { data: Record<string, unknown>; line: number; keyLines: Map<string, number> };

function keyLinesOf(yaml: string, firstLine: number): Map<string, number> {
  const lines = new Map<string, number>();
  yaml.split("\n").forEach((text, offset) => {
    const key = text.match(/^([A-Za-z_][\w-]*):/);
    if (key && !lines.has(key[1])) lines.set(key[1], firstLine + 1 + offset);
  });
  return lines;
}

export function parseFrontMatter(file: string, tree: Root): FrontMatter {
  const first = tree.children[0];
  if (!first || first.type !== "yaml") return { data: {}, line: 1, keyLines: new Map() };
  const line = first.position?.start.line ?? 1;
  let parsed: unknown;
  try {
    parsed = parseYaml(first.value);
  } catch (error) {
    throw new ConverterError(file, line, `front matter is not valid YAML: ${(error as Error).message}`);
  }
  if (parsed === null || parsed === undefined) return { data: {}, line, keyLines: new Map() };
  if (typeof parsed !== "object" || Array.isArray(parsed)) throw new ConverterError(file, line, "front matter must be a mapping");
  return { data: parsed as Record<string, unknown>, line, keyLines: keyLinesOf(first.value, line) };
}
