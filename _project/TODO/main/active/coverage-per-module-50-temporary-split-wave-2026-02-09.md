# Coverage Wave Snapshot (2026-02-09)

## Scope
- TODO: `coverage-per-module-50-temporary-split`
- Wave focus: active TPC-DI modules under 50% that were quick to lift with unit-heavy tests.
- Added tests:
`tests/unit/core/tpcdi/test_incremental_loader_coverage.py`
`tests/unit/core/tpcdi/test_sql_generator_coverage.py`

## Before (full `make coverage-per-file`)
- `benchbox/core/tpcdi/etl/pipeline.py`: `10.03%`
- `benchbox/core/tpcdi/generator/sql.py`: `10.13%`
- `benchbox/core/tpcdi/etl/scd_processor.py`: `20.00%`
- `benchbox/core/tpcdi/etl/sources.py`: `21.05%`
- `benchbox/core/tpcdi/generator/dimensions.py`: `23.97%`
- `benchbox/core/tpcdi/generator/facts.py`: `27.87%`
- `benchbox/core/tpcdi/etl/incremental_loader.py`: `43.69%`

## After (full `make coverage-per-file`)
- `benchbox/core/tpcdi/etl/pipeline.py`: `10.03%`
- `benchbox/core/tpcdi/etl/scd_processor.py`: `20.00%`
- `benchbox/core/tpcdi/etl/sources.py`: `21.05%`
- `benchbox/core/tpcdi/generator/dimensions.py`: `23.97%`
- `benchbox/core/tpcdi/generator/facts.py`: `27.87%`
- Removed from under-50 list:
`benchbox/core/tpcdi/generator/sql.py`
`benchbox/core/tpcdi/etl/incremental_loader.py`

## Notes
- Targeted module-only coverage run after test additions:
`incremental_loader.py`: `82%`
`generator/sql.py`: `91%`
- Global gate still fails due many non-TPC-DI modules below 50%; this snapshot records this wave's verified delta only.
