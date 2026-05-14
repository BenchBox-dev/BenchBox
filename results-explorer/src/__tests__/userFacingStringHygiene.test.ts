// @vitest-environment node
/**
 * Guardrail: user-facing strings (Error messages, JSX text, console output)
 * must not reference internal repository documents. The deployed explorer
 * is read by users who do not have access to `_project/`, `AGENTS.md`, or
 * `CLAUDE.md`; pointing them at those paths is a leak of internal context
 * dressed up as actionable guidance.
 *
 * The scan looks at string literals, template literals, and static JSX text.
 * Source-code comments are intentionally allowed to reference internal docs
 * because they help maintainers and never reach the runtime.
 */

import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import * as ts from "typescript";
import { describe, expect, it } from "vitest";

const FORBIDDEN_PATTERNS: ReadonlyArray<{ pattern: RegExp; label: string }> = [
  { pattern: /_project\//, label: "_project/" },
  { pattern: /\bAGENTS\.md\b/, label: "AGENTS.md" },
  { pattern: /\bCLAUDE\.md\b/, label: "CLAUDE.md" },
];

const here = fileURLToPath(new URL(".", import.meta.url));
const srcRoot = resolve(here, "..");

interface Finding {
  file: string;
  fragment: string;
  pattern: string;
}

function scanSource(file: string, source: string, scriptKind: ts.ScriptKind): Finding[] {
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, scriptKind);
  const findings: Finding[] = [];

  function scanFragment(fragment: string): void {
    for (const { pattern, label } of FORBIDDEN_PATTERNS) {
      if (pattern.test(fragment)) {
        findings.push({
          file,
          fragment: fragment.length > 200 ? `${fragment.slice(0, 200)}…` : fragment,
          pattern: label,
        });
      }
    }
  }

  function visit(node: ts.Node): void {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isJsxText(node)) {
      scanFragment(node.getText(sourceFile));
    }
    if (ts.isTemplateExpression(node)) {
      scanFragment(node.head.getText(sourceFile));
      for (const span of node.templateSpans) {
        scanFragment(span.literal.getText(sourceFile));
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return findings;
}

function scanFile(absPath: string): Finding[] {
  const source = readFileSync(absPath, "utf8");
  const scriptKind = absPath.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return scanSource(relative(srcRoot, absPath), source, scriptKind);
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
        .map((f) => `  ${f.file}: source fragment contains "${f.pattern}"\n    ${f.fragment}`)
        .join("\n");
      throw new Error(
        `Found ${findings.length} runtime source fragment(s) referencing internal repository paths.` +
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
      "<p>See AGENTS.md</p>",
      "{/* JSX maintainer note: CLAUDE.md (this is a comment, allowed) */}",
      'const ok = "ask a maintainer to rebuild the Explorer data";',
    ].join("\n");
    const findings = scanSource("synthetic.tsx", sample, ts.ScriptKind.TSX);
    expect(findings).toEqual([
      {
        file: "synthetic.tsx",
        fragment: '"see _project/foo.md"',
        pattern: "_project/",
      },
      {
        file: "synthetic.tsx",
        fragment: "See AGENTS.md",
        pattern: "AGENTS.md",
      },
    ]);
  });
});
