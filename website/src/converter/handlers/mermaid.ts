import type { RootContent } from "mdast";
import { UnknownConstructError } from "../errors.ts";
import type { DirectiveHandler } from "../types.ts";

export const mermaidDirective: DirectiveHandler = {
  kind: "directive",
  names: ["mermaid"],
  options: [],
  argument: "none",
  handle(call, context) {
    const diagram = call.body.trim();
    if (diagram === "") {
      throw new UnknownConstructError(call.at.file, call.at.line, "directive-body:mermaid", "mermaid requires a diagram body");
    }
    context.useComponent("Mermaid");
    return [
      {
        type: "mdxJsxFlowElement",
        name: "Mermaid",
        attributes: [
          {
            type: "mdxJsxAttribute",
            name: "diagram",
            value: { type: "mdxJsxAttributeValueExpression", value: JSON.stringify(diagram) },
          },
        ],
        children: [],
      } as unknown as RootContent,
    ];
  },
};
