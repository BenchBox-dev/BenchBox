<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Migrating from the Modin DataFrame platform

```{tags} intermediate, guide, modin, dataframe-platform
```

BenchBox no longer supports the `modin` and `modin-df` platform selectors. No published Modin release supports the pandas 3 dependency required by BenchBox's current DataFrame update.

Use `pandas-df` when you need pandas-compatible, single-process execution:

```bash
uv add benchbox --extra pandas
uv run benchbox run --platform pandas-df --benchmark tpch --scale 0.1
```

Use `dask-df` when you need distributed DataFrame execution:

```bash
uv add benchbox --extra dask
uv run benchbox run --platform dask-df --benchmark tpch --scale 0.1
```

Existing commands that select `modin` or `modin-df` now fail with a migration message naming these replacements. Remove the `modin` or `dataframe-modin` extra from project dependency declarations before updating BenchBox.
