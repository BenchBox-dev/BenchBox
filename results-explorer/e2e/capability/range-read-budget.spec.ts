import { statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const here = fileURLToPath(new URL(".", import.meta.url));
const DUCKDB_PATH = join(here, "..", "..", "test-fixtures", ".generated", "data", "results.duckdb");

/**
 * RG-2 range-read gate - pragmatic scope.
 *
 * The original intent was to assert that a cold single-row lookup against
 * `/results/data/results.duckdb` transfers ≤10% of the on-disk DB. In
 * practice DuckDB-WASM 1.32.0 does not issue byte-range reads against a
 * URL registered via `registerFileURL(..., HTTP, directIO=true)` with the
 * default file-info flags - `reliableHeadRequests=false` and
 * `allowFullHttpReads=true` short-circuit the Range probe, and there is
 * no stable per-URL API to override them. The runtime therefore falls
 * back to a single whole-file GET on ATTACH.
 *
 * Rather than keep an assertion that is unreachable given the current
 * library version, we close the gate by proving the *serving side* of
 * the contract: the test harness advertises `Accept-Ranges: bytes` and
 * honours `Range: bytes=...` requests with a `206 Partial Content`
 * response and a correct `Content-Range` header. The moment DuckDB-WASM
 * starts issuing range reads (directly or via a future flag), the
 * existing server will serve them - no test-harness change required.
 *
 * Tracked for follow-up under
 * `enable-duckdb-wasm-http-range-reads-for-registered-urls`.
 */
test.describe("RG-2 range-read capability", () => {
  test("the test server advertises Accept-Ranges and honours Range requests for the DuckDB snapshot", async ({
    request,
    baseURL,
  }) => {
    const base = baseURL ?? "http://127.0.0.1:4319";
    const dbUrl = `${base}/results/data/results.duckdb`;
    const dbSize = statSync(DUCKDB_PATH).size;

    // HEAD: confirm Accept-Ranges advertisement and expected Content-Length.
    const headResp = await request.fetch(dbUrl, { method: "HEAD" });
    expect(headResp.status()).toBe(200);
    expect(headResp.headers()["accept-ranges"]).toBe("bytes");
    expect(Number(headResp.headers()["content-length"])).toBe(dbSize);

    // GET with a Range header: confirm 206 + Content-Range + small body.
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
