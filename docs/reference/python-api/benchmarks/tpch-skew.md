# TPC-H Skew API

```{tags} reference, python-api, tpch
```

<!-- markdownlint-disable MD024 -->

Python API reference for the TPC-H Skew benchmark.

## Overview

TPC-H Skew generates the eight TPC-H tables with non-uniform value distributions and serves the 22 standard TPC-H queries unchanged, so the same query text can be timed on uniform and on skewed data. The amount of skew comes from one of six presets or from a custom configuration.

The `compare_with_uniform()` example needs the `duckdb` package.

## `benchbox.TPCHSkew`

<span id="benchbox.tpch_skew.TPCHSkew"></span>

Creates a TPC-H benchmark whose generated data follows a chosen skew preset.

**Import:** `from benchbox import TPCHSkew` · **Extras:** none

### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Data size multiplier. Must be positive. Values of 1 or more must be whole numbers. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data files. When `None`, the directory is `benchmark_runs/datagen/tpch_skew_<sf token>` under the current directory (for example `tpch_skew_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. |
| `skew_preset` | `str` or `None` | `None` | One of `none`, `light`, `moderate`, `heavy`, `extreme`, `realistic`, case-insensitive. `None` selects `moderate`. |
| `skew_config` | `SkewConfiguration` or `None` | `None` | A custom configuration, imported from `benchbox.core.tpch_skew`. When given it wins over `skew_preset`, and `skew_preset` reads `"custom"`. |
| `**kwargs` | keyword arguments | none | `verbose` (`bool` or `int`) and `quiet` (`bool`) set the log level. `parallel` (`int`) and `force_regenerate` (`bool`) are forwarded to the data generator. |

The constructor creates no files. Data is written by `generate_data()`.

### Returns

A `TPCHSkew` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

### Raises

- `ValueError` when `scale_factor` is zero or negative, or is 1 or more and not a whole number (`Scale factor must be positive`).
- `ValueError` for an unknown `skew_preset`: `Invalid skew preset: bogus. Valid: ['none', 'light', 'moderate', 'heavy', 'extreme', 'realistic']`.
- `TypeError` when `scale_factor` is not a number.

### Example

```python
from benchbox import TPCHSkew

print(TPCHSkew.get_available_presets())
benchmark = TPCHSkew(scale_factor=0.01, output_dir="skew_data", skew_preset="heavy")
files = benchmark.generate_data()
print(len(files), sorted(benchmark.tables))
info = benchmark.get_skew_info()
print(info["preset"], info["skew_factor"], info["distribution_type"])
print(len(benchmark.get_queries()))
```

Output on 0.4.1:

```text
['none', 'light', 'moderate', 'heavy', 'extreme', 'realistic']
8 ['customer', 'lineitem', 'nation', 'orders', 'part', 'partsupp', 'region', 'supplier']
heavy 0.8 zipfian
22
```

### Compatibility

`benchbox.tpch_skew.TPCHSkew` is the same class.

## Constructor

<span id="benchbox.tpch_skew.TPCHSkew.__init__"></span>

`TPCHSkew(scale_factor=1.0, output_dir=None, skew_preset=None, skew_config=None, **kwargs)`. The arguments are in the Parameters table above.

## Skew presets

The skew factor is the preset's main strength setting, between 0 and 1.

| Preset | Skew factor |
| --- | --- |
| `none` | 0.0 |
| `light` | 0.2 |
| `moderate` | 0.5 |
| `heavy` | 0.8 |
| `extreme` | 1.0 |
| `realistic` | 0.6 |

### get_available_presets()

<span id="benchbox.tpch_skew.TPCHSkew.get_available_presets"></span>

`TPCHSkew.get_available_presets() -> list[str]` is a static method that returns the six preset names in the order of the table above.

### get_preset_description(preset_name)

<span id="benchbox.tpch_skew.TPCHSkew.get_preset_description"></span>

`TPCHSkew.get_preset_description(preset_name) -> str` is a static method that returns a one-line description such as `Heavy skew (z=0.8) - significant concentration, affects join performance`. The name is case-insensitive. Raises `ValueError` for an unknown name (`Unknown preset: x. Valid: [...]`).

### get_skew_info()

<span id="benchbox.tpch_skew.TPCHSkew.get_skew_info"></span>

`get_skew_info() -> dict` returns the active configuration with the keys `preset`, `skew_factor`, `distribution_type`, `attribute_skew_enabled`, `join_skew_enabled`, `temporal_skew_enabled` and `config_summary`. For `heavy`, the factor is 0.8, the distribution is `zipfian`, and attribute, join and temporal skew are all enabled.

### skew_preset and skew_config

<span id="benchbox.tpch_skew.TPCHSkew.skew_preset"></span>
<span id="benchbox.tpch_skew.TPCHSkew.skew_config"></span>

`skew_preset` is the lower-case preset name (`"moderate"` by default, `"custom"` when `skew_config` was given). `skew_config` is the `SkewConfiguration` in use. A custom configuration is not checked at construction: `SkewConfiguration(skew_factor=5)` is accepted, and its `validate()` method returns `['skew_factor should be in [0, 1], got 5']`.

## Methods

### generate_data()

<span id="benchbox.tpch_skew.TPCHSkew.generate_data"></span>

`generate_data() -> list` writes one pipe-delimited `.tbl` file per TPC-H table plus `_datagen_manifest.json` to `output_dir` and returns the eight file paths. `benchmark.tables` is a `dict` that maps table name to path and is empty until `generate_data()` has run. At scale factor 0.01 with `heavy`, `lineitem` holds 60,175 rows.

### manifest_matches_datagen_identity(manifest)

<span id="benchbox.tpch_skew.TPCHSkew.manifest_matches_datagen_identity"></span>

