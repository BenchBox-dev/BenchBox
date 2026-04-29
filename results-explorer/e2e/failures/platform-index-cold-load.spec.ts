import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";
import type { BrowserContext, Route } from "@playwright/test";

import { waitForShell } from "../support/fixtures";

const here = fileURLToPath(new URL(".", import.meta.url));
const productionDuckDb = readFileSync(join(here, "..", "..", "public", "data", "results.duckdb"));
const productionDuckDbSize = productionDuckDb.byteLength;

const DUCKDB_ROUTE = "**/results/data/results.duckdb";

const BASE_DUCKDB_HEADERS = {
  "Accept-Ranges": "bytes",
  "Cache-Control": "no-store",
  "Content-Type": "application/octet-stream",
  "Cross-Origin-Resource-Policy": "cross-origin",
};

async function fulfillDuckDb(route: Route) {
  const request = route.request();
  const range = request.headers()["range"];
  if (request.method() === "HEAD") {
    await route.fulfill({
      status: 200,
      headers: {
        ...BASE_DUCKDB_HEADERS,
        "Content-Length": String(productionDuckDbSize),
      },
    });
    return;
  }

  if (range) {
    const match = /^bytes=(\d+)-(\d+)?$/.exec(range);
    if (match) {
      const start = Number(match[1]!);
      const end = match[2] ? Number(match[2]) : productionDuckDbSize - 1;
      if (start <= end && end < productionDuckDbSize) {
        await route.fulfill({
          status: 206,
          headers: {
            ...BASE_DUCKDB_HEADERS,
            "Content-Length": String(end - start + 1),
            "Content-Range": `bytes ${start}-${end}/${productionDuckDbSize}`,
          },
          body: productionDuckDb.subarray(start, end + 1),
        });
        return;
      }

      await route.fulfill({
        status: 416,
        headers: {
          "Accept-Ranges": "bytes",
          "Content-Range": `bytes */${productionDuckDbSize}`,
        },
      });
      return;
    }
  }

  await route.fulfill({
    status: 200,
    headers: {
      ...BASE_DUCKDB_HEADERS,
      "Content-Length": String(productionDuckDbSize),
    },
    body: productionDuckDb,
  });
}

async function useProductionDuckDb(context: BrowserContext) {
  await context.route(DUCKDB_ROUTE, fulfillDuckDb);
}

test.describe.configure({ mode: "serial" });

test.describe("PlatformIndex cold-load regression (B2)", () => {
  test.beforeEach(async ({ context }) => {
    await useProductionDuckDb(context);
  });

  test("cold-load renders DuckDB with 4 rows and capital-D heading", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /^DuckDB Results$/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.locator("table tbody tr")).toHaveCount(4);
  });

  test("cold-load renders Polars with 2 rows and capital-P heading", async ({ page }) => {
    await page.goto("/results/p/polars/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /^Polars Results$/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.locator("table tbody tr")).toHaveCount(2);
  });
});
