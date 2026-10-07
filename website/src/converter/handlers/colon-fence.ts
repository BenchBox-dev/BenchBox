import type { PhrasingContent } from "mdast";
import type { SyntaxHandler } from "../types.ts";

export function lineStarts(children: readonly PhrasingContent[]): string[] {
  const starts: string[] = [];
  let atLineStart = true;
  for (const child of children) {
    if (child.type === "text") {
      child.value.split("\n").forEach((line, index) => {
        if (index > 0 || atLineStart) starts.push(line);
      });
      atLineStart = child.value.endsWith("\n");
    } else {
      if (atLineStart) starts.push("");
      atLineStart = child.type === "break";
    }
  }
  return starts;
}

function escapeLineStarts(children: readonly PhrasingContent[]): PhrasingContent[] {
  const out: PhrasingContent[] = [];
  let atLineStart = true;
  for (const child of children) {
    if (child.type !== "text") {
      out.push(child);
      atLineStart = false;
      continue;
    }
    let buffer = "";
    child.value.split("\n").forEach((line, index) => {
      const indent = line.length - line.trimStart().length;
      if ((index > 0 || atLineStart) && line.slice(indent).startsWith(":")) {
        let newline = index > 0;
        if (buffer !== "") out.push({ type: "text", value: buffer });
        const previous = out[out.length - 1];
        if (!newline && previous?.type === "text" && previous.value.endsWith("\n")) {
          previous.value = previous.value.slice(0, -1);
          newline = true;
        }
        out.push({ type: "html", value: `${newline ? "\n" : ""}${line.slice(0, indent)}&#58;` });
        buffer = line.slice(indent + 1);
      } else buffer += index > 0 ? `\n${line}` : line;
    });
    if (buffer !== "") out.push({ type: "text", value: buffer });
    atLineStart = child.value.endsWith("\n");
  }
  return out;
}

export const colonFenceSyntax: SyntaxHandler<"colon-fence"> = {
  kind: "syntax",
  name: "colon-fence",
  handle(node) {
    node.children = escapeLineStarts(node.children);
    return [node];
  },
};
