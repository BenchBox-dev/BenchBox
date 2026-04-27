import * as duckdb from "@duckdb/duckdb-wasm";

import duckdbWasmMvp from "@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url";
import duckdbWorkerMvp from "@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url";
import duckdbWasmEh from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import duckdbWorkerEh from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";
import duckdbWasmCoi from "@duckdb/duckdb-wasm/dist/duckdb-coi.wasm?url";
import duckdbWorkerCoi from "@duckdb/duckdb-wasm/dist/duckdb-browser-coi.worker.js?url";
import duckdbPthreadWorker from "@duckdb/duckdb-wasm/dist/duckdb-browser-coi.pthread.worker.js?url";

// Same-origin bundle descriptor for Vite builds. This removes the jsDelivr
// dependency while still letting duckdb-wasm pick the best runtime variant
// (MVP, EH, or COI/threads) via selectBundle(). All three variants' WASM and
// worker files are emitted to dist/assets/ at build time (~15 MB uncompressed
// total), but the browser only fetches the URLs returned by selectBundle() -
// so runtime bandwidth is for one variant only.
export const LOCAL_DUCKDB_BUNDLES: duckdb.DuckDBBundles = {
  mvp: {
    mainModule: duckdbWasmMvp,
    mainWorker: duckdbWorkerMvp,
  },
  eh: {
    mainModule: duckdbWasmEh,
    mainWorker: duckdbWorkerEh,
  },
  coi: {
    mainModule: duckdbWasmCoi,
    mainWorker: duckdbWorkerCoi,
    pthreadWorker: duckdbPthreadWorker,
  },
};
