# Binary Integration Reference

Verify TPC binary packaging and wrappers.

## Check

- `_binaries/tpc-h/<os-arch>/` and `_binaries/tpc-ds/<os-arch>/` paths.
- Executability and platform detection.
- Python wrapper command construction and error handling.
- Data/query generation smoke at supported scale.

## Rules

Do not compile stock TPC-DS `dsdgen` below SF1; BenchBox uses patched bundled
binaries. Separate missing-binary, permission, wrapper, and output-shape
failures.
