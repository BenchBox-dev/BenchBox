import type { Link } from "mdast";
import { UnresolvedReferenceError } from "../errors.ts";
import type { RoleHandler } from "../types.ts";

const TITLED = /^([\s\S]*?)\s*<([^<>]+)>$/;

function split(content: string): { title: string | undefined; target: string } {
  const match = content.match(TITLED);
  return match ? { title: match[1].trim() || undefined, target: match[2].trim() } : { title: undefined, target: content.trim() };
}

export const docRole: RoleHandler = {
  kind: "role",
  names: ["doc"],
  handle(call, context) {
    const { title, target } = split(call.content);
    const resolved = context.resolveDoc(target, call.at);
    const link: Link = { type: "link", url: resolved.route, children: [{ type: "text", value: title ?? resolved.title }] };
    return [link];
  },
};

export const refRole: RoleHandler = {
  kind: "role",
  names: ["ref"],
  handle(call, context) {
    const { title, target } = split(call.content);
    const resolved = context.resolveLabel(target, call.at);
    const text = title ?? resolved.title;
    if (text === undefined) {
      throw new UnresolvedReferenceError(call.at.file, call.at.line, `ref:${target}`, "labels content without a heading, so it needs explicit link text: {ref}`text <label>`");
    }
    const link: Link = { type: "link", url: `${resolved.route}#${resolved.id}`, children: [{ type: "text", value: text }] };
    return [link];
  },
};
