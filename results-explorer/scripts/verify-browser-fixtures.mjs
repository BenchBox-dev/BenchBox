#!/usr/bin/env node
/**
 * Post-generation invariant check for the browser-test fixture corpus.
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
 *
 * The check is deliberately narrow - the TODO and architecture note
 * define the minimum; wider variants can extend the fixture generator
 * and tighten these checks at the same time.
 */

import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const projectRoot = resolve(here, "..");
const repoRoot = resolve(projectRoot, "..");
const dbPath = join(projectRoot, "test-fixtures", ".generated", "data", "results.duckdb");

if (!existsSync(dbPath)) {
  console.error(`[verify-browser-fixtures] missing ${dbPath} - run the generator first.`);
  process.exit(2);
}

const pythonSrc = `
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

const proc = spawnSync("uv", ["run", "--", "python", "-c", pythonSrc, dbPath], {
  cwd: repoRoot,
  encoding: "utf8",
});
if (proc.status !== 0) {
  console.error(proc.stderr);
  process.exit(proc.status ?? 1);
}
const data = JSON.parse(proc.stdout.trim().split("\n").pop());

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
  for (const e of errors) console.error("  -", e);
  console.error("  observed:", JSON.stringify(data));
  process.exit(1);
}

console.log("[verify-browser-fixtures] OK", JSON.stringify(data));
