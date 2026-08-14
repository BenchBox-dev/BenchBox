<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# benchbox-experimental Future State

```{tags} contributor, architecture, experimental
```

Related TODO: `isolate-experimental-core-subsystems`

Proposed extracted library or package name: `benchbox-experimental`

## Status (2026-08-13)

**Blocked on evidence for further extraction.** The namespace move is already
represented in the repository, but the default wheel still ships the
experimental package. No companion package or extra is justified until demand,
install-size benefit, CI burden, and release cost are measured.

Measured on `origin/develop` at `723126bf3` with `uv build --wheel`:

| Measure | Result |
| --- | --- |
| Wheel | 10,219,657 bytes; 1,325 archive entries |
| `benchbox.experimental` entries | 24; 307,255 uncompressed bytes |
| Warm `import benchbox` in five fresh processes | 0.298–0.409 seconds; environment setup excluded |
| Broad CI/release touchpoint search | 18 matching files; no CI-minute or release-cost measurement |

The measured contents confirm that experimental code remains packaged, but do
not establish that extraction is worth its versioning, CI, and dependency-skew
cost. Default-wheel contents remain unchanged in this item.

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
