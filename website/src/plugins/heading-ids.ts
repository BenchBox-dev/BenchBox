import type { Heading, Root } from "mdast";
import { visit } from "unist-util-visit";

type HeadingProperties = { hProperties?: Record<string, string> };

type AstroFile = { path?: string; data: { astro?: { frontmatter?: { headingIds?: unknown } } } };

export function headingIds() {
  return (tree: Root, file: AstroFile) => {
    const ids = file.data.astro?.frontmatter?.headingIds;
    const expected = Array.isArray(ids) ? ids.map(String) : [];
    const headings: Heading[] = [];
    visit(tree, "heading", (node) => {
      headings.push(node);
    });
    if (headings.length !== expected.length) {
      throw new Error(`${file.path ?? "document"}: ${headings.length} headings but ${expected.length} converter heading ids`);
    }
    headings.forEach((heading, position) => {
      const data = (heading.data ?? {}) as HeadingProperties;
      heading.data = { ...data, hProperties: { ...(data.hProperties ?? {}), id: expected[position] } } as Heading["data"];
    });
  };
}
