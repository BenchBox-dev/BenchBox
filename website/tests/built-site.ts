import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dist = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "dist");

export function builtSite(): string | undefined {
  if (existsSync(path.join(dist, "index.html"))) return dist;
  if (process.env.CI && !process.env.BENCHBOX_SITE_UNBUILT) throw new Error(`built site is required in CI but missing: ${dist}`);
  return undefined;
}
