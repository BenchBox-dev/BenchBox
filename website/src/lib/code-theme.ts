import type { ThemeRegistration } from "shiki";

const rules: [string[], string][] = [
  [["comment", "punctuation.definition.comment"], "var(--code-comment)"],
  [["string.quoted", "punctuation.definition.string"], "var(--prism-string)"],
  [["keyword", "storage", "support.function.builtin.shell", "entity.name.function.python", "support.function.builtin.python", "entity.name.class"], "var(--prism-keyword)"],
  [["constant.numeric", "constant.language", "constant.other.symbol", "entity.name.tag"], "var(--prism-deleted)"],
  [["keyword.operator"], "var(--prism-operator)"],
  [["variable.other", "variable.parameter", "regexp"], "var(--prism-variable)"],
  [["punctuation.separator", "punctuation.terminator", "punctuation.section"], "var(--text-secondary)"],
];

export const landingCodeTheme: ThemeRegistration = {
  name: "benchbox-landing",
  type: "dark",
  colors: { "editor.foreground": "var(--code-fg)", "editor.background": "var(--code-bg)" },
  settings: [
    { settings: { foreground: "var(--code-fg)" } },
    ...rules.map(([scope, foreground]) => ({ scope, settings: { foreground } })),
  ],
};
