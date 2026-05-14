import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";

import { expect, test } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

type Bundle = {
  benchmark?: { id?: string; name?: string; scale_factor?: number };
  platform?: { name?: string };
  queries?: Array<{ id?: string; status?: string }>;
};

type CorpusRouteSeed = {
  resultId: string;
  benchmarkId: string;
  benchmarkName: string;
  platformId: string;
  platformName: string;
  queryId?: string;
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
    await expect(page.getByText(/Showing \d+ of \d+ results/i)).toBeVisible({ timeout: 30_000 });

    await page.goto(`/results/r/${seed.resultId}`);
    await waitForShell(page);
    await waitForDataLoaded(
      page,
      new RegExp(`${escapeRe(seed.benchmarkName)}\\s+-\\s+${escapeRe(seed.platformName)}`, "i"),
    );
    await expect(page.getByRole("heading", { name: /Query Timings/i })).toBeVisible();
    if (seed.queryId) {
      await expect(page.getByRole("main").getByText(seed.queryId, { exact: true }).first()).toBeVisible();
    }

    await page.goto("/results/query");
    await waitForShell(page);
    await waitForDataLoaded(page, /matching result bundle/);
    await expect(page.getByRole("main").getByText(seed.platformName, { exact: true }).first()).toBeVisible();
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

  for (const fileName of bundleFiles) {
    const bundle = JSON.parse(readFileSync(join(bundlesDir, fileName), "utf8")) as Bundle;
    const benchmarkId = bundle.benchmark?.id;
    const platformName = bundle.platform?.name;
    if (!benchmarkId || !platformName) continue;
    return {
      resultId: basename(fileName, ".json"),
      benchmarkId,
      benchmarkName: humanizeBenchmark(benchmarkId),
      platformId: platformId(platformName),
      platformName,
      queryId: bundle.queries?.find((query) => query.id && query.status !== "FAILED")?.id,
    };
  }
  throw new Error(`external corpus has no routable benchmark/platform bundles: ${bundlesDir}`);
}

function platformId(raw: string): string {
  return raw.replace(/[-_]trust[-_](ci|community|local|unknown)/gi, "").trim().toLowerCase().replaceAll(" ", "-");
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
