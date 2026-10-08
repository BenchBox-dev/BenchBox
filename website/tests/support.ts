import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { buildSite, type BuildResult } from "../src/converter/build.ts";
import type { HandlerRegistry } from "../src/converter/registry.ts";
import { EXCLUSIONS_FILE } from "../src/converter/sources.ts";

const created: string[] = [];

export function writeDocs(files: Record<string, string>): string {
  const root = mkdtempSync(path.join(os.tmpdir(), "benchbox-docs-"));
  created.push(root);
  for (const [relative, content] of Object.entries({ [EXCLUSIONS_FILE]: "", ...files })) {
    const target = path.join(root, relative);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, content);
  }
  return root;
}

export function cleanup(): void {
  for (const root of created.splice(0)) rmSync(root, { recursive: true, force: true });
}

export function build(files: Record<string, string>, registry?: HandlerRegistry): BuildResult {
  const docsRoot = writeDocs(files);
  return registry ? buildSite({ docsRoot, registry }) : buildSite({ docsRoot });
}

export function pageOf(result: BuildResult, contentPath: string): string {
  const content = result.files.get(`content/${contentPath}`);
  if (content === undefined) {
    throw new Error(`no output ${contentPath}; errors: ${result.errors.map((error) => error.message).join("; ")}`);
  }
  return content;
}

export function bodyOf(result: BuildResult, contentPath: string): string {
  return pageOf(result, contentPath).replace(/^---\n[\s\S]*?\n---\n\n/, "");
}

export function frontMatterOf(result: BuildResult, contentPath: string): string {
  const match = pageOf(result, contentPath).match(/^---\n([\s\S]*?)\n---\n/);
  return match ? match[1] : "";
}

export const STUB = "# Stub\n";
