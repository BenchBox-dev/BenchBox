#!/usr/bin/env node
import { existsSync, statSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

import { EXPECTED_READ_MODEL_VERSION } from "./explorer-build-contract.mjs";

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
  if (snapshotMtime < sourceMtime) return false;

  const readModelVersion = readSnapshotReadModelVersion();
  if (readModelVersion !== EXPECTED_READ_MODEL_VERSION) {
    log(
      `snapshot read-model v${readModelVersion ?? "unknown"} does not match ` +
        `expected v${EXPECTED_READ_MODEL_VERSION}`,
    );
    return false;
  }
  return true;
}

function runUv(args, action) {
  if (action === "validation") {
    log("validating snapshot read-model version");
  } else {
    log(`uv ${args.join(" ")}`);
  }
  const result = spawnSync("uv", args, {
    cwd: repoRoot,
    encoding: "utf8",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: action === "rebuild" ? "inherit" : "pipe",
  });
  if (result.error && result.error.code === "ENOENT") {
    throw new Error(
      `Explorer dev snapshot ${action} needs \`uv\`, which was not found on PATH. ` +
        "Install uv (https://docs.astral.sh/uv/) or set EXPLORER_SKIP_PREDEV=1 to skip " +
        "the rebuild and accept a stale/missing local snapshot.",
    );
  }
  return result;
}

function readSnapshotReadModelVersion() {
  const probe = [
    "run",
    "--",
    "python",
    "-c",
    [
      "import duckdb, sys",
      "path = sys.argv[1]",
      "with duckdb.connect(path, read_only=True) as con:",
      "    row = con.execute('SELECT read_model_version FROM metadata LIMIT 1').fetchone()",
      "print(row[0] if row else 0)",
    ].join("\n"),
    snapshotPath,
  ];
  const result = runUv(probe, "validation");
  if (result.status !== 0) {
    return null;
  }
  const version = Number(result.stdout.trim());
  return Number.isInteger(version) && version >= 0 ? version : null;
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
  const result = runUv(args, "rebuild");
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
