import { expect, test, type Locator } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

function sortableHeader(scope: Locator, label: RegExp): Locator {
  return scope.locator("th[aria-sort]").filter({ hasText: label }).first();
}

async function rowIds(rows: Locator): Promise<string[]> {
  return rows.evaluateAll((elements) =>
    elements.map((row) => row.getAttribute("data-testid") ?? ""),
  );
}

async function columnTexts(rows: Locator, columnIndex: number): Promise<string[]> {
  return rows.evaluateAll(
    (elements, index) =>
      elements.map((row) =>
        (row.children.item(index)?.textContent ?? "").replace(/\s+/g, " ").trim(),
      ),
    columnIndex,
  );
}

function parseScale(cellText: string): number {
  return Number(cellText.match(/[\d.]+/)?.[0] ?? Number.NaN);
}

async function platformCellLabels(rows: Locator, columnIndex: number): Promise<string[]> {
  return rows.evaluateAll(
    (elements, index) =>
      elements.map((row) => {
        const cell = row.children.item(index);
        return cell?.querySelector(".font-medium")?.textContent?.trim() ?? cell?.textContent?.trim() ?? "";
      }),
    columnIndex,
  );
}

test.describe("Index sortable headers", () => {
  test("PlatformIndex headers update aria-sort and row order", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    await waitForDataLoaded(page, /DuckDB Results/);

    const table = page.locator("table").first();
    const rows = table.locator("tbody tr[data-testid]");
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(2);

    const initialOrder = await rowIds(rows);
    const scaleHeader = sortableHeader(table, /^Scale/);
    const scaleButton = scaleHeader.getByRole("button", { name: /Scale/ });

    await scaleButton.click();
    await expect(scaleHeader).toHaveAttribute("aria-sort", "ascending");
    await scaleButton.click();
    await expect(scaleHeader).toHaveAttribute("aria-sort", "descending");

    const scales = (await columnTexts(rows, 2)).map(parseScale);
    expect(scales).toEqual([...scales].sort((a, b) => b - a));
    expect(await rowIds(rows)).not.toEqual(initialOrder);
  });

  test("BenchmarkIndex matrix headers update aria-sort and row order", async ({ page }) => {
    await page.goto("/results/tpch/?sf=0.01&phase=standard");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);

    const grid = page.getByRole("grid", { name: /tpch SF0\.01 standard results/i });
    const rows = grid.locator("tbody tr[data-testid]");
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(3);

    const platformHeader = sortableHeader(grid, /^Platform/);
    await platformHeader.getByRole("button", { name: /Platform/ }).click();

    await expect(platformHeader).toHaveAttribute("aria-sort", "ascending");
    // QueryHeatmap sorts by the platform display name, while the cell also
    // carries version and receipt metadata. Read the visible platform label
    // element instead of sorting the whole cell text.
    const platforms = await platformCellLabels(rows, 1);
    expect(platforms).toEqual([...platforms].sort((a, b) => a.localeCompare(b)));
  });

  test("BenchmarkIndex list headers update aria-sort and row order", async ({ page }) => {
    await page.goto("/results/tpch/?sf=0.01&phase=standard");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);

    await page.getByRole("radio", { name: "List" }).click();
    const table = page.locator("table").first();
    const rows = table.locator("tbody tr[data-testid]");
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(3);

    const platformHeader = sortableHeader(table, /^Platform/);
    await platformHeader.getByRole("button", { name: /Platform/ }).click();

    await expect(platformHeader).toHaveAttribute("aria-sort", "ascending");
    const platforms = await platformCellLabels(rows, 0);
    expect(platforms).toEqual([...platforms].sort((a, b) => a.localeCompare(b)));
  });
});
