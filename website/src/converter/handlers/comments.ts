import type { SyntaxHandler } from "../types.ts";

export const commentSyntax: SyntaxHandler<"comment"> = {
  kind: "syntax",
  name: "comment",
  handle(_node, _at, context) {
    context.releaseLabels();
    return [];
  },
};

export const htmlCommentSyntax: SyntaxHandler<"html-comment"> = {
  kind: "syntax",
  name: "html-comment",
  handle() {
    return [];
  },
};
