import path from "node:path";
import { fileURLToPath } from "node:url";
import { assertBuilt, assertOwnedOutput, buildSite, clearOutput, loadKnownBrokenLinks, UnownedOutputError, writeOutput } from "./build.ts";
import { ConversionFailedError, constructOf } from "./errors.ts";

const websiteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

function option(name: string, fallback: string): string {
  const position = process.argv.indexOf(name);
  return position >= 0 && process.argv[position + 1] ? process.argv[position + 1] : fallback;
}

const docsRoot = path.resolve(option("--docs", path.join(websiteRoot, "..", "docs")));
const outRoot = path.resolve(option("--out", path.join(websiteRoot, ".generated")));
const showAll = process.argv.includes("--all");

try {
  assertOwnedOutput(outRoot);
} catch (error) {
  if (!(error instanceof UnownedOutputError)) throw error;
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
}

const knownBrokenLinks = loadKnownBrokenLinks(path.join(websiteRoot, "..", "_project", "design", "site-inventory", "known-broken-links.json"));

const result = buildSite({ docsRoot, knownBrokenLinks });

try {
  assertBuilt(result);
} catch (error) {
  if (!(error instanceof ConversionFailedError)) throw error;
  const byConstruct = new Map<string, typeof error.errors>();
  for (const failure of error.errors) {
    const group = byConstruct.get(constructOf(failure)) ?? [];
    byConstruct.set(constructOf(failure), [...group, failure]);
  }
  const lines: string[] = [];
  for (const [construct, failures] of [...byConstruct.entries()].sort((a, b) => b[1].length - a[1].length || (a[0] < b[0] ? -1 : 1))) {
    const files = new Set(failures.map((failure) => failure.file));
    lines.push(`${construct}: ${failures.length} occurrences in ${files.size} files`);
    for (const failure of showAll ? failures : failures.slice(0, 3)) lines.push(`  ${failure.message}`);
  }
  const files = new Set(error.errors.map((failure) => failure.file));
  lines.push(`${error.errors.length} errors in ${files.size} files`);
  clearOutput(outRoot);
  process.stderr.write(`${lines.join("\n")}\n`);
  process.exit(1);
}

writeOutput(outRoot, result.files);
process.stdout.write(`converted ${result.summary.pages} pages (${result.summary.md} md, ${result.summary.mdx} mdx) into ${path.relative(process.cwd(), outRoot) || "."}\n`);
