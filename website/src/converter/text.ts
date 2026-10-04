import type { Nodes } from "mdast";

export function plainText(node: Nodes): string {
  if ("value" in node && typeof node.value === "string" && node.type !== "html") return node.value;
  if ("children" in node) return (node.children as Nodes[]).map(plainText).join("");
  if (node.type === "image") return node.alt ?? "";
  return "";
}
