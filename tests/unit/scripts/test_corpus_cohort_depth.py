"""The corpus cohort-depth requirement must fail a PR, not just a manual run.

`results-data/SEED_CORPUS_SPEC.md` states it as a hard requirement: every
committed cohort must have at least 3 comparison identities. `results-data/validate_corpus.py`
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

import datetime as dt
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


def _write_bundle(
    directory: Path,
    name: str,
    *,
    benchmark: str,
    scale: float,
    platform: str,
    platform_version: str | None = None,
    execution_version: str | None = None,
    run_timestamp: str = "2026-08-01T12:00:00",
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    platform_payload = {"name": platform}
    if platform_version is not None:
        platform_payload["version"] = platform_version
    payload = {
        "benchmark": {"id": benchmark, "scale_factor": scale},
        "platform": platform_payload,
        "run": {"timestamp": run_timestamp},
    }
    if execution_version is not None:
        payload["execution"] = {"driver_version_resolved": execution_version}
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_every_committed_cohort_meets_the_platform_floor() -> None:
    """The invariant itself, against the real corpus."""
    validator = _load_validator()
    cohorts = validator.cohort_platforms(validator.discover_bundles(BUNDLES))

    assert cohorts, "no cohorts found - this gate would be vacuous"
    shallow = validator.shallow_cohorts(cohorts)
    assert not shallow, (
        f"{len(shallow)} cohort(s) below {validator.MINIMUM_PLATFORMS_PER_COHORT} identities; a one-identity "
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


def test_the_gate_accepts_a_version_matrix_as_distinct_identities(tmp_path: Path) -> None:
    """A version-over-version cohort may repeat one platform name."""
    validator = _load_validator()
    matrix_dir = tmp_path / "duckdb-version-matrix"
    for index, version in enumerate(("1.0.0", "1.5.5", "1.6.0.dev365")):
        _write_bundle(
            matrix_dir,
            f"duckdb-{index}.json",
            benchmark="tpch",
            scale=10.0,
            platform="DuckDB",
            platform_version=version,
        )

    assert validator.shallow_cohorts(validator.cohort_platforms(validator.discover_bundles(tmp_path))) == {}


def test_versions_do_not_pad_an_ordinary_cross_platform_cohort(tmp_path: Path) -> None:
    """Version identity is reserved for the explicitly segregated matrix corpus."""
    validator = _load_validator()
    for index, version in enumerate(("1.0", "2.0", "3.0")):
        _write_bundle(
            tmp_path,
            f"datafusion-{index}.json",
            benchmark="tpch",
            scale=10.0,
            platform="DataFusion",
            platform_version=version,
        )

    cohorts = validator.cohort_platforms(validator.discover_bundles(tmp_path))
    assert cohorts == {("tpch", "10.0"): {"DataFusion"}}
    assert validator.shallow_cohorts(cohorts) == cohorts


def test_same_platform_version_does_not_pad_a_cohort(tmp_path: Path) -> None:
    """Repeated runs at one version remain one comparison identity."""
    validator = _load_validator()
    matrix_dir = tmp_path / "duckdb-version-matrix"
    for index in range(3):
        _write_bundle(
            matrix_dir,
            f"duckdb-{index}.json",
            benchmark="tpch",
            scale=10.0,
            platform="DuckDB",
            platform_version="1.5.5",
        )

    cohorts = validator.cohort_platforms(validator.discover_bundles(tmp_path))
    assert cohorts == {("tpch", "10.0"): {"DuckDB v1.5.5"}}
    assert validator.shallow_cohorts(cohorts) == cohorts


def test_duckdb_package_version_overrides_internal_engine_version(tmp_path: Path) -> None:
    """DuckDB development builds compare by package version, not engine string."""
    validator = _load_validator()
    matrix_dir = tmp_path / "duckdb-version-matrix"
    _write_bundle(
        matrix_dir,
        "duckdb-dev.json",
        benchmark="tpch",
        scale=10.0,
        platform="DuckDB",
        platform_version="2.0.0-alpha38615",
        execution_version="1.6.0.dev365",
    )

    assert validator.cohort_platforms(validator.discover_bundles(tmp_path)) == {
        ("tpch", "10.0"): {"DuckDB v1.6.0.dev365"}
    }


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


def test_recency_report_uses_bundle_timestamps(tmp_path: Path) -> None:
    """Per-cohort and overall ages come from run.timestamp, not file mtime."""
    validator = _load_validator()
    as_of = dt.date(2026, 9, 4)
    _write_bundle(
        tmp_path,
        "old.json",
        benchmark="tpch",
        scale=1.0,
        platform="DuckDB",
        run_timestamp="2026-05-02T10:00:00",
    )
    _write_bundle(
        tmp_path,
        "new.json",
        benchmark="tpch",
        scale=1.0,
        platform="DataFusion",
        run_timestamp="2026-08-26T10:00:00",
    )
    _write_bundle(
        tmp_path,
        "other.json",
        benchmark="tpcds",
        scale=10.0,
        platform="Spark",
        run_timestamp="2026-07-01T10:00:00",
    )

    overall, per_cohort, warnings = validator.cohort_recency(validator.discover_bundles(tmp_path), as_of=as_of)

    assert warnings == []
    assert overall is not None
    assert overall.oldest == dt.date(2026, 5, 2)
    assert overall.newest == dt.date(2026, 8, 26)
    assert overall.oldest_age_days == 125
    assert overall.newest_age_days == 9
    assert overall.bundle_count == 3
    assert per_cohort[("tpch", "1.0")].oldest_age_days == 125
    assert per_cohort[("tpch", "1.0")].newest_age_days == 9
    assert per_cohort[("tpcds", "10.0")].oldest_age_days == 65


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2026-09-05", dt.date(2026, 9, 5)),
        ("2026-09-04T23:59:59-12:00", dt.date(2026, 9, 5)),
        ("2026-09-05T00:15:00+14:00", dt.date(2026, 9, 4)),
        ("2026-09-05T12:00:00Z", dt.date(2026, 9, 5)),
        ("2026-09-05T12:00:00", dt.date(2026, 9, 5)),
    ],
)
def test_run_timestamp_contract_uses_utc_calendar_days(timestamp: str, expected: dt.date) -> None:
    """Offsets become UTC dates; legacy naive timestamps are explicitly UTC."""
    validator = _load_validator()
    assert validator.parse_run_date({"run": {"timestamp": timestamp}}) == expected


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-09-05Tnot-a-time",
        "2026-09-05T12:00",
        "2026-09-05T12:00:00Z trailing",
        "2026-02-30",
        "2026-09-05 12:00:00",
        "2026-09-05T12:00:00+24:00",
    ],
)
def test_run_timestamp_contract_rejects_malformed_or_trailing_text(timestamp: str) -> None:
    validator = _load_validator()
    with pytest.raises(validator.CorpusReadError, match="unparseable run.timestamp"):
        validator.parse_run_date({"run": {"timestamp": timestamp}})


def test_recency_defaults_to_the_utc_current_day(monkeypatch: pytest.MonkeyPatch) -> None:
    validator = _load_validator()
    monkeypatch.setattr(validator, "utc_today", lambda: dt.date(2026, 9, 5))
    assert validator.age_days(dt.date(2026, 9, 4)) == 1


def test_age_does_not_fail_a_deep_enough_cohort(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Stale timestamps remain visible in the report without flipping exit status."""
    validator = _load_validator()
    as_of = dt.date(2026, 9, 4)
    for platform in ("DuckDB", "DataFusion", "Spark"):
        _write_bundle(
            tmp_path,
            f"{platform}.json",
            benchmark="tpch",
            scale=1.0,
            platform=platform,
            run_timestamp="2026-01-01T00:00:00",
        )

    assert validator.main(tmp_path, as_of=as_of) == 0
    captured = capsys.readouterr().out
    assert "Recency" in captured
    assert "oldest=2026-01-01 (246 days)" in captured
    assert "informational only" in captured
    assert "does not affect ranking eligibility" in captured


