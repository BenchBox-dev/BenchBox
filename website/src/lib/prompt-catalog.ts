import { readFileSync } from "node:fs";
import path from "node:path";
import type { Catalog } from "./prompt-builder.ts";

const generated = path.resolve(process.cwd(), "..", "landing", "prompts", "catalog.generated.js");
const ASSIGNMENT = /window\.__BENCHBOX_PROMPT_CATALOG__\s*=\s*/;

export function parseCatalogSource(source: string): Catalog {
  const match = ASSIGNMENT.exec(source);
  if (!match) throw new Error("catalog.generated.js does not assign window.__BENCHBOX_PROMPT_CATALOG__");
  const json = source.slice(match.index + match[0].length).trim().replace(/;$/, "");
  return JSON.parse(json) as Catalog;
}

export function loadPromptCatalog(file: string = generated): Catalog {
  return parseCatalogSource(readFileSync(file, "utf-8"));
}
