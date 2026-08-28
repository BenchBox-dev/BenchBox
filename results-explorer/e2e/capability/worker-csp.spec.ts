import { expect, test } from "@playwright/test";

import { waitForDataLoaded } from "../support/fixtures";

test("DuckDB worker inherits the page CSP and cannot fetch a remote URL", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  let remoteRequests = 0;
  await page.route("https://example.invalid/**", async (route) => {
    remoteRequests += 1;
    await route.fulfill({ status: 200, contentType: "text/csv", body: "value\n1\n" });
  });
  await page.goto("/results/query");
  try {
    await waitForDataLoaded(page, /matching result bundle/);
  } catch (error) {
    throw new Error(`${String(error)}\nBrowser errors:\n${browserErrors.join("\n")}`);
  }
  await page.locator("summary", { hasText: "Advanced SQL" }).click();
  await page.locator("textarea").fill("SELECT * FROM read_csv_auto('https://example.invalid/exfil.csv')");
  await page.getByRole("button", { name: /^Run SQL$/ }).click();

  const error = page.locator("details", { hasText: "Advanced SQL" }).getByRole("alert");
  await expect(error).toBeVisible();
  await expect(error).toContainText(/http|network|fetch|access|permission|connect|external|disabled/i);
  expect(remoteRequests).toBe(0);
});
