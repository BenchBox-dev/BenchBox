---
iteration: shrink-nyctaxi-downloader-lifecycle
date: 2026-05-24
surface: NYC Taxi downloader lifecycle
branch: chore/shrink-nyctaxi-downloader-lifecycle
pr:
raw_cloc_delta: 250
credited_reduction: 250
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --by-file --include-lang=Python benchbox/core/nyctaxi/downloader.py
  - make duplicate-check-json
  - uv run -- python scripts/check_complexity.py --source-root benchbox/core/nyctaxi --no-fail --top 20
  - uv run -- ruff check benchbox/core/nyctaxi/downloader.py tests/unit/core/nyctaxi/test_downloader.py tests/unit/core/nyctaxi/test_multi_type.py tests/unit/generators/test_scale_factor_harmonization.py
  - uv run -- python -m pytest tests/unit/core/nyctaxi/test_downloader.py tests/unit/core/nyctaxi/test_multi_type.py tests/unit/generators/test_scale_factor_harmonization.py -q -n 0
  - uv run -- python - <<'PY' ... # manual NYC Taxi downloader fingerprint
  - make pr-preflight
---

## Thesis

Shrink iteration under the smaller-subsystem exception. The NYC Taxi downloader
lifecycle subsystem is `benchbox/core/nyctaxi/downloader.py`, measured at 632
Python code lines before edits. The final file is 382 Python code lines, for a
250-line credited maintained-Python reduction. This meets the smaller-subsystem
floor: at least 250 credited lines and at least 10% of the subsystem.

The three public downloader classes stay explicit and grep-findable:
`NYCTaxiDataDownloader`, `GreenTaxiDataDownloader`, and `HVFHVDataDownloader`.
The repeated lifecycle around initialization, sample-rate saturation warnings,
trip-file output, monthly parquet download, sampling, row writing, malformed-row
logging, and stats construction moved into a private shared base. The
taxi-type-specific behavior remains on the concrete classes: public return
types, table names, filenames, URL prefixes, logger names, warning labels,
column providers, row-mapping aliases/defaults, synthetic generation
parameters/row writers, and HVFHV February 2019 default-month behavior.

Credited reduction is the net maintained-Python cloc reduction after adding the
private helper/base code. There is no Python-to-data relocation, generated
Python, SQL/query movement, benchmark deletion, platform deletion, or
deprecated/beta-public surface removal.

## Guardrail Evidence

- Iteration type: shrink iteration, smaller-subsystem exception.
- Subsystem: `benchbox/core/nyctaxi/downloader.py`; baseline 632 Python cloc,
  below the 1,000-line smaller-subsystem cap.
- Minimum gate: remove at least 250 credited Python lines and at least 10% of
  the subsystem. Final measurement is 250 lines, 39.6% of the subsystem.
- Moved-content classification: logic consolidation only.
- Decision-gate status: conservative default. No open policy gate is used to
  approve relocation, generated implementation, or dynamic symbol injection.
- Public/exported surface: all three downloader class names, constructor
  signatures, and module imports remain explicit.
- Open PR overlap: after PR #617 merged, `gh pr list --state open --base
  develop --json number,title,headRefName,baseRefName,state,mergeStateStatus
  --limit 30` returned `[]`.
- Baseline duplicate evidence: `make duplicate-check-json` reports duplicated
  NYC Taxi downloader blocks in `_process_parquet_file` (3 x 54),
  `_download_and_process_trips` (3 x 38), `__init__` (2 x 52), and
  `get_download_stats` (3 x 14).
- Baseline complexity evidence: `uv run -- python scripts/check_complexity.py
  --source-root benchbox/core/nyctaxi --no-fail --top 20` passed with
  downloader lifecycle functions at CC 7 and 4.
- Baseline behavior evidence: `uv run -- python -m pytest
  tests/unit/core/nyctaxi/test_downloader.py
  tests/unit/core/nyctaxi/test_multi_type.py
  tests/unit/generators/test_scale_factor_harmonization.py -q -n 0` reported
  91 passed before edits.

## Verification

- `make shrink-rollup` before edits: cumulative merged credited reduction 252;
  remaining floor 11,748, stretch 18,748.
- `cloc --include-lang=Python benchbox/`: 206,352 Python code lines after the
  slice, down from the 206,602 pre-edit sanity measurement on this branch.
- `cloc --by-file --include-lang=Python benchbox/core/nyctaxi/downloader.py`:
  382 code lines after the slice, down from 632 before the slice.
- `make duplicate-check-json`: no duplicate groups remain for
  `benchbox/core/nyctaxi/downloader.py`; repo duplicate summary moved from 306
  groups / 414 instances / 7,730 duplicated lines to 301 groups / 406
  instances / 7,435 duplicated lines.
- `uv run -- python scripts/check_complexity.py --source-root
  benchbox/core/nyctaxi --no-fail --top 20`: passed; downloader lifecycle
  worst CC remains 7, with `_write_metered_synthetic_row` at 5 and
  `_download_and_process_trips` at 4.
- `uv run -- ruff check benchbox/core/nyctaxi/downloader.py
  tests/unit/core/nyctaxi/test_downloader.py
  tests/unit/core/nyctaxi/test_multi_type.py
  tests/unit/generators/test_scale_factor_harmonization.py`: passed.
- `uv run -- python -m pytest tests/unit/core/nyctaxi/test_downloader.py
  tests/unit/core/nyctaxi/test_multi_type.py
  tests/unit/generators/test_scale_factor_harmonization.py -q -n 0`: 91
  passed.
- Manual pre/post fingerprint against `origin/develop` matched exactly for all
  three public downloader classes: constructor signature, logger name, explicit
  months, sample rate, stats shape, deterministic synthetic row count, first
  rows, synthetic SHA-256, and HVFHV default months for 2019 and 2020.
- `make pr-preflight`: passed; broad fast suite reported 22,775 passed, 5
  skipped, 47 warnings, and 4 subtests passed.

## Residual Risk

The main risk is collapsing superficially identical download lifecycle code
that still carries type-specific behavior. Those differences are kept in
explicit class attributes or methods, and verification fingerprints public
constructor defaults, logger names, table/file names, URL patterns, stats
shape, and deterministic synthetic output for all three downloaders.

## Next Target

If this slice lands with credit, continue through another duplicate-maintenance
surface with no benchmark/platform deletion. If it misses the smaller-subsystem
threshold, reject it and move to a larger true-dedup target.
