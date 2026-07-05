"""G-8 exit gate: no legacy metric-bearing JSON artifacts survive a pipeline build.

Asserts two invariants:

1. A freshly-built output directory contains ONLY the canonical artifacts
   (``results.duckdb`` and ``bundles/``). No ``manifest.json``,
   ``meta_leaderboard.json``, ``short_ids.json``, ``results_schema.json``,
   or directories for ``details/``, ``compare/``, ``benchmarks/``.

2. No explorer page or component fetches from ``/results/data/bundles/``
   at runtime. Bundles are a download-only affordance.

Stale artifacts from earlier pipeline versions are removed by the pipeline's
output-dir sweep, so even if the caller reuses an older output dir, the
contract holds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _project.scripts.explorer_pipeline.pipeline import ExplorerPipeline
from tests.unit.scripts.explorer_pipeline.conftest import MINIMAL_BUNDLE

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[4]
EXPLORER_SRC = REPO_ROOT / "results-explorer/src"


LEGACY_FILES = (
    "manifest.json",
    "meta_leaderboard.json",
    "short_ids.json",
    "results_schema.json",
)
LEGACY_DIRS = ("details", "compare", "benchmarks")


@pytest.fixture()
def built_output(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    bundles_dir = data_dir / "bundles"
    bundles_dir.mkdir(parents=True)
    (bundles_dir / "b.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
    output = tmp_path / "out"
    ExplorerPipeline().run(data_dir, output)
    return output


class TestPipelineOutputIsMetricFree:
    def test_no_legacy_files_present(self, built_output: Path) -> None:
        survivors = [name for name in LEGACY_FILES if (built_output / name).exists()]
        assert not survivors, f"pipeline emitted disallowed metric JSON artifacts: {survivors}"

    def test_no_legacy_dirs_present(self, built_output: Path) -> None:
        survivors = [name for name in LEGACY_DIRS if (built_output / name).is_dir()]
        assert not survivors, f"pipeline emitted disallowed metric directories: {survivors}"

    def test_only_canonical_artifacts_emitted(self, built_output: Path) -> None:
        """Output dir must contain exactly: results.duckdb + bundles/ (everything else is legacy)."""
        actual = {p.name for p in built_output.iterdir()}
        assert actual == {"results.duckdb", "bundles"}, f"unexpected output-dir members: {actual}"

    def test_stale_artifacts_are_swept_on_rebuild(self, tmp_path: Path) -> None:
        """Rebuilding over a polluted output dir removes legacy files and dirs."""
        data_dir = tmp_path / "data"
        bundles_dir = data_dir / "bundles"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "b.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")

        output = tmp_path / "out"
        output.mkdir(parents=True)
        # Pollute output with legacy files and dirs
        for name in LEGACY_FILES:
            (output / name).write_text("{}", encoding="utf-8")
        for name in LEGACY_DIRS:
            (output / name).mkdir()
            (output / name / "stale.json").write_text("{}", encoding="utf-8")

        ExplorerPipeline().run(data_dir, output)

        for name in LEGACY_FILES:
            assert not (output / name).exists(), f"rebuild left {name} in place"
        for name in LEGACY_DIRS:
            assert not (output / name).exists(), f"rebuild left {name}/ in place"


class TestSourceTreeDoesNotFetchMetricJson:
    """No page or component fetches legacy metric-bearing JSON paths."""

    FORBIDDEN_PATH_PATTERNS = (
        "/results/data/benchmarks/",
        "/results/data/details/",
        "/results/data/compare/",
        "/results/data/meta_leaderboard.json",
        "/results/data/short_ids.json",
        "/results/data/results_schema.json",
        "/results/data/manifest.json",
        "/results/data/bundles/",
    )

    def _source_files(self) -> list[Path]:
        pages = list((EXPLORER_SRC / "pages").rglob("*.tsx")) + list((EXPLORER_SRC / "pages").rglob("*.ts"))
        components = list((EXPLORER_SRC / "components").rglob("*.tsx")) + list(
            (EXPLORER_SRC / "components").rglob("*.ts")
        )
        return [p for p in (*pages, *components) if "__tests__" not in p.parts]

    def test_no_page_or_component_fetches_legacy_json(self) -> None:
        violations: list[str] = []
        for path in self._source_files():
            text = path.read_text(encoding="utf-8")
            for pattern in self.FORBIDDEN_PATH_PATTERNS:
                if pattern in text:
                    violations.append(f"{path.relative_to(REPO_ROOT)}: references {pattern}")
        assert not violations, "explorer source references legacy metric JSON paths:\n  " + "\n  ".join(violations)
