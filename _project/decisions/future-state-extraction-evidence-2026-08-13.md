<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Future-State Extraction Evidence Baseline

- **Date:** 2026-08-13
- **Measured source:** `origin/develop` at `723126bf3802c499dc195993f1880cc20a748059`
- **Decision:** Further release-tooling, experimental-subsystem, and monitoring
  extraction is blocked on evidence. This item makes no packaging or default
  wheel change.

## Measurements

The default wheel was built with `uv build --wheel` at the measured SHA.

| Measure | Result | How to reproduce |
| --- | --- | --- |
| Wheel size | 10,219,657 bytes (9.75 MiB) | `uv build --wheel`, then `stat` the resulting `.whl` |
| Wheel archive entries | 1,325 | `python -c "import zipfile; print(len(zipfile.ZipFile('<whl>').namelist()))"` |
| `benchbox.experimental` entries | 24; 307,255 uncompressed bytes | Count and `sum` the 24 packaged `benchbox/experimental/**/*.py` files |
| `benchbox.monitoring` entries | 5 | Count packaged `benchbox/monitoring/*.py` files |
| Release/maintainer/sync package-path entries | 0 | Search the wheel and tree for `benchbox-maintainer`, `benchbox/release`, and maintainer/sync package paths |

`import benchbox` was observed at 0.298–0.409 seconds across five fresh
processes with environment setup excluded. That range is a machine-local
observation, not a checked-in benchmark, and it is **not** import-cost evidence
for experimental or monitoring extraction: `import benchbox` does not load
those packages.

No CI-minute or release-cost measurement was taken. A later extraction item
must supply those numbers rather than reuse an undocumented file-count search.

The wheel includes `benchbox.experimental` and `benchbox.monitoring`. It does
not include a `benchbox-maintainer`, `benchbox/release`, or maintainer/sync
package path. Product publishing paths such as
`benchbox/cli/commands/publish.py` and `benchbox/core/publishing/` are not
maintainer-package evidence and remain in scope for the supported product.

`psutil>=5.9.0` is a core dependency used outside `benchbox.monitoring`. The
measurements do not show a material install-size win for moving monitoring
behind an extra, and dropping the monitoring package would not by itself drop
`psutil`.

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