`manifest_matches_datagen_identity(manifest) -> bool` is true when `manifest` (the parsed `_datagen_manifest.json`) was written with this instance's skew configuration. It is false for `{}`, and false for a manifest written with another preset.

```python
import json

with open("skew_data/_datagen_manifest.json") as handle:
    manifest = json.load(handle)
print(benchmark.manifest_matches_datagen_identity(manifest))
# True
```

### get_query(query_id, \*, params=None, seed=None, scale_factor=None, dialect=None, base_dialect=None)

<span id="benchbox.tpch_skew.TPCHSkew.get_query"></span>

`get_query(query_id, *, params=None, seed=None, scale_factor=None, dialect=None, base_dialect=None, **kwargs) -> str` returns one TPC-H query as SQL text. The text is the standard TPC-H query; skew only changes the data.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `int` | required | 1 to 22. |
| `params` | `dict` or `None` | `None` | Parameter overrides. |
| `seed` | `int` or `None` | `None` | Seed for the generated parameter values. The same seed gives the same text; different seeds give different parameters. |
| `scale_factor` | `float` or `None` | `None` | Scale factor used for parameter calculation. Must be positive. |
| `dialect` | `str` or `None` | `None` | Target SQL dialect, translated with SQLGlot. With `duckdb`, identifiers are quoted. |
| `base_dialect` | `str` or `None` | `None` | Dialect the source text is read as before translation. |

Raises `ValueError` when `query_id` is outside 1 to 22 (`Query ID must be 1-22, got 23`) or `scale_factor` is not positive, and `TypeError` when `query_id` is not an `int` (a string `"1"` is rejected) or `seed` is not an `int`.

### get_queries(dialect=None, base_dialect=None)

<span id="benchbox.tpch_skew.TPCHSkew.get_queries"></span>

`get_queries(dialect=None, base_dialect=None) -> dict[str, str]` returns all 22 queries. The keys are the strings `"1"` to `"22"`, although `get_query()` takes an `int`.

### get_schema()

<span id="benchbox.tpch_skew.TPCHSkew.get_schema"></span>

`get_schema() -> dict` returns the TPC-H schema, a mapping from table name to definition. The keys, in order, are `region`, `nation`, `supplier`, `part`, `partsupp`, `customer`, `orders` and `lineitem`.

### get_create_tables_sql(dialect="standard", tuning_config=None)

<span id="benchbox.tpch_skew.TPCHSkew.get_create_tables_sql"></span>

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the TPC-H `CREATE TABLE` script. `dialect` makes no difference to the text for `duckdb`.

### get_benchmark_info()

<span id="benchbox.tpch_skew.TPCHSkew.get_benchmark_info"></span>

`get_benchmark_info() -> dict` returns `name`, `version`, `description`, `reference`, `scale_factor`, `num_queries` (22), `tables` and `skew_info` (the same dict as `get_skew_info()`).

### compare_with_uniform(adapter, queries=None, iterations=1)

<span id="benchbox.tpch_skew.TPCHSkew.compare_with_uniform"></span>

`compare_with_uniform(adapter, queries=None, iterations=1) -> dict` runs the selected queries through a platform adapter once against a standard TPC-H benchmark and once against this benchmark, and returns both sets of timings. Neither phase generates data. Each loads whatever is already in its own default directory under the current directory: `benchmark_runs/datagen/tpch_<sf token>` (for example `tpch_sf001`) for the standard phase and this benchmark's `output_dir` for the skewed phase. A phase with no files there loads 0 rows, and queries such as Q1 return 0 rows but still report `SUCCESS`. Call `generate_data()` on this benchmark and on `TPCH(scale_factor=...)` first, with the same scale factor, to get meaningful timings from both.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `adapter` | platform adapter | required | For example `DuckDBAdapter`. |
| `queries` | `list[int]` or `None` | `None` | Query ids 1 to 22. `None` runs all 22. |
| `iterations` | `int` | `1` | Must be at least 1. |

The returned dict has the keys `queries`, `scale_factor`, `skew_preset`, `skew_config`, `iterations`, `uniform_results`, `skewed_results`, `comparison` and `summary`. `uniform_results` and `skewed_results` map `"Q1"`, `"Q6"` and so on to `{"times": [seconds], "status": "SUCCESS"}`.

Raises `ValueError` when `adapter` is `None` (`adapter cannot be None`), when `queries` holds anything but integers from 1 to 22, or when `iterations` is below 1. A failure while running a phase raises `RuntimeError` (`Failed to run uniform benchmark: ...`), for example when `adapter` has no `run_benchmark` method.

On 0.4.1, `comparison` and `summary` come back unfilled: every `comparison` entry is `{'status': 'INCOMPLETE', 'reason': 'Missing timing data'}` and `summary` is `{'queries_compared': 0, 'error': 'No valid comparisons could be made'}`. `iterations` is recorded in the result but each query runs once per phase. Read the timings from `uniform_results` and `skewed_results`. The adapter prints its load and run progress to standard output.

```python
from benchbox.platforms.duckdb import DuckDBAdapter

adapter = DuckDBAdapter(database=":memory:")
results = benchmark.compare_with_uniform(adapter, queries=[1, 6, 14])
print(sorted(results["skewed_results"]))
print(results["summary"])
```

Output on 0.4.1, after the adapter's progress lines:

```text
['Q1', 'Q14', 'Q6']
{'queries_compared': 0, 'error': 'No valid comparisons could be made'}
```

## Inherited members

Every other member comes from `BaseBenchmark`: running on a platform (`run_with_platform`, `run_benchmark`), validation, logging, `output_dir`, `scale_factor` and the loading configuration. See {doc}`/reference/python-api/base`.
