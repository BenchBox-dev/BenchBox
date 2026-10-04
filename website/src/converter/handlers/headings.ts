import { plainText } from "../text.ts";
import type { SyntaxHandler } from "../types.ts";

export const headingSyntax: SyntaxHandler<"heading"> = {
  kind: "syntax",
  name: "heading",
  handle(node, _at, context) {
    const text = plainText(node);
    const id = context.allocateHeadingId(text);
    context.addSection(node.depth, text, id);
    if (node.depth === 1 && context.needsTitle()) {
      context.claimTitle(text, id);
      return context.collection === "docs" ? [{ type: "html", value: `<span id="${id}"></span>` }] : [];
    }
    context.recordHeadingId(id);
    return [node];
  },
};
