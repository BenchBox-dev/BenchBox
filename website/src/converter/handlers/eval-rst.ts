import type { Link, List, ListItem, PhrasingContent } from "mdast";
import { ConverterError } from "../errors.ts";
import type { DirectiveHandler } from "../types.ts";
import { linkSyntax } from "./links.ts";

const ITEM = /^\* `([^`<>]+?)\s*<([^<>`\s]+)>`_([^`*\\<>]*)$/;

export const evalRstDirective: DirectiveHandler = {
  kind: "directive",
  names: ["eval-rst"],
  options: [],
  argument: "none",
  handle(call, context) {
    const items: ListItem[] = [];
    call.body.split("\n").forEach((line, offset) => {
      if (line.trim() === "") return;
      const match = line.match(ITEM);
      const suffix = match?.[3] ?? "";
      if (!match || suffix.startsWith("_")) {
        throw new ConverterError(call.bodyAt.file, call.bodyAt.line + offset, `eval-rst supports only bullet items of the form * \`text <url>\`_ [- description]; got ${JSON.stringify(line)}`);
      }
      const link: Link = { type: "link", url: match[2], children: [{ type: "text", value: match[1] }] };
      const children = [...linkSyntax.handle(link, { file: call.bodyAt.file, line: call.bodyAt.line + offset }, context)] as PhrasingContent[];
      if (suffix !== "") children.push({ type: "text", value: suffix });
      items.push({ type: "listItem", spread: false, children: [{ type: "paragraph", children }] });
    });
    if (items.length === 0) throw new ConverterError(call.at.file, call.at.line, "eval-rst block is empty");
    const list: List = { type: "list", ordered: false, spread: false, children: items };
    return [list];
  },
};
