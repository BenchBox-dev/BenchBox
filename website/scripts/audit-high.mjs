import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { main } from "../../results-explorer/scripts/audit-high.mjs";

const websiteRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");

function runNpmAudit() {
  const result = spawnSync("npm", ["audit", "--json", "--audit-level=high"], {
    cwd: websiteRoot,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  return JSON.parse(result.stdout);
}

function readAllowlist() {
  return JSON.parse(readFileSync(resolve(websiteRoot, "scripts", "audit-high-allowlist.json"), "utf8"));
}

process.exitCode = main({ audit: runNpmAudit, allowlist: readAllowlist });
