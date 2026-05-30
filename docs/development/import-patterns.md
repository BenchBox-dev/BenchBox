# Import Patterns and Lazy Loading

```{tags} contributor, reference
```

BenchBox uses a lightweight lazy-loading system so benchmarks are only imported
when they are first accessed. This keeps the initial import of `benchbox`
fast, avoids heavy optional dependencies, and produces actionable guidance when
a dependency is missing.

## Benchmark Registry

All lazily loaded benchmarks are defined in `benchbox/__init__.py` via the
`_BENCHMARK_REGISTRY` mapping. Each `_BenchmarkSpec` entry specifies:

- The module path (relative to `benchbox`)
- The class name to load from that module
- Optional dependency labels (`benchbox[<extra>]` groupings)
- Whether to persist the original `ImportError` for diagnostics (enabled by default)

### Adding a New Benchmark

1. Implement the benchmark in `benchbox/<benchmark_name>.py`.
2. Add a `_BenchmarkSpec` entry to `_BENCHMARK_REGISTRY` with the module name,
   class name, and any optional dependency extras.
3. Export the class through `__all__` if it should be part of the public API.
4. Add unit tests under `tests/unit/test_init.py` to confirm the lazy import and
   provide coverage for missing dependency messaging if appropriate.

`_load_benchmark_class()` centralizes the import logic and logs successes or
failures through the benchmark module logger. Tests can use `_clear_lazy_cache()`
and patch `benchbox._import_module` to simulate missing dependencies without
touching the actual modules.

## Error Messaging

When a benchmark fails to import (for example, because an optional dependency is
not installed) BenchBox raises an enhanced `ImportError` that includes:

- The benchmark name
- Suggested `uv pip install` commands for individual or grouped extras
- Full version context (BenchBox, Python, and platform) for debugging

Downstream code should rely on this behavior instead of wrapping imports a
second time.

## Optional Eager Imports

Benchmarks that are required for internal bootstrapping (such as `TPCH`
and `TPCDS`) can still be imported eagerly at module level. This keeps the core
API available without increasing lazy-loading complexity. Other benchmarks should
remain in `_BENCHMARK_REGISTRY` so optional dependencies are imported only when
the matching benchmark is first accessed.

## Contributor Tips

- Prefer adding new benchmarks to the registry instead of bespoke lazy import
  logic elsewhere in the codebase.
- Use the compatibility helpers from `benchbox.utils.version` to gate features
  that depend on specific BenchBox versions.
- Document new optional dependencies in `pyproject.toml` so the suggested install
  command is accurate.
- When an adapter requires a particular library build, expose it through the
  shared `driver_version` option so the runtime version manager can validate (or
  auto-install) the requested wheel before the import occurs.
