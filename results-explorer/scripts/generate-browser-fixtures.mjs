#!/usr/bin/env node
/**
 * Deterministic fixture-corpus generator for the browser-functional
 * test suite.
 *
 * Copies source bundles from `test-fixtures/source/bundles/` into
 * `test-fixtures/.generated/source/bundles/`, applies controlled
 * metadata variants (trust labels, compare-invalid cohorts), and then
 * runs `uv run -- python _project/scripts/explorer_publish.py build` to
 * produce the per-run read model at `test-fixtures/.generated/data/`.
 *
 * Never touches:
 *   - results-explorer/public/data/
 *   - results-data/bundles/
 *
 * See docs/development/browser-test-architecture.md for the decision
 * record this generator implements.
 */

import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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
  {
    // Partial query-coverage variant: derived from the TPC-H DataFusion
    // bundle with Q22 omitted. The follow-up usability release gate uses
    // this to exercise Compare's normalized-speedup "Comparable only"
    // default with a real browser corpus row that has at least one hidden
    // partial query.
    source: "tpch-datafusion-sf0.01-20260403-c0d4f3d9.json",
    subdir: "partial-query",
    derived: "tpch-datafusion-partial-sf0.01-20260403-query-gap.json",
    mutate: (bundle) => {
      const mutated = omitMeasurementQuery(bundle, "22");
      mutated.platform = {
        ...(mutated.platform ?? {}),
        name: "DataFusion Partial",
      };
      if (mutated.run) {
        mutated.run.id = `${mutated.run.id ?? "run"}-partial-query`;
      }
      return mutated;
    },
  },
  {
    // Synthetic AWS managed-cloud variant: fixture-only coverage for the
    // environment facets flattened into the browser snapshot. This never
    // touches the public corpus.
    source: "tpch-duckdb-sf0.01-20260403-7fe93365.json",
    subdir: "environment/aws-cloud",
    derived: "tpch-fixture-aws-sf0.01-20260403-environment.json",
    sidecars: {
      "submission-manifest.json": {
        version: "1",
        bundle: "tpch-fixture-aws-sf0.01-20260403-environment.json",
        submitted_at: "2026-05-03T00:00:00Z",
        contributor: "browser-functional-test-fixture",
        note:
          "Synthetic AWS environment-facet variant produced by the browser-test fixture generator. " +
          "Do not treat as a real cloud benchmark result.",
      },
    },
    mutate: (bundle) =>
      withEnvironmentFacetVariant(bundle, {
        runSuffix: "env-aws-cloud",
        platformName: "Fixture AWS SQL",
        runtimeType: "managed_cloud",
        deployment: {
          deployment_type: "managed_cloud",
          connection_mode: "cloud_endpoint",
          endpoint_class: "cloud_endpoint",
          metadata_source: "fixture",
          collection_status: "available",
        },
        cloud: {
          provider: "aws",
          region: "us-east-1",
          source: "fixture",
          collection_status: "available",
        },
        compute: {
          node_type: "m6i.large",
          source: "fixture",
          collection_status: "available",
        },
        storage: {
          table_format: "parquet",
          source: "fixture",
          collection_status: "available",
        },
      }),
  },
  {
    // Synthetic GCP serverless variant: exercises a second cloud provider,
    // region, and compute-shape source path.
    source: "tpch-duckdb-sf0.01-20260403-7fe93365.json",
    subdir: "environment/gcp-serverless",
    derived: "tpch-fixture-gcp-sf0.01-20260403-environment.json",
    sidecars: {
      "submission-manifest.json": {
        version: "1",
        bundle: "tpch-fixture-gcp-sf0.01-20260403-environment.json",
        submitted_at: "2026-05-03T00:00:00Z",
        contributor: "browser-functional-test-fixture",
        note:
          "Synthetic GCP serverless environment-facet variant produced by the browser-test fixture generator. " +
          "Do not treat as a real cloud benchmark result.",
      },
    },
    mutate: (bundle) =>
      withEnvironmentFacetVariant(bundle, {
        runSuffix: "env-gcp-serverless",
        platformName: "Fixture GCP Serverless",
        runtimeType: "serverless",
        deployment: {
          deployment_type: "serverless",
          connection_mode: "cloud_endpoint",
          endpoint_class: "cloud_endpoint",
          metadata_source: "fixture",
          collection_status: "available",
        },
        cloud: {
          provider: "gcp",
          region: "us-central1",
          source: "fixture",
          collection_status: "available",
        },
        compute: {
          serverless_slots: "serverless-slots-4",
          source: "fixture",
          collection_status: "available",
        },
        storage: {
          table_format: "parquet",
          source: "fixture",
          collection_status: "available",
        },
      }),
  },
  {
    // Synthetic provisioned-local/container-source variant: this remains
    // `deployment_class=local` under the current flattened contract while
    // carrying normalized runtime metadata for future runtime facets.
    source: "tpch-duckdb-sf0.01-20260403-7fe93365.json",
    subdir: "environment/container-local",
    derived: "tpch-fixture-container-sf0.01-20260403-environment.json",
    mutate: (bundle) =>
      withEnvironmentFacetVariant(bundle, {
        runSuffix: "env-container-local",
        platformName: "Fixture Container SQL",
        runtimeType: "docker_container",
        deployment: {
          deployment_type: "embedded",
          connection_mode: "localhost",
          endpoint_class: "localhost_port",
          metadata_source: "fixture",
          collection_status: "available",
        },
        cloud: {
          source: "unavailable",
          collection_status: "unavailable",
        },
        compute: {
          node_type: "container-cpu-10",
          source: "fixture",
          collection_status: "available",
        },
        storage: {
          table_format: "duckdb_native",
          source: "fixture",
          collection_status: "available",
        },
        container: {
          image: "benchbox/results-explorer-fixture:local",
          runtime: "docker",
          source: "fixture",
          collection_status: "available",
        },
      }),
  },
];

