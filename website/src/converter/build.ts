import { lstatSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { convertDocument, type ConvertedDocument } from "./document.ts";
import { DocsIndex, placeholderInfo } from "./docs-index.ts";
import { ConverterError, ConversionFailedError } from "./errors.ts";
import { createDefaultRegistry } from "./handlers/index.ts";
import type { DocInfo } from "./model.ts";
import type { HandlerRegistry } from "./registry.ts";
import { findMdxProblem, serializeDocument } from "./serialize.ts";
import { generateTagSources } from "./tag-pages.ts";
import { buildSidebar } from "./sidebar.ts";
import { listDocSources } from "./sources.ts";

export type BuildOptions = { docsRoot: string; registry?: HandlerRegistry; knownBrokenLinks?: ReadonlySet<string> };

export type BuildSummary = { pages: number; md: number; mdx: number; mdxPages: string[] };

export type BuildResult = { files: Map<string, string>; errors: ConverterError[]; summary: BuildSummary; infos: DocInfo[] };

function json(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}

type SourceText = { relative: string; raw: string };

type Run = { registry: HandlerRegistry; docsRoot: string; knownBroken: ReadonlySet<string> };

function convertAll(sources: readonly SourceText[], index: DocsIndex, run: Run, pass: "collect" | "emit"): ConvertedDocument[] {
  return sources.map((source) => convertDocument({ path: source.relative, raw: source.raw, index, pass, ...run }));
}

export function loadKnownBrokenLinks(file: string): Set<string> {
  const entries = JSON.parse(readFileSync(file, "utf-8")) as [string, string, string][];
  return new Set(entries.map(([source, target]) => `${source} ${target}`));
}

function hasUnknownToctreeTarget(document: ConvertedDocument, index: DocsIndex): boolean {
  return document.info.toctrees.some((block) => block.entries.some((entry) => entry.kind === "doc" && index.get(entry.path) === undefined));
}

export function buildSite(options: BuildOptions): BuildResult {
  const run: Run = { registry: options.registry ?? createDefaultRegistry(), docsRoot: options.docsRoot, knownBroken: options.knownBrokenLinks ?? new Set() };
  const sources: SourceText[] = listDocSources(options.docsRoot).map((source) => ({ relative: source.relative, raw: readFileSync(source.absolute, "utf-8") }));
  const errors: ConverterError[] = listDocSources(options.docsRoot, ".rst").map(
    (source) => new ConverterError(source.relative, 1, "reStructuredText pages are not built by this site; convert the page to MyST Markdown"),
  );
  const seed = new DocsIndex(sources.map((source) => placeholderInfo(source)));
  const firstPass = convertAll(sources, seed, run, "collect");
  const generated = generateTagSources(firstPass.map((document) => document.info).filter((info) => info.collection === "docs").map((info) => ({ path: info.path, tags: info.tags })));
  const generatedSeed = new DocsIndex([...seed.paths().map((path) => seed.get(path) as DocInfo), ...generated.map((source) => placeholderInfo(source))]);
  const collected = firstPass.map((document, position) =>
    hasUnknownToctreeTarget(document, seed) ? convertAll([sources[position]], generatedSeed, run, "collect")[0] : document,
  );
  collected.push(...convertAll(generated, generatedSeed, run, "collect"));
  const emitted = [...sources, ...generated];
  let index: DocsIndex;
  try {
    index = new DocsIndex(collected.map((document) => document.info));
  } catch (error) {
    if (error instanceof ConverterError) return { files: new Map(), errors: [error], summary: { pages: 0, md: 0, mdx: 0, mdxPages: [] }, infos: [] };
    throw error;
  }
  const documents = convertAll(emitted, index, run, "emit");
  for (const document of documents) errors.push(...document.errors);
  const summary: BuildSummary = { pages: documents.length, md: 0, mdx: 0, mdxPages: [] };
  const infos = documents.map((document) => document.info);
  if (errors.length > 0) return { files: new Map(), errors, summary, infos };
  const sidebar = buildSidebar(index);
  const files = new Map<string, string>();
  const tags = new Map<string, { path: string; route: string; title: string }[]>();
  for (const document of documents) {
    const serialized = serializeDocument(document, sidebar.order[document.path]);
    if (serialized.format === "mdx") {
      const problem = findMdxProblem(document);
      if (problem) {
        errors.push(new ConverterError(problem.at.file, problem.at.line, `content is not valid MDX on this page, which uses a component: ${problem.reason}`));
        continue;
      }
    }
    files.set(`content/${serialized.outputPath}`, serialized.content);
    if (serialized.format === "mdx") {
      summary.mdx += 1;
      summary.mdxPages.push(document.path);
    } else summary.md += 1;
    for (const tag of document.info.tags) {
      const pages = tags.get(tag) ?? [];
      pages.push({ path: document.path, route: document.info.route, title: document.info.title });
      tags.set(tag, pages);
    }
  }
  files.set("manifest/sidebar.json", json(sidebar));
  files.set("manifest/tags.json", json(Object.fromEntries([...tags.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)))));
  files.set("manifest/summary.json", json(summary));
  if (errors.length > 0) return { files: new Map(), errors, summary, infos };
  return { files, errors, summary, infos };
}

export const OUTPUT_MARKER = ".benchbox-converter-output";

export class UnownedOutputError extends Error {
  constructor(outRoot: string, reason = `it is not empty and has no ${OUTPUT_MARKER} file from an earlier converter run`) {
    super(`refusing to touch ${outRoot}: ${reason}`);
    this.name = "UnownedOutputError";
  }
}

export function assertOwnedOutput(outRoot: string): void {
  let stats;
  try {
    stats = lstatSync(outRoot);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
  if (!stats.isDirectory()) throw new UnownedOutputError(outRoot, "it exists and is not a directory");
  const entries = readdirSync(outRoot);
  if (entries.length > 0 && !entries.includes(OUTPUT_MARKER)) throw new UnownedOutputError(outRoot);
}

export function clearOutput(outRoot: string): void {
  assertOwnedOutput(outRoot);
  rmSync(outRoot, { recursive: true, force: true });
}

export function writeOutput(outRoot: string, files: Map<string, string>): void {
  assertOwnedOutput(outRoot);
  mkdirSync(outRoot, { recursive: true });
  writeFileSync(path.join(outRoot, OUTPUT_MARKER), "");
  const keep = new Set([...files.keys(), OUTPUT_MARKER]);
  const stale = (directory: string, prefix: string): void => {
    let entries: string[] = [];
    try {
      entries = readdirSync(directory);
    } catch {
      return;
    }
    for (const name of entries) {
      const absolute = path.join(directory, name);
      const relative = prefix ? `${prefix}/${name}` : name;
      if (lstatSync(absolute).isDirectory()) stale(absolute, relative);
      else if (!keep.has(relative)) rmSync(absolute);
    }
  };
  stale(outRoot, "");
  for (const [relative, content] of files) {
    const target = path.join(outRoot, relative);
    let current: string | undefined;
    try {
      current = readFileSync(target, "utf-8");
    } catch {
      current = undefined;
    }
    if (current === content) continue;
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, content);
  }
}

export function assertBuilt(result: BuildResult): void {
  if (result.errors.length > 0) throw new ConversionFailedError(result.errors);
}
