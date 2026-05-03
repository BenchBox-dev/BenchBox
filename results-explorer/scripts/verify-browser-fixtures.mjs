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
 *   - environment facets include fixture-only cloud/provider/region/shape
 *     coverage plus a normalized container runtime source
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
const genBundlesDir = join(genRoot, "source", "bundles");
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
environment_values = {}
for column in (
    "deployment_class",
    "cloud_provider",
    "cloud_region",
    "instance_or_warehouse",
    "storage_format",
):
    environment_values[column] = [
        row[0]
        for row in con.execute(
            f"SELECT DISTINCT {column} FROM results WHERE {column} IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
cloud_rows = con.execute(
    """
    SELECT
        result_id,
        platform,
        cloud_provider,
        cloud_region,
        instance_or_warehouse,
        storage_format,
        trust_label
    FROM results
    WHERE deployment_class = 'cloud'
    ORDER BY result_id
    """
).fetchall()
container_rows = con.execute(
    """
    SELECT
        result_id,
        platform,
        deployment_class,
        instance_or_warehouse,
        storage_format,
        trust_label
    FROM results
    WHERE platform = 'Fixture Container SQL'
    ORDER BY result_id
    """
).fetchall()

result = {
    "platforms_per_cohort": platforms_per_cohort,
    "benchmarks": benchmarks,
    "trust_labels": sorted(trust_labels),
    "environment_values": environment_values,
    "cloud_rows": cloud_rows,
    "container_rows": container_rows,
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
  verifyEnvironmentCoverage(data, errors);

  if (errors.length) {
    console.error("[verify-browser-fixtures] fixture corpus invariants failed:");
    for (const error of errors) console.error("  -", error);
    console.error("  observed:", JSON.stringify(data));
    process.exit(1);
  }

  console.log("[verify-browser-fixtures] OK", JSON.stringify(data));
}

function verifyEnvironmentCoverage(data, errors) {
  const values = data.environment_values ?? {};
  const requiredValues = {
    deployment_class: ["cloud", "local"],
    cloud_provider: ["aws", "gcp"],
    cloud_region: ["us-east-1", "us-central1"],
    instance_or_warehouse: ["m6i.large", "serverless-slots-4"],
    storage_format: ["duckdb_native", "parquet"],
  };
  for (const [facet, required] of Object.entries(requiredValues)) {
    const observed = new Set(values[facet] ?? []);
    for (const value of required) {
      if (!observed.has(value)) {
        errors.push(`environment facet ${facet} missing ${value}`);
      }
    }
  }

  const cloudRows = data.cloud_rows ?? [];
  if (cloudRows.length < 2) {
    errors.push(`expected at least two fixture cloud rows, observed ${cloudRows.length}`);
  }
  const nonCommunityCloudRows = cloudRows.filter(([, , , , , , trustLabel]) => trustLabel !== "community-submission");
  if (nonCommunityCloudRows.length) {
    errors.push("synthetic cloud fixture rows must be marked trust_label=community-submission");
  }

  const containerRows = data.container_rows ?? [];
  const hasContainerSnapshotRow = containerRows.some(
    ([, , deploymentClass, shape, storageFormat]) =>
      deploymentClass === "local" && shape === "container-cpu-10" && storageFormat === "duckdb_native",
  );
  if (!hasContainerSnapshotRow) {
    errors.push("container runtime fixture did not survive into the snapshot as a local container row");
  }

  const generatedBundles = generatedBundlePayloads();
  const runtimeTypes = new Set(
    generatedBundles.map((bundle) => bundle.environment?.platform_runtime?.runtime_type).filter(Boolean),
  );
  if (!runtimeTypes.has("docker_container")) {
    errors.push("generated source bundles lack a docker_container runtime fixture");
  }

  if (!errors.length) {
    console.log(
      "[verify-browser-fixtures] environment coverage OK",
      JSON.stringify({
        environment_values: values,
        cloud_rows: cloudRows.length,
        container_rows: containerRows.length,
        runtime_types: [...runtimeTypes].sort(),
      }),
    );
  }
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

function generatedBundlePayloads() {
  return listFiles(genBundlesDir)
    .filter((file) => isResultBundleJson(file))
    .map((file) => JSON.parse(readFileSync(join(genBundlesDir, ...file.split("/")), "utf8")));
}

function isResultBundleJson(file) {
  const name = file.split("/").pop() ?? "";
  return (
    name.endsWith(".json") &&
    name !== "submission-manifest.json" &&
    !name.endsWith(".manifest.json") &&
    !name.endsWith(".tuning.json")
  );
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
