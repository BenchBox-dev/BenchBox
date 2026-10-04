import { readdirSync } from "node:fs";
import path from "node:path";

export const EXCLUDED_ROOTS: ReadonlySet<string> = new Set(["_build", "_tags", "_static", "_templates", "_project", "agent"]);

export const EXCLUDED_FILES: ReadonlySet<string> = new Set([
  "development/task-management-design.md",
  "development/dependency-audit-raw.md",
  "development/unified_frame_any_survey.md",
  "development/duplication-residuals.md",
]);

export type DocSourceFile = { absolute: string; relative: string };

function compareNames(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function walk(root: string, directory: string, suffix: string, found: DocSourceFile[]): void {
  const entries = readdirSync(directory, { withFileTypes: true }).sort((a, b) => compareNames(a.name, b.name));
  for (const entry of entries) {
    const absolute = path.join(directory, entry.name);
    const relative = path.relative(root, absolute).split(path.sep).join("/");
    if (entry.name.startsWith(".#")) continue;
    if (entry.isDirectory()) {
      if (directory === root && EXCLUDED_ROOTS.has(entry.name)) continue;
      if (entry.name === "_sources" || entry.name.endsWith(".lproj")) continue;
      walk(root, absolute, suffix, found);
    } else if (entry.name.endsWith(suffix) && !EXCLUDED_FILES.has(relative)) {
      found.push({ absolute, relative });
    }
  }
}

export function listDocSources(docsRoot: string, suffix: ".md" | ".rst" = ".md"): DocSourceFile[] {
  const found: DocSourceFile[] = [];
  walk(docsRoot, docsRoot, suffix, found);
  return found;
}
