import { LABEL_MARKER } from "../preprocess.ts";
import type { SyntaxHandler } from "../types.ts";

export const labelSyntax: SyntaxHandler<"label"> = {
  kind: "syntax",
  name: "label",
  handle(node, at, context) {
    const marker = node.value.match(LABEL_MARKER);
    if (!marker) return [];
    return [context.queueLabel(marker[1], at)];
  },
};
