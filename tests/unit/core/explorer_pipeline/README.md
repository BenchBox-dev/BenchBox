# Explorer pipeline tests

These tests exercise the Explorer publishing pipeline whose source moved out
of the BenchBox CLI surface in PR #418.

- Source under test: `_project/scripts/explorer_pipeline/` (and the entry
  point `_project/scripts/explorer_publish.py`).
- Why the tests didn't move with the source: `_project/` is intentionally
  excluded from the BenchBox wheel build (see `tool.setuptools.packages.find`
  in `pyproject.toml`). Keeping the test tree under `tests/` preserves the
  existing `make test-*` / pytest collection paths and avoids accidentally
  shipping test files.

See `docs/development/adr/adr-explorer-cli-surface.md` for the decision that
relocated the publisher.
