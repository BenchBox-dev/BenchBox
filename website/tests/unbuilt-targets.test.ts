import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { UNBUILT_TARGETS } from "../src/converter/handlers/links.ts";

const websiteRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

function pageFiles(directory: string): string[] {
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { recursive: true, encoding: "utf-8" }).map((entry) => entry.split(path.sep).join("/"));
}

describe("links rendered as text because their target is not built", () => {
  it.each(Object.keys(UNBUILT_TARGETS))("%s still has no Astro route; drop it from UNBUILT_TARGETS once it does", (target) => {
    const stem = path.posix.basename(target, ".html");
    const routes = pageFiles(path.join(websiteRoot, "src", "pages", path.posix.dirname(target))).filter((entry) => entry.replace(/\.astro$/, "").replace(/\/index$/, "") === stem || entry.startsWith(`${stem}/`) || entry.startsWith(`${stem}.`));
    expect(routes).toEqual([]);
    expect(existsSync(path.join(websiteRoot, "dist", target))).toBe(false);
  });
});
