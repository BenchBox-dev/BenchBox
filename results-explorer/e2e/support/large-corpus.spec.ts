import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";
import { waitForResultRows, waitForShell } from "./fixtures";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const generatorPath = resolve(projectRoot, "scripts", "generate-browser-fixtures.mjs");
const serverPath = resolve(projectRoot, "scripts", "serve-browser-tests.mjs");

function generateLargeFixture(outputRoot: string) {
  execFileSync(process.execPath, [generatorPath], {
    cwd: projectRoot,
    env: {
      ...process.env,
      E2E_FIXTURE_OUTPUT_ROOT: outputRoot,
      E2E_FIXTURE_PROFILE: "large",
    },
    stdio: "inherit",
  });
}

async function reservePort(): Promise<number> {
  return await new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        server.close();
        reject(new Error("could not reserve a local port"));
        return;
      }
      server.close(() => resolvePort(address.port));
    });
  });
}

async function waitForServer(url: string, server: ChildProcess, output: () => string) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null) {
      throw new Error(`large-corpus server exited ${server.exitCode}: ${output()}`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The child is still binding its socket.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 50));
  }
  throw new Error(`large-corpus server did not become ready: ${output()}`);
}

async function withLargeFixture(run: (baseUrl: string) => Promise<void>) {
  const outputRoot = mkdtempSync(resolve(tmpdir(), "benchbox-large-browser-fixture-"));
  let server: ChildProcess | null = null;
  let serverOutput = "";
  try {
    generateLargeFixture(outputRoot);
    const port = await reservePort();
    server = spawn(process.execPath, [serverPath, "--host", "127.0.0.1", "--port", String(port)], {
      cwd: projectRoot,
      env: { ...process.env, E2E_FIXTURE_DIR: resolve(outputRoot, "data") },
      stdio: ["ignore", "pipe", "pipe"],
    });
    server.stdout?.on("data", (chunk) => {
      serverOutput += String(chunk);
    });
    server.stderr?.on("data", (chunk) => {
      serverOutput += String(chunk);
    });
    const baseUrl = `http://127.0.0.1:${port}`;
    await waitForServer(`${baseUrl}/results/`, server, () => serverOutput);
    await run(baseUrl);
  } finally {
    server?.kill("SIGTERM");
    rmSync(outputRoot, { recursive: true, force: true });
  }
}

test.describe("large corpus fixture", () => {
  // CI can need more than the global 90 seconds to generate the 292-result fixture
  // before the browser assertions begin.
  test.describe.configure({ timeout: 240_000 });

  test("large corpus Compare builder is bounded after retirement (no unbounded candidate table)", async ({ browser }) => {
    await withLargeFixture(async (baseUrl) => {
      for (const viewport of [
        { width: 1440, height: 900 },
        { width: 390, height: 844 },
      ]) {
        const context = await browser.newContext({ viewport });
        const page = await context.newPage();
        await page.goto(`${baseUrl}/results/compare`);
        await waitForShell(page);

        await expect(page.getByTestId("compare-builder-query-cta")).toBeVisible();
        await expect(page.locator("table")).toHaveCount(0);
        const documentHeight = await page.evaluate(() => document.documentElement.scrollHeight);
        expect(documentHeight).toBeLessThan(6000);
        expect(documentHeight).toBeLessThan(viewport.height * 8);

        await context.close();
      }
    });
  });

  test("query paging scale bounds document height and preserves cross-page selection", async ({ browser }) => {
    await withLargeFixture(async (baseUrl) => {
      for (const viewport of [
        { width: 1440, height: 1000 },
        { width: 390, height: 844 },
      ]) {
        const context = await browser.newContext({ viewport });
        const page = await context.newPage();
        await page.goto(`${baseUrl}/results/query`);
        await waitForShell(page);

        const panel = page.getByTestId("query-results-panel");
        await waitForResultRows(page, panel, 24);
        await expect(panel.locator('tbody tr[data-testid^="query-result-row-"]')).toHaveCount(24);
        await expect(page.getByTestId("query-pagination")).toBeVisible();

        const documentHeight = await page.evaluate(() => document.documentElement.scrollHeight);
        expect(documentHeight).toBeLessThan(viewport.height * 3);

        await panel.locator('input[data-testid^="query-compare-checkbox-"]').first().check();
        await page.getByRole("button", { name: "Next page" }).click();
        await expect.poll(() => new URL(page.url()).searchParams.get("page")).toBe("2");
        await waitForResultRows(page, panel, 24);
        await expect(page.getByTestId("query-compare-tray")).toContainText("1 result selected");

        await context.close();
      }
    });
  });
});
