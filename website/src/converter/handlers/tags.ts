import { UnknownConstructError } from "../errors.ts";
import type { DirectiveHandler } from "../types.ts";

export const tagsDirective: DirectiveHandler = {
  kind: "directive",
  names: ["tags"],
  options: [],
  argument: "accepted",
  handle(call, context) {
    const source = call.argument !== "" ? call.argument : call.body;
    const tags = source
      .split(/[,\n]/)
      .map((tag) => tag.trim())
      .filter(Boolean);
    if (tags.length === 0) throw new UnknownConstructError(call.at.file, call.at.line, "directive-argument:tags", "tags needs at least one tag");
    context.addTags(tags);
    return [];
  },
};
