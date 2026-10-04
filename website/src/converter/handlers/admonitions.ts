import type { RootContent } from "mdast";
import { UnknownConstructError } from "../errors.ts";
import type { DirectiveCall, DirectiveHandler } from "../types.ts";

type CalloutType = "note" | "tip" | "caution" | "danger";

const KINDS: Readonly<Record<string, { type: CalloutType; title: string }>> = {
  note: { type: "note", title: "Note" },
  tip: { type: "tip", title: "Tip" },
  warning: { type: "caution", title: "Warning" },
  important: { type: "caution", title: "Important" },
  deprecated: { type: "caution", title: "Deprecated" },
};

function parts(call: DirectiveCall): { title: string; lead: string; separate: boolean } {
  const kind = KINDS[call.name];
  if (call.name !== "deprecated") return { title: kind.title, lead: call.argument, separate: false };
  const [version, ...rest] = call.argument.split(/\s+/);
  if (!version) {
    throw new UnknownConstructError(call.at.file, call.at.line, "directive-argument:deprecated", "deprecated requires a version argument");
  }
  return { title: `Deprecated since ${version}`, lead: rest.join(" "), separate: true };
}

export const admonitionDirective: DirectiveHandler = {
  kind: "directive",
  names: Object.keys(KINDS),
  options: [],
  argument: "accepted",
  handle(call, context) {
    const kind = KINDS[call.name];
    const { title, lead, separate } = parts(call);
    context.useComponent("Callout");
    let children: RootContent[];
    if (lead === "") children = context.convertMarkdown(call.body, call.bodyAt);
    else if (separate) children = [...context.convertMarkdown(lead, call.at), ...context.convertMarkdown(call.body, call.bodyAt)];
    else children = context.convertMarkdown(`${lead}\n${call.body}`, call.at);
    return [
      {
        type: "mdxJsxFlowElement",
        name: "Callout",
        attributes: [
          { type: "mdxJsxAttribute", name: "type", value: kind.type },
          { type: "mdxJsxAttribute", name: "title", value: title },
        ],
        children,
      } as unknown as RootContent,
    ];
  },
};
