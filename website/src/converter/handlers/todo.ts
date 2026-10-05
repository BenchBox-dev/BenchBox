import { notYetImplementedDirective, notYetImplementedSyntax } from "../registry.ts";
import type { Handler } from "../types.ts";

export const todoHandlers: readonly Handler[] = [
  notYetImplementedDirective("admonitions", ["note", "tip", "warning", "important", "caution", "danger", "attention", "hint", "error", "seealso", "admonition", "deprecated", "versionadded", "versionchanged"]),
  notYetImplementedDirective("mermaid", ["mermaid"]),
  notYetImplementedDirective("tables", ["list-table", "csv-table", "table"]),
  notYetImplementedDirective("sphinx-design", ["grid", "grid-item", "grid-item-card", "card", "tab-set", "tab-item", "dropdown"]),
  notYetImplementedDirective("eval-rst", ["eval-rst"]),
  notYetImplementedDirective("highlighting", ["code-block", "code", "sourcecode", "literalinclude"]),
  notYetImplementedSyntax("deflist", "deflist"),
  notYetImplementedDirective("ablog", ["postlist", "post", "update"]),
  notYetImplementedSyntax("raw-html", "raw-html"),
  notYetImplementedDirective("images", ["image", "figure"]),
  notYetImplementedSyntax("images", "image"),
];
