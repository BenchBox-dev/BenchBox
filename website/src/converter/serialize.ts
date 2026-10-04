import type { Root, RootContent } from "mdast";
import remarkGfm from "remark-gfm";
import remarkMdx from "remark-mdx";
import remarkStringify from "remark-stringify";
import { unified } from "unified";
import { stringify as stringifyYaml } from "yaml";
import { COMPONENT_MODULES } from "./components.ts";
import type { ConvertedDocument } from "./document.ts";

export type SerializedDocument = { outputPath: string; content: string; format: "md" | "mdx" };

const STRINGIFY_OPTIONS = {
  bullet: "-",
  bulletOther: "*",
  emphasis: "*",
  strong: "*",
  fence: "`",
  fences: true,
  rule: "-",
  listItemIndent: "one",
  incrementListMarker: true,
  setext: false,
  resourceLink: false,
} as const;

const markdown = unified().use(remarkGfm).use(remarkStringify, STRINGIFY_OPTIONS);
const mdx = unified().use(remarkGfm).use(remarkMdx).use(remarkStringify, STRINGIFY_OPTIONS);

function containsJsx(nodes: readonly RootContent[]): boolean {
  return nodes.some((node) => node.type.startsWith("mdx") || ("children" in node && containsJsx(node.children as RootContent[])));
}

function importsFor(document: ConvertedDocument): RootContent[] {
  const up = "../".repeat(document.contentId.split("/").length + 1);
  return [...document.components].sort().map((name) => ({ type: "mdxjsEsm", value: `import ${name} from "${up}${COMPONENT_MODULES[name]}";` }) as unknown as RootContent);
}

export function serializeDocument(document: ConvertedDocument, order: number | undefined): SerializedDocument {
  const needsMdx = document.components.size > 0 || containsJsx(document.root.children);
  const data = { ...document.data };
  if (order !== undefined) data.sidebar = { order };
  const frontMatter = `---\n${stringifyYaml(data, { lineWidth: 0 })}---\n`;
  const children = needsMdx ? [...importsFor(document), ...document.root.children] : document.root.children;
  const root: Root = { type: "root", children };
  const body = (needsMdx ? mdx : markdown).stringify(root);
  const format = needsMdx ? "mdx" : "md";
  return { outputPath: `${document.contentId}.${format}`, content: `${frontMatter}\n${body}`, format };
}
