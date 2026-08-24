"""The corpus cohort-depth requirement must fail a PR, not just a manual run.

`results-data/SEED_CORPUS_SPEC.md` states it as a hard requirement: every
committed cohort must have at least 3 platforms. `results-data/validate_corpus.py`
enforces it and exits 1 on violation.

Nothing ran it. Every reference to that script in `.github/workflows` is a path
list for mirroring, not an execution, and it was absent from pr-preflight, from
ci-lint and from every pre-commit hook. So PR #1854 added a TPC-DS SF10 cohort
with DuckDB alone, passed pr-preflight green with 28,043 tests, and merged --
leaving develop carrying a violated invariant until someone happened to run the
validator by hand.

This module closes that gap by importing the script rather than restating its
rule, so the gate and the contributor-facing tool cannot drift apart. It lives
in the whole-corpus unit lane beside `test_corpus_privacy_invariant.py`, which
already closed the same class of hole for path leaks and sidecar hashes, and
therefore runs in pr-preflight and in the required CI lane without a new
workflow job.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / "results-data" / "validate_corpus.py"
BUNDLES = REPO_ROOT / "results-data" / "bundles"


def _load_validator() -> ModuleType:
    """Import the vendored script by path; it is not an installed module."""
    spec = importlib.util.spec_from_file_location("validate_corpus", VALIDATOR)
    assert spec and spec.loader, f"cannot load {VALIDATOR}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_bundle(directory: Path, name: str, *, benchmark: str, scale: float, platform: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        json.dumps(
            {
                "benchmark": {"id": benchmark, "scale_factor": scale},
                "platform": {"name": platform},
            }
        ),
        encoding="utf-8",
    )


def test_every_committed_cohort_meets_the_platform_floor() -> None:
    """The invariant itself, against the real corpus."""
    validator = _load_validator()
    cohorts = validator.cohort_platforms(validator.discover_bundles(BUNDLES))

    assert cohorts, "no cohorts found - this gate would be vacuous"
    shallow = validator.shallow_cohorts(cohorts)
    assert not shallow, (
        f"{len(shallow)} cohort(s) below {validator.MINIMUM_PLATFORMS_PER_COHORT} platforms; a one-platform "
        "cohort is not a comparison. See results-data/SEED_CORPUS_SPEC.md:\n  "
        + "\n  ".join(
            f"{benchmark} SF={scale}: {sorted(platforms)}" for (benchmark, scale), platforms in shallow.items()
        )
    )


def test_the_gate_detects_a_one_platform_cohort(tmp_path: Path) -> None:
    """Negative control, on synthetic bundles.

    Asserting against a real violation would stop being a control the moment
    the corpus is correct, which is the state this gate exists to keep it in.
    """
    validator = _load_validator()
    _write_bundle(tmp_path, "a.json", benchmark="tpcds", scale=10.0, platform="DuckDB")

    shallow = validator.shallow_cohorts(validator.cohort_platforms(validator.discover_bundles(tmp_path)))

    assert shallow == {("tpcds", "10.0"): {"DuckDB"}}


def test_the_gate_accepts_a_full_cohort(tmp_path: Path) -> None:
    """Positive control: three platforms in one cohort must not be flagged."""
    validator = _load_validator()
    for platform in ("DuckDB", "DataFusion", "Spark"):
        _write_bundle(tmp_path, f"{platform}.json", benchmark="tpcds", scale=10.0, platform=platform)

    assert validator.shallow_cohorts(validator.cohort_platforms(validator.discover_bundles(tmp_path))) == {}


def test_companion_files_are_not_counted_as_bundles(tmp_path: Path) -> None:
    """A sidecar must not pad a cohort's platform count.

    Counting `x.manifest.json` beside `x.json` would let a one-platform cohort
    look deeper than it is, which is the failure mode this gate exists to stop.
    """
    validator = _load_validator()
    _write_bundle(tmp_path, "a.json", benchmark="tpch", scale=1.0, platform="DuckDB")
    for companion in ("a.manifest.json", "a.plans.json", "a.tuning.json", "a.applied.json"):
        (tmp_path / companion).write_text("{}", encoding="utf-8")
    (tmp_path / "submission-manifest.json").write_text("{}", encoding="utf-8")

    assert [path.name for path in validator.discover_bundles(tmp_path)] == ["a.json"]


def test_an_unreadable_bundle_fails_closed(tmp_path: Path) -> None:
    """The validator's other invariant: a bundle that cannot be read is fatal.

    Skipping it would let a truncated or unreviewed bundle pass while the gate
    stayed green.
    """
    validator = _load_validator()
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(validator.CorpusReadError):
        validator.cohort_platforms(validator.discover_bundles(tmp_path))


@pytest.mark.parametrize(
    ("platforms", "expected_exit"),
    [(("DuckDB",), 1), (("DuckDB", "DataFusion", "Spark"), 0)],
)
def test_the_entry_point_returns_the_right_exit_code(
    tmp_path: Path, platforms: tuple[str, ...], expected_exit: int
) -> None:
    """End-to-end through `main`, so a change that swallows the failure is caught.

    The assertions above use the helpers directly; this one pins the exit code
    the contributor and any future CI caller actually observe.
    """
    validator = _load_validator()
    for platform in platforms:
        _write_bundle(tmp_path, f"{platform}.json", benchmark="tpcds", scale=10.0, platform=platform)

    assert validator.main(tmp_path) == expected_exit
