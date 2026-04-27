#!/usr/bin/env node
/**
 * Deterministic fixture-corpus generator for the browser-functional
 * test suite.
 *
 * Copies source bundles from `test-fixtures/source/bundles/` into
 * `test-fixtures/.generated/source/bundles/`, applies controlled
 * metadata variants (trust labels, compare-invalid cohorts), and then
 * runs `benchbox explorer build` to produce the per-run read model at
 * `test-fixtures/.generated/data/`.
 *
 * Never touches:
 *   - results-explorer/public/data/
 *   - results-data/bundles/
 *
 * See docs/development/browser-test-architecture.md for the decision
 * record this generator implements.
 */

import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { readExplorerBuildContract } from "./explorer-build-contract.mjs";

const here = fileURLToPath(new URL(".", import.meta.url));
const projectRoot = resolve(here, "..");
const repoRoot = resolve(projectRoot, "..");

const sourceRoot = join(projectRoot, "test-fixtures", "source");
const sourceBundlesDir = join(sourceRoot, "bundles");
const genRoot = join(projectRoot, "test-fixtures", ".generated");
const genSourceRoot = join(genRoot, "source");
const genBundlesDir = join(genSourceRoot, "bundles");
const genDataDir = join(genRoot, "data");

const assertExplorerBuildContract = () => {
  const contract = readExplorerBuildContract();
  log(`validated explorer build contract ${contract.version} (${contract.command})`);
  return contract;
};

/**
 * Metadata variants applied to the generator output. Each entry takes a
 * source bundle filename and produces one or more derived bundles plus
 * optional sidecars. Variants are purely additive - the original bundle
 * is always copied verbatim so tests can rely on the known-good shape
 * for happy-path assertions.
 */
const VARIANTS = [
  {
    // Community-submission variant: derived from the TPC-H DuckDB bundle.
    // The explorer pipeline promotes every bundle that lives next to a
    // `submission-manifest.json` sidecar to `trust_label=community-submission`,
    // so the derived file must land in its own subdirectory to avoid
    // tainting the adjacent maintainer-run bundles.
    source: "tpch-duckdb-sf0.01-20260403-7fe93365.json",
    subdir: "community",
    derived: "tpch-duckdb-sf0.01-20260403-community.json",
    sidecars: {
      "submission-manifest.json": {
        version: "1",
        bundle: "tpch-duckdb-sf0.01-20260403-community.json",
        submitted_at: "2026-04-18T00:00:00Z",
        contributor: "browser-functional-test-fixture",
        note:
          "Synthetic community-submission variant produced by the browser-test fixture generator. " +
          "Do not treat as a real contribution.",
      },
    },
    mutate: (bundle) => {
      // Give the derived record a distinct run id so it does not collide
      // with its maintainer-run ancestor.
      const mutated = structuredClone(bundle);
      if (mutated.run) {
        mutated.run.id = `${mutated.run.id ?? "run"}-community`;
      }
      return mutated;
    },
  },
  {
    // Tuned variant: derived from the TPC-H DuckDB bundle with
    // `config.tuning_mode="tuned"` and a sibling `.tuning.json` sidecar
    // so the pipeline sets `has_tuning=true`. The failure-injection suite
    // uses this to exercise the sidecar fetch-error path on ResultDetail.
    // A per-variant subdirectory keeps the tuning sidecar scoped to this
    // one bundle.
    source: "tpch-duckdb-sf0.01-20260403-7fe93365.json",
    subdir: "tuned",
    derived: "tpch-duckdb-sf0.01-20260403-tuned.json",
    sidecars: {
      "tpch-duckdb-sf0.01-20260403-tuned.tuning.json": {
        tuning_mode: "tuned",
        memory_limit: "4GB",
        threads: 4,
        notes:
          "Synthetic tuning config produced by the browser-test fixture " +
          "generator. Do not treat as a real contribution.",
      },
    },
    mutate: (bundle) => {
      const mutated = structuredClone(bundle);
      mutated.config = { ...(mutated.config ?? {}), tuning_mode: "tuned" };
      if (mutated.run) {
        mutated.run.id = `${mutated.run.id ?? "run"}-tuned`;
      }
      return mutated;
    },
  },
  {
    // Scale-factor variant: same TPC-H DuckDB bundle rewritten to SF 0.1.
    // The compare-scale-mismatch failure test pairs this with an SF 0.01
    // bundle to exercise the hard-block path that jsdom cannot reach.
    source: "tpch-duckdb-sf0.01-20260403-7fe93365.json",
    subdir: "sf01",
    derived: "tpch-duckdb-sf0.1-20260403-scale.json",
    mutate: (bundle) => {
      const mutated = structuredClone(bundle);
      if (mutated.benchmark) {
        mutated.benchmark.scale_factor = 0.1;
      }
      if (mutated.run) {
        mutated.run.id = `${mutated.run.id ?? "run"}-sf01`;
      }
      return mutated;
    },
  },
];

