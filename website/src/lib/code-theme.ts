import type { ShikiTransformer, ThemeRegistration } from "shiki";

const rules: [string[], string][] = [
  [["comment", "punctuation.definition.comment"], "var(--code-comment)"],
  [["string.quoted", "punctuation.definition.string"], "var(--prism-string)"],
  [["support.function.builtin.python"], "var(--prism-string)"],
  [["keyword", "storage", "support.function.builtin.shell"], "var(--prism-keyword)"],
  [["constant.numeric", "constant.language"], "var(--prism-deleted)"],
  [["keyword.operator"], "var(--prism-operator)"],
  [
    [
      "punctuation.separator",
      "punctuation.accessor",
      "punctuation.parenthesis",
      "punctuation.section",
      "punctuation.definition.arguments",
      "punctuation.definition.parameters",
      "punctuation.definition.list",
      "punctuation.definition.dict",
      "punctuation.definition.set",
      "punctuation.definition.tuple",
    ],
    "var(--code-punctuation)",
  ],
];

export const landingCodeTheme: ThemeRegistration = {
  name: "benchbox-landing",
  type: "dark",
  colors: { "editor.foreground": "var(--code-fg)", "editor.background": "var(--code-bg)" },
  settings: [{ settings: { foreground: "var(--code-fg)" } }, ...rules.map(([scope, foreground]) => ({ scope, settings: { foreground } }))],
};

const SHELL_OPTION = /^-{1,2}\w+(\.\w+)*$/;
const SHELL_KEYWORD_WORDS = new Set(["add", "import"]);

function withColor(style: unknown, color: string): string {
  const rest = String(style ?? "")
    .split(";")
    .filter((part) => part.trim() && !part.trim().startsWith("color:"));
  return [`color:${color}`, ...rest].join(";");
}

export function landingTransformers(lang: string): ShikiTransformer[] {
  if (lang !== "bash") return [];
  return [
    {
      span(node, _line, _col, _lineElement, token) {
        const word = token.content.trim();
        if (SHELL_OPTION.test(word)) node.properties.style = withColor(node.properties.style, "var(--prism-variable)");
        else if (SHELL_KEYWORD_WORDS.has(word)) node.properties.style = withColor(node.properties.style, "var(--prism-keyword)");
      },
    },
  ];
}
