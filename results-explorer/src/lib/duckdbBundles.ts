import * as duckdb from "@duckdb/duckdb-wasm";

import duckdbWasmMvp from "@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url";
import duckdbWorkerMvp from "@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url";
import duckdbWasmEh from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import duckdbWorkerEh from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";
import duckdbWasmCoi from "@duckdb/duckdb-wasm/dist/duckdb-coi.wasm?url";
import duckdbWorkerCoi from "@duckdb/duckdb-wasm/dist/duckdb-browser-coi.worker.js?url";
import duckdbPthreadWorker from "@duckdb/duckdb-wasm/dist/duckdb-browser-coi.pthread.worker.js?url";

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
