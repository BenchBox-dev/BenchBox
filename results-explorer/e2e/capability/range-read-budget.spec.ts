import { statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { waitForDataLoaded } from "../support/fixtures";

const here = fileURLToPath(new URL(".", import.meta.url));
const DUCKDB_PATH = join(here, "..", "..", "test-fixtures", ".generated", "data", "results.duckdb");

const DB_PATH = "/results/data/results.duckdb";
const BYTE_BUDGET_RATIO = 0.10;

interface TransferLogEntry {
  path: string;
  method: string;
  status: number;
  hasRange: boolean;
  contentLength: number;
}

test.describe("RG-2 range-read budget", () => {
  test.skip("a cold explorer load transfers <=10% of the snapshot via 206 ranged GETs", async ({
    page,
    request,
    baseURL,
  }) => {
    const base = baseURL ?? "http://127.0.0.1:4319";
    const dbSize = statSync(DUCKDB_PATH).size;

    const resetResp = await request.post(`${base}/__test/transfers/reset`);
    expect(resetResp.status()).toBe(204);

    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);

    const transfersResp = await request.get(`${base}/__test/transfers`);
    expect(transfersResp.status()).toBe(200);
    const transfers = (await transfersResp.json()) as TransferLogEntry[];
    const dbTransfers = transfers.filter((t) => t.path === DB_PATH && t.method === "GET");

    expect(
      dbTransfers.length,
      `expected at least one GET against ${DB_PATH} during the cold load`,
    ).toBeGreaterThan(0);

    const totalBytes = dbTransfers.reduce((sum, t) => sum + t.contentLength, 0);
    const budget = Math.floor(dbSize * BYTE_BUDGET_RATIO);
    expect(
      totalBytes,
      `cold-load transfer total ${totalBytes} bytes exceeded ${BYTE_BUDGET_RATIO * 100}% of ${dbSize}-byte DB (=${budget})`,
    ).toBeLessThanOrEqual(budget);

    expect(
      dbTransfers.some((t) => t.status === 206 && t.hasRange),
      `expected at least one 206 ranged response among ${dbTransfers.length} DB transfers`,
    ).toBe(true);
  });
});

test.describe("RG-2 range-read capability (diagnostic)", () => {
  test("the test server advertises Accept-Ranges and honours Range requests for the DuckDB snapshot", async ({
    request,
    baseURL,
  }) => {
    const base = baseURL ?? "http://127.0.0.1:4319";
    const dbUrl = `${base}/results/data/results.duckdb`;
    const dbSize = statSync(DUCKDB_PATH).size;

    const headResp = await request.fetch(dbUrl, { method: "HEAD" });
    expect(headResp.status()).toBe(200);
    expect(headResp.headers()["accept-ranges"]).toBe("bytes");
    expect(Number(headResp.headers()["content-length"])).toBe(dbSize);

    const rangeEnd = Math.min(1023, dbSize - 1);
    const rangedResp = await request.fetch(dbUrl, {
      method: "GET",
      headers: { Range: `bytes=0-${rangeEnd}` },
    });
    expect(rangedResp.status()).toBe(206);
    expect(rangedResp.headers()["content-range"]).toBe(`bytes 0-${rangeEnd}/${dbSize}`);
    expect(Number(rangedResp.headers()["content-length"])).toBe(rangeEnd + 1);
    const body = await rangedResp.body();
    expect(body.byteLength).toBe(rangeEnd + 1);
  });

  test("an out-of-range request is rejected with 416", async ({ request, baseURL }) => {
    const base = baseURL ?? "http://127.0.0.1:4319";
    const dbUrl = `${base}/results/data/results.duckdb`;
    const dbSize = statSync(DUCKDB_PATH).size;

    const resp = await request.fetch(dbUrl, {
      method: "GET",
      headers: { Range: `bytes=${dbSize}-${dbSize + 10}` },
    });
    expect(resp.status()).toBe(416);
    expect(resp.headers()["content-range"]).toBe(`bytes */${dbSize}`);
  });
});
