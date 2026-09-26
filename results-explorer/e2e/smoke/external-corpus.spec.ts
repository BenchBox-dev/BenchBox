import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";

import { expect, test } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

type BundleQuery = {
  id?: string;
  query_id?: string;
  status?: string;
  run_type?: string | null;
  stream?: number | string | null;
  test_type?: string | null;
};

type Bundle = {
  benchmark?: { id?: string; name?: string; scale_factor?: number; test_type?: string | null };
  phases?: { power_test?: unknown; throughput_test?: unknown };
  platform?: { name?: string };
  queries?: BundleQuery[];
};

type CorpusRouteSeed = {
  resultId: string;
  benchmarkId: string;
  benchmarkName: string;
  platformId: string;
  platformName: string;
  queryId?: string;
  /** Bundle test_type ("power" | "throughput" | ...), mirroring the pipeline's _test_type inference. */
  testType: string | null;
  /** Distinct stream ids across execution rows; empty when the bundle records none. */
  streamValues: string[];
  /** Execution rows the explorer ingests (run_type measurement/warmup/unlabelled), mirroring _query_timings. */
  executionRows: number;
};

test.describe("External corpus smoke", () => {
  test("@uat-external-corpus renders benchmark, platform, result, and query routes from mounted data", async ({
    page,
  }) => {
    const seed = discoverExternalCorpusSeed();

    await page.goto(`/results/${seed.benchmarkId}/`);
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: new RegExp(`${escapeRe(seed.benchmarkName)} Results`, "i") })).toBeVisible();
    await expect(page.getByRole("link", { name: new RegExp(escapeRe(seed.platformName), "i") }).first()).toBeVisible({
      timeout: 30_000,
    });

    await page.goto(`/results/p/${seed.platformId}/`);
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: new RegExp(`${escapeRe(seed.platformName)} Results`, "i") })).toBeVisible();
    await expect(page.getByTestId("platform-run-count")).toBeVisible({ timeout: 30_000 });

    await page.goto(`/results/r/${seed.resultId}`);
    await waitForShell(page);
    await waitForDataLoaded(
      page,
      new RegExp(`${escapeRe(seed.benchmarkName)} result:\\s+${escapeRe(seed.platformName)}`, "i"),
    );
    await expect(page.getByRole("heading", { name: /Query timings/i })).toBeVisible();
    if (seed.queryId) {
      await expect(page.getByRole("main").getByText(seed.queryId, { exact: true }).first()).toBeVisible();
    }

    await page.goto("/results/query");
    await waitForShell(page);
    await waitForDataLoaded(page, /matching run/);
    await expect(page.getByRole("main").getByText(seed.platformName, { exact: true }).first()).toBeVisible();
  });

  test("@uat-external-corpus renders throughput phase and stream data from mounted bundle", async ({ page }) => {
    const seed = discoverExternalCorpusSeed();
    // Only throughput corpora (e.g. the throughput-phase explorer sweep) can
    // exercise this path; other sweeps keep the generic route coverage above.
    test.skip(seed.testType !== "throughput", "mounted corpus has no throughput bundle");

    await page.goto(`/results/r/${seed.resultId}`);
    await waitForShell(page);
    await waitForDataLoaded(
      page,
      new RegExp(`${escapeRe(seed.benchmarkName)} result:\\s+${escapeRe(seed.platformName)}`, "i"),
    );

    // The bundle's test_type must survive the pipeline onto the result page:
    // subtitle names the phase and the run receipt records it.
    await expect(page.getByText(/throughput phase/i)).toBeVisible();
    const receipt = page.locator("#run-receipt");
    await expect(receipt.getByText("throughput", { exact: true }).first()).toBeVisible();

    // Every per-stream execution in the bundle must reach the page. The
    // "Individual samples" disclosure counts detail.queries, which the
    // pipeline fills from all measurement/warmup execution rows, so a dropped
    // or misclassified stream changes the count.
    test.skip(seed.streamValues.length < 2, "throughput bundle records fewer than two streams");
    await expect(page.getByText(`Individual samples (${seed.executionRows})`)).toBeVisible();
  });
});

