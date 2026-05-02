#!/usr/bin/env node
/**
 * Post-generation invariant and determinism checks for the browser-test
 * fixture corpus.
 *
 * Run after `generate-browser-fixtures.mjs`. Fails if the generated
 * corpus does not satisfy the minimum contract the browser suite
 * depends on:
 *   - at least one benchmark × scale has ≥3 distinct platforms
 *     (compare happy-path cohort)
 *   - at least two benchmarks exist (compare-invalid benchmark-mismatch
 *     cohort source)
 *   - both `maintainer-run` and `community-submission` trust labels are
 *     represented (trust-badge coverage)
 *   - a second generator run produces the same fixture tree. JSON files
 *     must be byte-identical. `data/results.duckdb` is the only allowed
 *     byte-level exception because DuckDB container bytes include storage
 *     metadata; its logical table digest must still be identical.
 */

import {
  cpSync,
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const projectRoot = resolve(here, "..");
const repoRoot = resolve(projectRoot, "..");
const genRoot = join(projectRoot, "test-fixtures", ".generated");
const dbRelativePath = "data/results.duckdb";
const dbPath = join(genRoot, ...dbRelativePath.split("/"));
const generatorPath = join(projectRoot, "scripts", "generate-browser-fixtures.mjs");

const BYTE_DIFF_ALLOWLIST = new Map([
  [
    dbRelativePath,
    "DuckDB file bytes include nondeterministic container metadata; logical table digest is compared instead.",
  ],
]);

if (!existsSync(dbPath)) {
  console.error(`[verify-browser-fixtures] missing ${dbPath} - run the generator first.`);
  process.exit(2);
}

const fixtureSummaryPython = `
import duckdb, json, sys
from pathlib import Path

db_path = Path(sys.argv[1])
con = duckdb.connect(str(db_path), read_only=True)

platforms_per_cohort = con.execute(
    "SELECT benchmark, scale_factor, COUNT(DISTINCT platform_id) FROM results GROUP BY 1,2"
).fetchall()
benchmarks = [row[0] for row in con.execute(
    "SELECT DISTINCT benchmark FROM results ORDER BY 1"
).fetchall()]
trust_labels = {row[0] for row in con.execute(
    "SELECT DISTINCT trust_label FROM results"
).fetchall()}

result = {
    "platforms_per_cohort": platforms_per_cohort,
    "benchmarks": benchmarks,
    "trust_labels": sorted(trust_labels),
}
print(json.dumps(result))
`.trim();

const logicalDigestPython = `
import datetime
import decimal
import duckdb
import hashlib
import json
import sys
from pathlib import Path

def normalize(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize(val) for key, val in sorted(value.items())}
    return value

def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'

db_path = Path(sys.argv[1])
con = duckdb.connect(str(db_path), read_only=True)
tables = sorted(row[0] for row in con.execute("SHOW TABLES").fetchall())
payload = {}
for table in tables:
    result = con.execute(f"SELECT * FROM {quote_ident(table)} ORDER BY ALL")
    columns = [description[0] for description in result.description]
    rows = [[normalize(value) for value in row] for row in result.fetchall()]
    payload[table] = {"columns": columns, "rows": rows}

body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
print(json.dumps({"sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "tables": tables}))
`.trim();

function runUvPythonJson(source, args) {
  const proc = spawnSync("uv", ["run", "--", "python", "-c", source, ...args], {
    cwd: repoRoot,
    encoding: "utf8",
  });
  if (proc.status !== 0) {
    throw new Error(proc.stderr || `uv python failed (exit ${proc.status})`);
  }
  return JSON.parse(proc.stdout.trim().split("\n").pop());
}

function verifyFixtureInvariants() {
  const data = runUvPythonJson(fixtureSummaryPython, [dbPath]);
  const errors = [];
  const comparableCohort = data.platforms_per_cohort.find(([, , count]) => count >= 3);
  if (!comparableCohort) {
    errors.push("no benchmark × scale has ≥3 distinct platforms (compare happy-path needs one)");
  }
  if (data.benchmarks.length < 2) {
    errors.push(`only ${data.benchmarks.length} benchmark(s) present; compare-invalid test needs ≥2`);
  }
  for (const required of ["maintainer-run", "community-submission"]) {
    if (!data.trust_labels.includes(required)) {
      errors.push(`trust_label="${required}" missing from corpus`);
    }
  }

  if (errors.length) {
    console.error("[verify-browser-fixtures] fixture corpus invariants failed:");
    for (const error of errors) console.error("  -", error);
    console.error("  observed:", JSON.stringify(data));
    process.exit(1);
  }

  console.log("[verify-browser-fixtures] OK", JSON.stringify(data));
}

function verifyFixtureDeterminism() {
  const tempRoot = mkdtempSync(join(tmpdir(), "benchbox-browser-fixtures-"));
  const firstRoot = join(tempRoot, "first");
  cpSync(genRoot, firstRoot, { recursive: true });

  try {
    runGenerator();
    const errors = compareFixtureTrees(firstRoot, genRoot);
    if (errors.length) {
      console.error("[verify-browser-fixtures] fixture determinism failed:");
      for (const error of errors) console.error("  -", error);
      throw new Error("fixture determinism failed");
    }
    console.log(
      "[verify-browser-fixtures] determinism OK",
      JSON.stringify({ allowlist: Object.fromEntries(BYTE_DIFF_ALLOWLIST) }),
    );
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
}

function runGenerator() {
  const proc = spawnSync(process.execPath, [generatorPath], {
    cwd: projectRoot,
    stdio: "inherit",
    env: { ...process.env },
  });
  if (proc.status !== 0) {
    throw new Error(`fixture regeneration failed (exit ${proc.status})`);
  }
}

function compareFixtureTrees(firstRoot, secondRoot) {
  const errors = [];
  const firstFiles = listFiles(firstRoot);
  const secondFiles = listFiles(secondRoot);
  const firstSet = new Set(firstFiles);
  const secondSet = new Set(secondFiles);

  for (const file of firstFiles) {
    if (!secondSet.has(file)) errors.push(`missing after regeneration: ${file}`);
  }
  for (const file of secondFiles) {
    if (!firstSet.has(file)) errors.push(`new after regeneration: ${file}`);
  }
  if (errors.length) return errors;

  for (const file of firstFiles) {
    const firstPath = join(firstRoot, ...file.split("/"));
    const secondPath = join(secondRoot, ...file.split("/"));
    if (BYTE_DIFF_ALLOWLIST.has(file)) {
      const firstDigest = runUvPythonJson(logicalDigestPython, [firstPath]);
      const secondDigest = runUvPythonJson(logicalDigestPython, [secondPath]);
      if (firstDigest.sha256 !== secondDigest.sha256) {
        errors.push(`logical DuckDB digest changed for ${file}: ${firstDigest.sha256} != ${secondDigest.sha256}`);
      }
      continue;
    }
    const firstBytes = readFileSync(firstPath);
    const secondBytes = readFileSync(secondPath);
    if (!firstBytes.equals(secondBytes)) {
      errors.push(`byte content changed for ${file}`);
    }
  }
  return errors;
}

function listFiles(root) {
  const files = [];
  const visit = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        visit(fullPath);
      } else if (entry.isFile()) {
        files.push(relative(root, fullPath).split(sep).join("/"));
      }
    }
  };
  visit(root);
  return files.sort();
}

try {
  verifyFixtureInvariants();
  verifyFixtureDeterminism();
} catch (error) {
  console.error("[verify-browser-fixtures] failed:", error?.message ?? error);
  process.exit(1);
}
