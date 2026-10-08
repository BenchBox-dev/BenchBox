// @vitest-environment node

import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const MISSPELLED_ATTRIBUTES: Readonly<Record<string, string>> = {
  textAnchor: "text-anchor",
  strokeWidth: "stroke-width",
  strokeDasharray: "stroke-dasharray",
  strokeLinecap: "stroke-linecap",
  strokeLinejoin: "stroke-linejoin",
  strokeOpacity: "stroke-opacity",
  strokeMiterlimit: "stroke-miterlimit",
  fillOpacity: "fill-opacity",
  fillRule: "fill-rule",
  dominantBaseline: "dominant-baseline",
  alignmentBaseline: "alignment-baseline",
  letterSpacing: "letter-spacing",
  clipPath: "clip-path",
  stopColor: "stop-color",
  stopOpacity: "stop-opacity",
  vectorEffect: "vector-effect",
  shapeRendering: "shape-rendering",
  paintOrder: "paint-order",
  markerStart: "marker-start",
  markerEnd: "marker-end",
};

const here = fileURLToPath(new URL(".", import.meta.url));
const srcRoot = resolve(here, "..");

function collectSources(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__tests__" || entry.name === "test") continue;
      collectSources(full, found);
    } else if (entry.name.endsWith(".tsx")) {
      found.push(full);
    }
  }
  return found;
}

describe("SVG attribute hygiene", () => {
  it("writes every SVG presentation attribute under the name SVG reads", () => {
    const offences: string[] = [];

    for (const file of collectSources(srcRoot)) {
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, index) => {
        for (const [camel, kebab] of Object.entries(MISSPELLED_ATTRIBUTES)) {
          if (new RegExp(`\\b${camel}=`).test(line)) {
            offences.push(
              `${relative(srcRoot, file)}:${index + 1} uses ${camel}= (write ${kebab}=)`,
            );
          }
        }
      });
    }

    expect(offences).toStrictEqual([]);
  });
});