const log = (...args) => console.log("[generate-browser-fixtures]", ...args);

const wipeGenerated = () => {
  if (existsSync(genRoot)) {
    rmSync(genRoot, { recursive: true, force: true });
  }
  mkdirSync(genBundlesDir, { recursive: true });
  mkdirSync(genDataDir, { recursive: true });
};

const copySources = () => {
  const entries = readdirSync(sourceBundlesDir, { withFileTypes: true });
  const files = entries.filter((e) => e.isFile() && e.name.endsWith(".json"));
  if (files.length === 0) {
    throw new Error(`no source bundles found under ${sourceBundlesDir}`);
  }
  for (const entry of files) {
    cpSync(join(sourceBundlesDir, entry.name), join(genBundlesDir, entry.name));
  }
  log(`copied ${files.length} source bundle(s)`);
};

const writeVariants = () => {
  for (const variant of VARIANTS) {
    const sourcePath = join(sourceBundlesDir, variant.source);
    if (!existsSync(sourcePath)) {
      throw new Error(`variant source not found: ${sourcePath}`);
    }
    const targetDir = variant.subdir ? join(genBundlesDir, variant.subdir) : genBundlesDir;
    mkdirSync(targetDir, { recursive: true });

    const bundle = JSON.parse(readFileSync(sourcePath, "utf8"));
    const mutated = variant.mutate ? variant.mutate(bundle) : bundle;
    writeFileSync(join(targetDir, variant.derived), JSON.stringify(mutated, null, 2));

    for (const [sidecarName, payload] of Object.entries(variant.sidecars ?? {})) {
      writeFileSync(join(targetDir, sidecarName), JSON.stringify(payload, null, 2));
    }
    log(`wrote variant ${variant.subdir ?? "."}/${variant.derived}`);
  }
};

const runPipeline = (contract) => {
  const args = ["run", "--", ...contract.commandArgs, "--data-dir", genSourceRoot, "--output", genDataDir];
  log(`uv ${args.join(" ")} (cwd=${repoRoot})`);
  const result = spawnSync("uv", args, {
    cwd: repoRoot,
    stdio: "inherit",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  if (result.status !== 0) {
    throw new Error(`benchbox explorer build failed (exit ${result.status})`);
  }
};

const main = () => {
  log(`sourceRoot=${sourceRoot}`);
  log(`genRoot=${genRoot}`);
  const contract = assertExplorerBuildContract();
  wipeGenerated();
  copySources();
  writeVariants();
  runPipeline(contract);

  // Sanity: pipeline must have produced at least the DuckDB snapshot.
  const duckdbPath = join(genDataDir, "results.duckdb");
  if (!existsSync(duckdbPath)) {
    throw new Error(`pipeline did not produce ${duckdbPath}`);
  }
  log(`generated ${duckdbPath}`);
};

try {
  main();
} catch (err) {
  console.error("[generate-browser-fixtures] failed:", err?.message ?? err);
  process.exit(1);
}
