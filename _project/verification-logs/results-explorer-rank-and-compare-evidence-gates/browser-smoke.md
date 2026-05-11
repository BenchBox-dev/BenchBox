# Results Explorer rank and compare evidence gates browser smoke

Date: 2026-05-11
Build: `cd results-explorer && npm run build`
Server: `node scripts/serve-browser-tests.mjs --port 4319 --host 127.0.0.1 --fixture-dir /tmp/results-explorer-rank-smoke-data`
Fixture: `/tmp/results-explorer-rank-smoke-data`, generated from `results-data/` with `uv run -- benchbox explorer build --data-dir results-data --output /tmp/results-explorer-rank-smoke-data`

PASS /results/amplab/?sf=0.01&phase=power&view=ranks shows the rank gate.
Evidence: route preserved `view=ranks`; page contained `Ranks are unavailable` and `No rankable results are available`.

PASS /results/amplab/?sf=0.01&phase=power shows the `Excluded runs` disclosure.
Evidence: opening the disclosure showed seven excluded rows with per-row reasons and `Receipt` links.

PASS /results/amplab/?sf=0.01&phase=power disables compare selection for non-comparable rows.
Evidence: at least one rendered compare checkbox was disabled for a row with comparison exclusion.

PASS /results/compare?ids=97631760,e9dec0d3 suppresses unsupported compare winner claims.
Evidence: Compare rendered `Insufficient comparable query evidence` and kept the Comparability Receipt visible.

FAIL count: 0 final smoke assertions failed.
