// @vitest-environment node
/**
 * Guardrail: user-facing strings (Error messages, JSX text, console output)
 * must not reference internal repository documents. The deployed explorer
 * is read by users who do not have access to `_project/`, `AGENTS.md`, or
 * `CLAUDE.md`; pointing them at those paths is a leak of internal context
 * dressed up as actionable guidance.
 *
 * The scan looks at string and template literals only — source-code
 * comments are intentionally allowed to reference internal docs because
 * they help maintainers and never reach the runtime.
 */

import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const FORBIDDEN_PATTERNS: ReadonlyArray<{ pattern: RegExp; label: string }> = [
  { pattern: /_project\//, label: "_project/" },
  { pattern: /\bAGENTS\.md\b/, label: "AGENTS.md" },
  { pattern: /\bCLAUDE\.md\b/, label: "CLAUDE.md" },
];

const here = fileURLToPath(new URL(".", import.meta.url));
const srcRoot = resolve(here, "..");

// Match double-quoted, single-quoted, and backtick-quoted strings, with
// support for escape sequences. Intentionally simple: a `${...}` inside a
// template literal is captured as part of the same backtick literal, which
// is fine — we only scan the captured text for substrings.
const STRING_LITERAL_RE = /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`/g;

// Strip block comments first so a `_project/` mention inside `/** ... */`
// is not visible to the string-literal scan. Line comments are stripped
// after to avoid affecting URLs like `http://` inside string literals.
function stripComments(source: string): string {
  let out = source.replace(/\/\*[\s\S]*?\*\//g, "");
  // Strip `//` line comments only when they are not inside a string. We
  // approximate by removing them after extracting strings: in practice the
  // string-literal regex below does its own quoting, so a residual `//`
  // outside a string is safe to drop.
  out = out.replace(/(^|[^:])\/\/[^\n]*/g, "$1");
  return out;
}

interface Finding {
  file: string;
  literal: string;
  pattern: string;
}

function scanFile(absPath: string): Finding[] {
  const source = readFileSync(absPath, "utf8");
  const sourceWithoutComments = stripComments(source);
  const findings: Finding[] = [];
  for (const match of sourceWithoutComments.matchAll(STRING_LITERAL_RE)) {
    const literal = match[0];
    for (const { pattern, label } of FORBIDDEN_PATTERNS) {
      if (pattern.test(literal)) {
        findings.push({
          file: relative(srcRoot, absPath),
          literal: literal.length > 200 ? `${literal.slice(0, 200)}…` : literal,
          pattern: label,
        });
      }
    }
  }
  return findings;
}

const EXCLUDED_DIR_NAMES = new Set(["__tests__", "test", "testing"]);

function collectSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const abs = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (EXCLUDED_DIR_NAMES.has(entry.name)) continue;
      collectSourceFiles(abs, out);
      continue;
    }
    if (!entry.isFile()) continue;
    if (!/\.(ts|tsx)$/.test(entry.name)) continue;
    if (/\.test\.(ts|tsx)$/.test(entry.name)) continue;
    out.push(abs);
  }
  return out;
}

describe("user-facing string hygiene", () => {
  it("does not reference internal repository documents in runtime strings", () => {
    const files = collectSourceFiles(srcRoot);
    expect(files.length).toBeGreaterThan(0);

    const findings = files.flatMap((file: string) => scanFile(file));
    if (findings.length > 0) {
      const message = findings
        .map((f) => `  ${f.file}: literal contains "${f.pattern}"\n    ${f.literal}`)
        .join("\n");
      throw new Error(
        `Found ${findings.length} runtime string(s) referencing internal repository paths.` +
          " Internal docs (_project/, AGENTS.md, CLAUDE.md) are not deployed and must" +
          " never be cited in error messages, JSX text, or console output:\n" +
          message,
      );
    }
  });

  it("matches expected forbidden patterns in a synthetic sample", () => {
    const sample = [
      'throw new Error("see _project/foo.md");',
      "// internal note: _project/bar.md (this is a comment, allowed)",
      'const ok = "regenerate via benchbox explorer build";',
    ].join("\n");
    const stripped = stripComments(sample);
    const literals = Array.from(stripped.matchAll(STRING_LITERAL_RE)).map((m) => m[0]);
    const flagged = literals.filter((lit) => /_project\//.test(lit));
    expect(flagged).toHaveLength(1);
    expect(flagged[0]).toContain("_project/foo.md");
  });
});
