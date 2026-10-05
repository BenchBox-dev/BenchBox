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

from _project.scripts.explorer_pipeline.models import canonical_phase, ranking_exclusion_reason
from _project.scripts.explorer_pipeline.transformer import BundleTransformer
from tests.unit.scripts.explorer_pipeline.conftest import MINIMAL_BUNDLE

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
    test_type: str | None = "power",
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
    if test_type is not None:
        payload["benchmark"]["test_type"] = test_type
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


def _write_phase_bundle(
    directory: Path,
    name: str,
    *,
    platform: str,
    power: str,
    throughput: str,
    streams: int = 3,
    test_type: str | None = None,
) -> None:
    benchmark: dict = {"id": "tpch", "scale_factor": 1.0}
    if test_type is not None:
        benchmark["test_type"] = test_type
    throughput_phase: dict = {"status": throughput}
    if throughput != "NOT_RUN":
        throughput_phase["stream_results"] = [{"stream_id": index, "success": True} for index in range(streams)]
    payload = {
        "benchmark": benchmark,
        "platform": {"name": platform},
        "run": {"timestamp": "2026-08-01T12:00:00"},
        "phases": {"power_test": {"status": power}, "throughput_test": throughput_phase},
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def _throughput_cohort(validator: ModuleType, directory: Path) -> dict:
    return {
        key: platforms
        for key, platforms in validator.cohort_platforms(validator.discover_bundles(directory)).items()
        if "#throughput" in key[1]
    }


@pytest.mark.parametrize("test_type", [None, "throughput", "Throughput"])
def test_throughput_bundles_form_their_own_cohort(tmp_path: Path, test_type: str | None) -> None:
    validator = _load_validator()
    for platform in ("DuckDB", "DataFusion", "Spark"):
        _write_phase_bundle(
            tmp_path, f"{platform}-power.json", platform=platform, power="COMPLETED", throughput="NOT_RUN"
        )
    _write_phase_bundle(
        tmp_path, "duckdb-tp.json", platform="DuckDB", power="NOT_RUN", throughput="COMPLETED", test_type=test_type
    )

    shallow = validator.shallow_cohorts(validator.cohort_platforms(validator.discover_bundles(tmp_path)))

    assert shallow == {("tpch", "1.0#throughput#3streams"): {"DuckDB"}}


def test_three_throughput_engines_pass_the_gate(tmp_path: Path) -> None:
    validator = _load_validator()
    for platform in ("DuckDB", "Spark", "Doris"):
        _write_phase_bundle(
            tmp_path,
            f"{platform}.json",
            platform=platform,
            power="NOT_RUN",
            throughput="COMPLETED",
            test_type="throughput",
        )

    assert validator.shallow_cohorts(validator.cohort_platforms(validator.discover_bundles(tmp_path))) == {}
    assert validator.main(tmp_path) == 0


def test_throughput_stream_counts_do_not_pad_each_other(tmp_path: Path) -> None:
    validator = _load_validator()
    for platform, streams in (("DuckDB", 2), ("Spark", 3), ("Doris", 3)):
        _write_phase_bundle(
            tmp_path,
            f"{platform}.json",
            platform=platform,
            power="NOT_RUN",
            throughput="COMPLETED",
            streams=streams,
            test_type="throughput",
        )

    assert _throughput_cohort(validator, tmp_path) == {
        ("tpch", "1.0#throughput#2streams"): {"DuckDB"},
        ("tpch", "1.0#throughput#3streams"): {"Spark", "Doris"},
    }


def test_not_run_power_phase_does_not_make_a_throughput_bundle_power(tmp_path: Path) -> None:
    validator = _load_validator()
    _write_phase_bundle(tmp_path, "tp.json", platform="DuckDB", power="NOT_RUN", throughput="COMPLETED")

    assert set(validator.cohort_platforms(validator.discover_bundles(tmp_path))) == {
        ("tpch", "1.0#throughput#3streams")
    }


def test_phase_names_are_case_normalized_and_standard_is_power(tmp_path: Path) -> None:
    validator = _load_validator()
    _write_bundle(tmp_path, "upper.json", benchmark="tpch", scale=1.0, platform="DuckDB", test_type="POWER")
    _write_bundle(tmp_path, "standard.json", benchmark="tpch", scale=1.0, platform="Spark", test_type="Standard")
    _write_bundle(tmp_path, "combined.json", benchmark="tpch", scale=1.0, platform="Doris", test_type="combined")
    _write_bundle(tmp_path, "none.json", benchmark="tpch", scale=1.0, platform="Polars", test_type=None)

    assert validator.cohort_platforms(validator.discover_bundles(tmp_path)) == {
        ("tpch", "1.0"): {"DuckDB", "Spark"},
        ("tpch", "1.0#combined"): {"Doris"},
        ("tpch", "1.0#unknown"): {"Polars"},
    }


def _rankable_bundle(directory: Path, name: str, platform: str, **overrides: object) -> None:
    payload: dict = {
        "benchmark": {"id": "tpch", "scale_factor": 1.0, "test_type": "power", "compliance_class": "official"},
        "platform": {"name": platform},
        "run": {"timestamp": "2026-08-01T12:00:00"},
        "summary": {"queries": {"total": 22, "passed": 22, "failed": 0}, "validation": "passed"},
    }
    payload.update(overrides)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


UNRANKABLE_OVERRIDES = {
    "failed-queries": {"summary": {"queries": {"total": 22, "passed": 21, "failed": 1}, "validation": "passed"}},
    "partial-validation": {"summary": {"queries": {"total": 22, "passed": 22, "failed": 0}, "validation": "partial"}},
    "failed-validation": {"summary": {"queries": {"total": 22, "passed": 22, "failed": 0}, "validation": "FAILED"}},
    "unofficial": {
        "benchmark": {
            "id": "tpch",
            "scale_factor": 1.0,
            "test_type": "power",
            "compliance_class": "unofficial_subscale",
        }
    },
    "translation-fallback": {
        "summary": {"queries": {"total": 22, "passed": 22, "failed": 0}, "validation": "passed"},
        "execution": {"translation": "fallback"},
    },
}


@pytest.mark.parametrize("reason", sorted(UNRANKABLE_OVERRIDES))
def test_an_unrankable_bundle_does_not_count_toward_depth(tmp_path: Path, reason: str) -> None:
    validator = _load_validator()
    _rankable_bundle(tmp_path, "a.json", "DuckDB")
    _rankable_bundle(tmp_path, "b.json", "DataFusion")
    _rankable_bundle(tmp_path, "c.json", "Spark", **UNRANKABLE_OVERRIDES[reason])

    cohorts = validator.cohort_platforms(validator.discover_bundles(tmp_path))

    assert cohorts == {("tpch", "1.0"): {"DuckDB", "DataFusion"}}
    assert validator.shallow_cohorts(cohorts) == cohorts
    assert validator.main(tmp_path) == 1


def test_a_failed_throughput_bundle_cannot_complete_a_throughput_cohort(tmp_path: Path) -> None:
    validator = _load_validator()
    for platform in ("DuckDB", "Spark"):
        _write_phase_bundle(
            tmp_path,
            f"{platform}.json",
            platform=platform,
            power="NOT_RUN",
            throughput="COMPLETED",
            test_type="throughput",
        )
    sqlite = json.loads((tmp_path / "Spark.json").read_text(encoding="utf-8"))
    sqlite["platform"]["name"] = "SQLite"
    sqlite["phases"]["throughput_test"]["status"] = "FAILED"
    sqlite["summary"] = {"queries": {"total": 66, "passed": 21, "failed": 45}, "validation": "partial"}
    (tmp_path / "SQLite.json").write_text(json.dumps(sqlite), encoding="utf-8")

    assert _throughput_cohort(validator, tmp_path) == {("tpch", "1.0#throughput#3streams"): {"DuckDB", "Spark"}}
    assert validator.main(tmp_path) == 1


def test_a_cohort_with_only_unrankable_bundles_is_reported_unranked_and_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    validator = _load_validator()
    for platform in ("BigQuery", "Databricks", "Snowflake"):
        _rankable_bundle(tmp_path, f"{platform}.json", platform, **UNRANKABLE_OVERRIDES["unofficial"])
    for platform in ("DuckDB", "DataFusion", "Spark"):
        _write_bundle(tmp_path, f"{platform}.json", benchmark="tpcds", scale=1.0, platform=platform)

    cohorts = validator.cohort_platforms(validator.discover_bundles(tmp_path))

    assert cohorts[("tpch", "1.0")] == set()
    assert validator.shallow_cohorts(cohorts) == {}
    assert validator.unranked_cohorts(cohorts) == [("tpch", "1.0")]
    assert validator.main(tmp_path) == 0
    captured = capsys.readouterr().out
    assert "tpch SF=1.0: 0 identities ([]) [UNRANKED" in captured
    assert "UNRANKED: 1 cohort(s)" in captured
    assert "All 1 ranked cohort(s) meet" in captured


@pytest.mark.parametrize("rankable", [1, 2])
def test_a_cohort_with_one_or_two_rankable_identities_still_fails(tmp_path: Path, rankable: int) -> None:
    validator = _load_validator()
    for index, platform in enumerate(("DuckDB", "DataFusion")[:rankable]):
        _rankable_bundle(tmp_path, f"ok{index}.json", platform)
    for platform in ("BigQuery", "Snowflake"):
        _rankable_bundle(tmp_path, f"{platform}.json", platform, **UNRANKABLE_OVERRIDES["unofficial"])

    shallow = validator.shallow_cohorts(validator.cohort_platforms(validator.discover_bundles(tmp_path)))

    assert len(shallow[("tpch", "1.0")]) == rankable
    assert validator.main(tmp_path) == 1


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
        "benchmark": {"id": "tpch", "scale_factor": 1.0, "test_type": "power"},
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


def test_recency_names_missing_parseable_timestamps_when_bundles_exist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A populated corpus with bad dates is distinct from an empty corpus."""
    validator = _load_validator()
    for platform in ("DuckDB", "DataFusion", "Spark"):
        _write_bundle(
            tmp_path,
            f"{platform}.json",
            benchmark="tpch",
            scale=1.0,
            platform=platform,
            run_timestamp="2026-09-05Tnot-a-time",
        )

    assert validator.main(tmp_path, as_of=dt.date(2026, 9, 5)) == 0
    captured = capsys.readouterr().out
    assert "Overall: no parseable run timestamps" in captured
    assert "Overall: no bundles" not in captured


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
        "benchmark": {"id": "tpch", "scale_factor": 1.0, "test_type": "power"},
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
    assert "All 1 ranked cohort(s) meet" in captured


def test_override_companions_are_not_read_as_bundles(tmp_path: Path) -> None:
    """A ``<stem>.override.json`` beside a bundle is a companion, not a result."""
    validator = _load_validator()
    (tmp_path / "x_sf1_duckdb_sql_20261001_000000_aaaa.json").write_text("{}")
    (tmp_path / "x_sf1_duckdb_sql_20261001_000000_aaaa.override.json").write_text("{}")
    (tmp_path / "x_sf1_duckdb_sql_20261001_000000_aaaa.manifest.json").write_text("{}")

    names = [path.name for path in validator.discover_bundles(tmp_path)]

    assert names == ["x_sf1_duckdb_sql_20261001_000000_aaaa.json"]


BUNDLE_DERIVED_EXCLUSIONS = {"failed_queries", "validation_not_clean", "unofficial_compliance"}


def _explorer_view(path: Path) -> tuple[str, bool]:
    entry = BundleTransformer().to_manifest_entry(path)
    reason = ranking_exclusion_reason(entry)
    return canonical_phase(entry.test_type), reason not in BUNDLE_DERIVED_EXCLUSIONS


def _parity_variants() -> dict[str, dict]:
    def variant(**changes: object) -> dict:
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        return data

    def with_benchmark(**changes: object) -> dict:
        data = variant()
        data["benchmark"].update(changes)
        return data

    def without_test_type(phases: dict) -> dict:
        data = variant(phases=phases)
        del data["benchmark"]["test_type"]
        return data

    clean_queries = {"total": 2, "passed": 2, "failed": 0}
    return {
        "clean": variant(),
        "failed-count": variant(summary={"queries": {"total": 2, "passed": 1, "failed": 1}, "validation": "passed"}),
        "passed-short": variant(summary={"queries": {"total": 3, "passed": 2}, "validation": "passed"}),
        "partial": variant(summary={"queries": clean_queries, "validation": "partial"}),
        "dict-status": variant(summary={"queries": clean_queries, "validation": {"status": "FAILED"}}),
        "no-validation": variant(summary={"queries": clean_queries}),
        "unvalidated-failure": variant(summary={"queries": {"total": 2, "passed": 1, "failed": 1}}),
        "translation-fallback": variant(
            summary={"queries": clean_queries, "validation": "passed"}, execution={"translation": "fallback"}
        ),
        "translation-fallback-no-validation": variant(
            summary={"queries": clean_queries}, execution={"translation": "failed"}
        ),
        "unofficial": with_benchmark(compliance_class="unofficial_nonstandard"),
        "official": with_benchmark(compliance_class="official"),
        "phase-upper": with_benchmark(test_type="POWER"),
        "phase-standard": with_benchmark(test_type="standard"),
        "phase-throughput": with_benchmark(test_type="throughput"),
        "phase-from-power": without_test_type({"power_test": {"status": "COMPLETED"}}),
        "phase-from-throughput": without_test_type({"throughput_test": {"status": "COMPLETED"}}),
        "phase-not-run-power": without_test_type(
            {"power_test": {"status": "NOT_RUN"}, "throughput_test": {"status": "COMPLETED"}}
        ),
        "phase-all-not-run": without_test_type(
            {"power_test": {"status": "NOT_RUN"}, "throughput_test": {"status": "NOT_RUN"}}
        ),
        "phase-empty": without_test_type({"power_test": {}}),
        "phase-none": without_test_type({}),
    }


@pytest.mark.parametrize("name", sorted(_parity_variants()))
def test_validator_agrees_with_the_explorer_on_phase_and_rankability(tmp_path: Path, name: str) -> None:
    validator = _load_validator()
    path = tmp_path / "bundle.json"
    payload = _parity_variants()[name]
    path.write_text(json.dumps(payload), encoding="utf-8")

    explorer_phase, explorer_rankable = _explorer_view(path)

    assert validator.bundle_phase(payload) == explorer_phase
    assert validator.bundle_rankable(payload) is explorer_rankable


def test_validator_agrees_with_the_explorer_on_every_committed_bundle() -> None:
    validator = _load_validator()
    bundles = validator.discover_bundles(BUNDLES)
    assert bundles

    disagreements = []
    for path in bundles:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (validator.bundle_phase(payload), validator.bundle_rankable(payload)) != _explorer_view(path):
            disagreements.append(path.name)

    assert not disagreements


def test_every_committed_bundle_declares_a_phase() -> None:
    validator = _load_validator()
    undeclared = [
        path.name
        for path in validator.discover_bundles(BUNDLES)
        if validator.bundle_phase(json.loads(path.read_text(encoding="utf-8"))) == "unknown"
    ]

    assert not undeclared
