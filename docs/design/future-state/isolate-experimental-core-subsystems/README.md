<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# benchbox-experimental Future State

```{tags} contributor, architecture, experimental
```

Related TODO: `isolate-experimental-core-subsystems`

Proposed extracted library or package name: `benchbox-experimental`

## Future State

BenchBox core exposes only documented, supported benchmark surfaces. Prototype
or research-oriented subsystems such as NL2SQL, AIML/functions workflows,
multi-region orchestration, GPU support infrastructure, and concurrency testing
harnesses move behind an explicit experimental boundary. That boundary can be an
installable companion package or a clearly labeled namespace with limited
exports.

Note: GPU support has one active consumer (`benchbox/platforms/cudf.py`), so its
move requires updating that platform adapter's imports. The other four
subsystems have zero external consumers today.

## Why This Is Valuable

- The public package boundary matches the documented support policy.
- Experimental code can iterate quickly without implying production support.
- Contributors gain a stable rule for where future prototypes should live.

## How The End State Is Used

Core users interact with supported benchmarks only:

```bash
uv add benchbox
benchbox list-benchmarks
benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

Experimental users opt in explicitly:

```bash
uv add benchbox-experimental
python -c "from benchbox_experimental import NL2SQLBenchmark"
```

If the namespace stays in-repo rather than becoming a separate distribution, the
usage model is still explicit:

```python
from benchbox.experimental import NL2SQLBenchmark
```

## BenchBox After The Refactor

- Supported benchmarks stay in the main registry and top-level docs.
- Experiments are discoverable only through an explicit experimental path.
- Removing or extracting one experiment no longer reshapes the supported core.

## Non-Goals

- Promoting experimental modules into supported registries to avoid refactoring
- Breaking supported benchmark APIs while reorganizing prototypes