const log = (...args) => console.log("[generate-browser-fixtures]", ...args);

const LOCAL_PLATFORM_METADATA = {
  duckdb: {
    runtimeType: "local_process",
    deployment: {
      deployment_type: "embedded",
      connection_mode: "file",
      endpoint_class: "embedded_process",
      metadata_source: "observed",
      collection_status: "available",
    },
    storage: {
      table_format: "duckdb_native",
      source: "inferred",
      collection_status: "partial",
    },
  },
  datafusion: {
    runtimeType: "dataframe_process",
    deployment: {
      deployment_type: "embedded",
      connection_mode: "dataframe",
      endpoint_class: "embedded_process",
      metadata_source: "observed",
      collection_status: "available",
    },
    storage: {
      table_format: "parquet",
      source: "inferred",
      collection_status: "partial",
    },
  },
  polars: {
    runtimeType: "dataframe_process",
    deployment: {
      deployment_type: "embedded",
      connection_mode: "dataframe",
      endpoint_class: "embedded_process",
      metadata_source: "observed",
      collection_status: "available",
    },
    storage: {
      table_format: "parquet",
      source: "inferred",
      collection_status: "partial",
    },
  },
};

const platformKey = (bundle) => {
  const name = String(bundle.platform?.name ?? "").toLowerCase();
  if (name.includes("datafusion")) return "datafusion";
  if (name.includes("polars")) return "polars";
  return "duckdb";
};

const clientHostFromLegacy = (environment) => {
  if (!environment || typeof environment !== "object") return undefined;
  const clientHost = {
    os: environment.os,
    arch: environment.arch,
    cpu_count: environment.cpu_count,
    memory_gb: environment.memory_gb,
    python: environment.python,
    machine_id: environment.machine_id,
  };
  return Object.fromEntries(Object.entries(clientHost).filter(([, value]) => value !== undefined && value !== null));
};

