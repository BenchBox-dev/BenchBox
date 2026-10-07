import { flattenTitle, smartenTitle } from "../../lib/smartypants.ts";
import { plainText } from "../text.ts";
import type { SyntaxHandler } from "../types.ts";

export const headingSyntax: SyntaxHandler<"heading"> = {
  kind: "syntax",
  name: "heading",
  handle(node, _at, context) {
    const text = plainText(node);
    const title = smartenTitle(flattenTitle(node.children));
    const id = context.allocateHeadingId(text, title);
    context.addSection(node.depth, title, id);
    if (node.depth === 1 && context.needsTitle()) {
      context.claimTitle(title, id);
      return context.collection === "docs" ? [{ type: "html", value: `<span id="${id}"></span>` }] : [];
    }
    context.recordHeadingId(id);
    return [node];
  },
};