def test_missing_run_timestamp_is_omitted_from_recency(tmp_path: Path) -> None:
    """A timestamp-less bundle is warned and omitted; parseable peers remain."""
    validator = _load_validator()
    as_of = dt.date(2026, 9, 4)
    _write_bundle(
        tmp_path,
        "ok.json",
        benchmark="tpch",
        scale=1.0,
        platform="DuckDB",
        run_timestamp="2026-05-02T10:00:00",
    )
    bare = {
        "benchmark": {"id": "tpch", "scale_factor": 1.0},
        "platform": {"name": "DataFusion"},
    }
    (tmp_path / "bare.json").write_text(json.dumps(bare), encoding="utf-8")

    overall, per_cohort, warnings = validator.cohort_recency(validator.discover_bundles(tmp_path), as_of=as_of)

    assert len(warnings) == 1
    assert "run.timestamp" in warnings[0]
    assert warnings[0].startswith("WARN")
    assert overall is not None
    assert overall.bundle_count == 1
    assert overall.oldest == dt.date(2026, 5, 2)
    assert per_cohort[("tpch", "1.0")].bundle_count == 1


def test_timestamp_less_bundle_does_not_fail_depth_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """main() on a deep-enough cohort with a timestamp-less bundle exits 0."""
    validator = _load_validator()
    as_of = dt.date(2026, 9, 4)
    for platform in ("DuckDB", "DataFusion", "Spark"):
        _write_bundle(
            tmp_path,
            f"{platform}.json",
            benchmark="tpch",
            scale=1.0,
            platform=platform,
            run_timestamp="2026-08-01T00:00:00",
        )
    bare = {
        "benchmark": {"id": "tpch", "scale_factor": 1.0},
        "platform": {"name": "ClickHouse"},
    }
    (tmp_path / "bare.json").write_text(json.dumps(bare), encoding="utf-8")

    assert validator.main(tmp_path, as_of=as_of) == 0
    captured = capsys.readouterr().out
    assert "WARN" in captured
    assert "run.timestamp" in captured
    assert "Recency" in captured
    assert "oldest=2026-08-01" in captured
    assert "3 bundles" in captured
    assert "All 1 cohort(s) meet" in captured
