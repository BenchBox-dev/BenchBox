#!/usr/bin/env node
import { existsSync, statSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const here = fileURLToPath(new URL(".", import.meta.url));
const explorerRoot = resolve(here, "..");
const repoRoot = resolve(explorerRoot, "..");
const snapshotPath = resolve(explorerRoot, "public", "data", "results.duckdb");
const sourceRoots = [
  resolve(repoRoot, "results-data", "bundles"),
  resolve(repoRoot, "_project", "scripts", "explorer_pipeline"),
];
const sourceFiles = [
  resolve(repoRoot, "_project", "scripts", "explorer_publish.py"),
  resolve(explorerRoot, "scripts", "explorer-build-contract.mjs"),
];

function log(message) {
  console.log(`[explorer-dev-snapshot] ${message}`);
}

async function newestMtimeMs(paths) {
  let newest = 0;
  for (const item of paths) {
    newest = Math.max(newest, await newestPathMtimeMs(item));
  }
  return newest;
}

async function newestPathMtimeMs(path) {
  if (!existsSync(path)) return 0;
  const stat = statSync(path);
  if (!stat.isDirectory()) return stat.mtimeMs;

  let newest = stat.mtimeMs;
  for (const entry of await readdir(path, { withFileTypes: true })) {
    newest = Math.max(newest, await newestPathMtimeMs(join(path, entry.name)));
  }
  return newest;
}

async function snapshotIsFresh() {
  if (!existsSync(snapshotPath)) return false;
  const snapshotMtime = statSync(snapshotPath).mtimeMs;
  const sourceMtime = await newestMtimeMs([...sourceRoots, ...sourceFiles]);
  return snapshotMtime >= sourceMtime;
}

function rebuildSnapshot() {
  const args = [
    "run",
    "--",
    "python",
    "_project/scripts/explorer_publish.py",
    "build",
    "--data-dir",
    "results-data",
    "--output",
    "results-explorer/public/data",
  ];
  log(`uv ${args.join(" ")}`);
  const result = spawnSync("uv", args, {
    cwd: repoRoot,
    stdio: "inherit",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  if (result.error && result.error.code === "ENOENT") {
    throw new Error(
      "Explorer dev snapshot rebuild needs `uv`, which was not found on PATH. " +
        "Install uv (https://docs.astral.sh/uv/) or set EXPLORER_SKIP_PREDEV=1 to skip " +
        "the rebuild and accept a stale/missing local snapshot.",
    );
  }
  if (result.status !== 0) {
    throw new Error(`Explorer dev snapshot rebuild failed with exit ${result.status ?? "unknown"}`);
  }
}

if (process.env.EXPLORER_SKIP_PREDEV === "1") {
  log("skipped by EXPLORER_SKIP_PREDEV=1");
} else if (await snapshotIsFresh()) {
  log("snapshot is current");
} else {
  log("snapshot missing or stale; rebuilding");
  rebuildSnapshot();
}
