# Dependency Compatibility

```{tags} contributor, reference
```

`pyproject.toml` owns declared Python and dependency ranges. `uv.lock` records
the resolved environment. Do not maintain a static copy of either here.

## Inspect current compatibility

Validate the lock against the manifest or generate the current compatibility
summary directly from those files:

```bash
make dependency-check            # Validate lock vs. pyproject specs
make dependency-check ARGS=--matrix  # Also print compatibility summary
```

The target calls `python -m benchbox.utils.dependency_validation`, which fails
when a declared dependency has no matching locked version.