const withEnvironmentFacetVariant = (bundle, options) => {
  const mutated = structuredClone(bundle);
  const environment = mutated.environment && typeof mutated.environment === "object" ? mutated.environment : {};
  const platform = mutated.platform && typeof mutated.platform === "object" ? mutated.platform : {};

  mutated.run = {
    ...(mutated.run ?? {}),
    id: `${mutated.run?.id ?? "run"}-${options.runSuffix}`,
  };
  mutated.platform = {
    ...platform,
    name: options.platformName,
    deployment: options.deployment,
    cloud: options.cloud,
    compute: options.compute,
    storage: options.storage,
  };
  mutated.environment = {
    ...environment,
    platform_runtime: {
      runtime_type: options.runtimeType,
      collection_status: "available",
      source: "fixture",
    },
    ...(options.container ? { container: options.container } : {}),
  };
  return mutated;
};

function omitMeasurementQuery(bundle, queryId) {
  const mutated = structuredClone(bundle);
  const queries = Array.isArray(mutated.queries) ? mutated.queries : [];
  const remaining = queries.filter((query) => String(query?.id ?? "") !== String(queryId));
  mutated.queries = remaining;

  const successful = remaining.filter((query) => String(query?.status ?? "").toUpperCase() === "SUCCESS");
  if (mutated.summary?.queries) {
    mutated.summary.queries = {
      ...mutated.summary.queries,
      total: remaining.length,
      passed: successful.length,
      failed: remaining.length - successful.length,
    };
  }

  return mutated;
}

const withNormalizedEnvironment = (bundle) => {
  const mutated = structuredClone(bundle);
  const metadata = LOCAL_PLATFORM_METADATA[platformKey(mutated)];
  const environment = mutated.environment && typeof mutated.environment === "object" ? mutated.environment : {};
  const platform = mutated.platform && typeof mutated.platform === "object" ? mutated.platform : {};

  mutated.environment = {
    ...environment,
    client_host: environment.client_host ?? clientHostFromLegacy(environment),
    platform_runtime: environment.platform_runtime ?? {
      runtime_type: metadata.runtimeType,
      collection_status: "available",
      source: "observed",
    },
  };
  mutated.platform = {
    ...platform,
    deployment: platform.deployment ?? metadata.deployment,
    cloud: platform.cloud ?? {
      source: "unavailable",
      collection_status: "unavailable",
    },
    compute: platform.compute ?? {
      source: "unavailable",
      collection_status: "unavailable",
    },
    storage: platform.storage ?? metadata.storage,
  };
  return mutated;
};

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
    const bundle = JSON.parse(readFileSync(join(sourceBundlesDir, entry.name), "utf8"));
    const normalized = withNormalizedEnvironment(bundle);
    writeFileSync(join(genBundlesDir, entry.name), JSON.stringify(normalized, null, 2));
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
    const variantBundle = variant.mutate ? variant.mutate(bundle) : bundle;
    const mutated = withNormalizedEnvironment(variantBundle);
    writeFileSync(join(targetDir, variant.derived), JSON.stringify(mutated, null, 2));

    for (const [sidecarName, payload] of Object.entries(variant.sidecars ?? {})) {
      writeFileSync(join(targetDir, sidecarName), JSON.stringify(payload, null, 2));
    }
    log(`wrote variant ${variant.subdir ?? "."}/${variant.derived}`);
  }
};

const runPipeline = (contract) => {
  const args = [...contract.commandArgs, "--data-dir", genSourceRoot, "--output", genDataDir];
  log(`${args.join(" ")} (cwd=${repoRoot})`);
  const result = spawnSync(args[0], args.slice(1), {
    cwd: repoRoot,
    stdio: "inherit",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  if (result.status !== 0) {
    throw new Error(`Explorer publish command failed (exit ${result.status})`);
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
