import { expect, test } from "@playwright/test";
import { waitForDataElement, waitForShell } from "../support/fixtures";

test("constant column hoisting keeps sparse columns and stable column indexes", async ({ page }) => {
  await page.goto("/results/p/polars/");
  await waitForShell(page);
  const polarsTable = page.getByRole("table", { name: "Polars results" });
  await waitForDataElement(page, polarsTable);

  await expect(page.getByTestId("platform-hoisted-metric-contract")).toContainText(
    "Route-wide metric contract",
  );
  await expect(polarsTable.getByRole("columnheader", { name: "Metric contract" })).toHaveCount(0);
  await expect(polarsTable.getByRole("button", { name: /Power score/ }).locator("xpath=..")).toHaveAttribute(
    "aria-colindex",
    "7",
  );

  await page.goto("/results/p/duckdb/");
  const duckdbTable = page.getByRole("table", { name: "DuckDB results" });
  await waitForDataElement(page, duckdbTable);
  await expect(duckdbTable.getByRole("columnheader", { name: "Metric contract" })).toBeVisible();
  const powerHeader = duckdbTable.getByRole("button", { name: /Power score/ }).locator("xpath=..");
  await expect(powerHeader).toHaveAttribute("aria-colindex", "8");
  await expect(duckdbTable.locator('tbody td[aria-colindex="8"]')).not.toHaveCount(0);

  await page.goto("/results/p/duckdb/?benchmark=tpch");
  await waitForDataElement(page, duckdbTable);
  await expect(duckdbTable.getByRole("columnheader", { name: "Metric contract" })).toBeVisible();
  await expect(powerHeader).toHaveAttribute("aria-colindex", "8");
});
