<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Future-State Extraction Evidence Baseline

- **Date:** 2026-08-13
- **Measured source:** `origin/develop` at `723126bf3`
**Decision:** Further release-tooling, experimental-subsystem, and monitoring
extraction is blocked on evidence. This item makes no packaging or default
wheel change.

## Measurements

The default wheel was built with `uv build --wheel`.

| Measure | Result |
| --- | --- |
| Wheel size | 10,219,657 bytes (9.75 MiB) |
| Wheel archive entries | 1,325 |
| `benchbox.experimental` entries | 24; 307,255 uncompressed bytes |
| `benchbox.monitoring` entries | 5 |
| Release/maintainer/sync package-path entries | 0 |
| Warm `import benchbox` | 0.298–0.409 seconds across five fresh processes; environment setup excluded |
| Broad CI/release touchpoint search | 18 matching files; this is not a CI-minute measurement |

The wheel includes `benchbox.experimental` and `benchbox.monitoring`. It does
not include a `benchbox-maintainer`, `benchbox/release`, or maintainer/sync
package path. Product publishing paths such as
`benchbox/cli/commands/publish.py` and `benchbox/core/publishing/` are not
maintainer-package evidence and remain in scope for the supported product.

`psutil>=5.9.0` is a core dependency. The measurements do not show a material
install-size win for moving monitoring behind an extra.

## Reconciled status

- `remove-release-tooling-from-wheel`: **Blocked on evidence for further
  extraction**. The current wheel already excludes the proposed maintainer
  package paths; demand, CI-minute impact, and release cost are not measured.
- `isolate-experimental-core-subsystems`: **Blocked on evidence for further
  extraction**. Experimental code remains packaged, but demand, install-size
  benefit, CI burden, and release cost are not measured.
- `gate-monitoring-behind-optional-extra`: **Blocked on evidence**. Monitoring
  remains packaged and `psutil` remains core until a measured size win and a
  second-consumer or demand case exist.

The future-state index and each proposal README use these statuses. A later
implementation item must include the missing evidence and decide whether to
confirm, lower, or supersede the proposal before changing packaging.