function discoverExternalCorpusSeed(): CorpusRouteSeed {
  const fixtureDir = resolve(
    process.env.E2E_FIXTURE_DIR ?? join(process.cwd(), "test-fixtures", ".generated", "data"),
  );
  const dbPath = join(fixtureDir, "results.duckdb");
  const bundlesDir = join(fixtureDir, "bundles");
  if (!existsSync(dbPath)) throw new Error(`external corpus missing results.duckdb: ${dbPath}`);
  if (!existsSync(bundlesDir)) throw new Error(`external corpus missing bundles directory: ${bundlesDir}`);

  const bundleFiles = readdirSync(bundlesDir)
    .filter((name) => name.endsWith(".json") && !name.endsWith(".plans.json"))
    .sort();
  if (bundleFiles.length === 0) throw new Error(`external corpus has no bundle JSON files: ${bundlesDir}`);

  let first: CorpusRouteSeed | undefined;
  for (const fileName of bundleFiles) {
    const bundle = JSON.parse(readFileSync(join(bundlesDir, fileName), "utf8")) as Bundle;
    const benchmarkId = bundle.benchmark?.id;
    const platformName = bundle.platform?.name;
    if (!benchmarkId || !platformName) continue;
    const firstQuery = bundle.queries?.find((query) => (query.id ?? query.query_id) && query.status !== "FAILED");
    const queryId = firstQuery?.id ?? firstQuery?.query_id;
    const seed: CorpusRouteSeed = {
      resultId: basename(fileName, ".json"),
      benchmarkId,
      benchmarkName: humanizeBenchmark(benchmarkId),
      platformId: platformId(platformName),
      platformName,
      queryId,
      testType: inferTestType(bundle),
      streamValues: distinctStreams(bundle.queries),
      executionRows: countExecutionRows(bundle.queries),
    };
    // Prefer a throughput bundle so the throughput-rendering test below has a
    // seed; otherwise keep the first routable bundle for generic coverage.
    if (seed.testType === "throughput") return seed;
    first ??= seed;
  }
  if (!first) throw new Error(`external corpus has no routable benchmark/platform bundles: ${bundlesDir}`);
  return first;
}

function platformId(raw: string): string {
  return raw.replace(/[-_]trust[-_](ci|community|local|unknown)/gi, "").trim().toLowerCase().replaceAll(" ", "-");
}

/** Mirror the explorer pipeline's `_test_type` inference (benchmark.test_type wins, then phases). */
function inferTestType(bundle: Bundle): string | null {
  const declared = bundle.benchmark?.test_type;
  if (declared) return String(declared);
  if (bundle.phases) {
    if (bundle.phases.power_test) return "power";
    if (bundle.phases.throughput_test) return "throughput";
  }
  return null;
}

/** Execution rows the pipeline ingests: measurement, warmup, or unlabelled legacy rows. */
function isExecutionRow(query: BundleQuery): boolean {
  return query.run_type === undefined || query.run_type === null || query.run_type === "measurement" ||
    query.run_type === "warmup";
}

function distinctStreams(queries: BundleQuery[] | undefined): string[] {
  const values = new Set<string>();
  for (const query of queries ?? []) {
    if (!isExecutionRow(query) || query.stream === undefined || query.stream === null) continue;
    const text = String(query.stream).trim();
    // Mirror the pipeline's int(stream) coercion: only numeric stream ids
    // survive ingestion, so only they can prove multi-stream rendering.
    if (text !== "" && Number.isInteger(Number(text))) values.add(String(Number(text)));
  }
  return [...values].sort();
}

function countExecutionRows(queries: BundleQuery[] | undefined): number {
  return (queries ?? []).filter(isExecutionRow).length;
}

function humanizeBenchmark(raw: string): string {
  const labels: Record<string, string> = {
    amplab: "AMPLab",
    clickbench: "ClickBench",
    coffeeshop: "CoffeeShop",
    datavault: "TPC-H Data Vault",
    flightdata: "Flight Data",
    h2odb: "H2ODB",
    joinorder: "JoinOrder",
    metadata_primitives: "Metadata",
    nyctaxi: "NYC Taxi",
    read_primitives: "Read Primitives",
    star_schema: "SSB",
    ssb: "SSB",
    tsbs_devops: "TSBS DevOps",
    tpcdi: "TPC-DI",
    tpcds: "TPC-DS",
    tpcds_obt: "TPC-DS-OBT",
    tpch: "TPC-H",
    tpch_skew: "TPC-H Skew",
    tpchavoc: "TPC-Havoc",
    vector_search: "Vector Search",
  };
  return labels[raw] ?? raw.toUpperCase();
}

function escapeRe(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
