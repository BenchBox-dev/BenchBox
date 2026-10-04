const KEYFRAMES = /^(-\w+-)?keyframes$/;

function scopeSelector(selector, scope) {
  const trimmed = selector.trim();
  if (trimmed === "html") return `html:has(${scope})`;
  if (trimmed === "body" || trimmed.startsWith("body::") || trimmed.startsWith("body:")) return scope + trimmed.slice(4);
  return `${scope} ${trimmed}`;
}

function insideKeyframes(rule) {
  return rule.parent?.type === "atrule" && KEYFRAMES.test(rule.parent.name);
}

export function scopeCss({ match, scope, drop = [] }) {
  return {
    postcssPlugin: "benchbox-scope-css",
    Once(root) {
      const file = root.source?.input.file ?? "";
      if (!match.test(file.replaceAll("\\", "/"))) return;
      root.walkRules((rule) => {
        if (insideKeyframes(rule)) return;
        const selectors = rule.selectors.filter((selector) => !drop.some((pattern) => pattern.test(selector.trim())));
        if (selectors.length === 0) {
          rule.remove();
          return;
        }
        rule.selectors = selectors.map((selector) => scopeSelector(selector, scope));
      });
    },
  };
}
