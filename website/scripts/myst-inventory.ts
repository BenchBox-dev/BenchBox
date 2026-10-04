import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { emptyInventory, scanFile, type Counter, type Inventory } from "../src/converter/inventory.ts";
import { listDocSources } from "../src/converter/sources.ts";

const docsRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "docs");
const queriesPrefix = "benchmarks/queries/";

function scanAll(include: (relative: string) => boolean): Inventory {
  const inventory = emptyInventory();
  for (const source of listDocSources(docsRoot)) {
    if (include(source.relative)) scanFile(inventory, source.relative, readFileSync(source.absolute, "utf-8"));
  }
  return inventory;
}

function sorted(counter: Counter): [string, number][] {
  return [...counter.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1));
}

function fileCount(inventory: Inventory, construct: string): number {
  return inventory.filesByConstruct.get(construct)?.size ?? 0;
}

function section(title: string, counter: Counter, inventory: Inventory, prefix: string | null): string[] {
  const lines = [`### ${title}`, "", "| construct | occurrences | files |", "| --- | ---: | ---: |"];
  for (const [name, count] of sorted(counter)) {
    const files = prefix === null ? "" : String(fileCount(inventory, `${prefix}${name}`));
    lines.push(`| \`${name}\` | ${count} | ${files} |`);
  }
  lines.push("");
  return lines;
}

function report(title: string, inventory: Inventory): string[] {
  const out = [`## ${title}`, "", `Files scanned: ${inventory.files}`, ""];
  out.push(...section("Directives", inventory.directives, inventory, "directive:"));
  out.push(...section("Directive options", inventory.directiveOptions, inventory, null));
  out.push(...section("Roles", inventory.roles, inventory, "role:"));
  out.push("### Labels and comments", "", `- \`(x)=\` labels: ${inventory.labels} in ${fileCount(inventory, "label")} files`);
  out.push(`- \`%\` comment lines: ${inventory.comments} in ${fileCount(inventory, "comment")} files`, "");
  out.push(...section("Front matter keys", inventory.frontMatterKeys, inventory, "front-matter:"));
  out.push(...section("myst: keys", inventory.mystKeys, inventory, null));
  out.push(...section("myst enable_extensions", inventory.enabledExtensions, inventory, "extension:"));
  out.push(...section("Raw HTML blocks (by first tag)", inventory.htmlBlocks, inventory, "html-block:"));
  out.push(...section("Inline HTML (by tag)", inventory.htmlInline, inventory, "html-inline:"));
  out.push(...section("Inside eval-rst: directives", inventory.evalRstDirectives, inventory, "eval-rst:"));
  out.push(...section("Inside eval-rst: roles", inventory.evalRstRoles, inventory, "eval-rst-role:"));
  out.push(...section("Inside eval-rst: other", inventory.evalRstOther, inventory, null));
  out.push(...section("Other syntax", inventory.syntax, inventory, null));
  out.push(...section("Links and images", inventory.links, inventory, null));
  return out;
}

const mode = process.argv[2] ?? "all";
const inventory =
  mode === "authored" ? scanAll((relative) => !relative.startsWith(queriesPrefix)) : mode === "queries" ? scanAll((relative) => relative.startsWith(queriesPrefix)) : scanAll(() => true);

if (process.argv.includes("--json")) {
  const replacer = (key: string, value: unknown) => {
    if (key === "filesByConstruct") return Object.fromEntries([...(value as Map<string, Set<string>>)].sort().map(([name, files]) => [name, [...files].sort()]));
    return value instanceof Map ? Object.fromEntries(sorted(value as Counter)) : value;
  };
  process.stdout.write(`${JSON.stringify(inventory, replacer, 2)}\n`);
} else {
  process.stdout.write(`${report(`MyST inventory (${mode})`, inventory).join("\n")}\n`);
}
