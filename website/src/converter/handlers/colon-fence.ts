import type { SyntaxHandler } from "../types.ts";

export const colonFenceSyntax: SyntaxHandler<"colon-fence"> = {
  kind: "syntax",
  name: "colon-fence",
  handle(node) {
    return [node];
  },
};
