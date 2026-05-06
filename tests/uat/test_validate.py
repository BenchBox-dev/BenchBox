"""Fast-test coverage for tests/uat/phases/validate.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.uat.phases import validate

pytestmark = pytest.mark.fast


def _write_tsv(path: Path, statuses: list[str]) -> None:
    lines = [
        "platform\tbenchmark\tscale\tresult_path\tvalidator_status\terror_count\twarning_count\tfirst_error",
    ]
    for i, status in enumerate(statuses):
        lines.append(f"duckdb\ttpch\t0.01\t/tmp/r{i}.json\t{status}\t0\t0\t")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_rollup_all_clean(tmp_path: Path):
    tsv = tmp_path / "rollup.tsv"
    _write_tsv(tsv, ["clean", "clean", "clean"])
    out = validate.parse_rollup(tsv, floor=0.80)
    assert out.clean_count == 3
    assert out.clean_rate == 1.0
    assert out.floor_breached is False


def test_parse_rollup_breaches_floor(tmp_path: Path):
    tsv = tmp_path / "rollup.tsv"
    _write_tsv(tsv, ["clean", "error", "error", "error", "error"])
    out = validate.parse_rollup(tsv, floor=0.80)
    assert out.error_count == 4
    assert out.clean_count == 1
    assert out.clean_rate == 0.2
    assert out.floor_breached is True
    assert out.exit_code() == 1


def test_parse_rollup_excludes_refused_from_denominator(tmp_path: Path):
    tsv = tmp_path / "rollup.tsv"
    _write_tsv(tsv, ["clean", "clean", "refused-by-cli"])
    out = validate.parse_rollup(tsv, floor=0.80)
    # Denominator is 2 (refused excluded) → clean_rate = 1.0.
    assert out.refused_count == 1
    assert out.clean_rate == 1.0


def test_parse_rollup_warning_only_counts_against_clean_rate(tmp_path: Path):
    tsv = tmp_path / "rollup.tsv"
    _write_tsv(tsv, ["clean", "warning_only", "warning_only", "warning_only"])
    out = validate.parse_rollup(tsv, floor=0.80)
    assert out.clean_rate == 0.25  # only the one clean bundle counts


def test_parse_rollup_missing_status_column_errors(tmp_path: Path):
    tsv = tmp_path / "broken.tsv"
    tsv.write_text("foo\tbar\n", encoding="utf-8")
    with pytest.raises(ValueError, match="validator_status"):
        validate.parse_rollup(tsv)


def test_has_rollup_script_in_repo():
    assert validate.has_rollup_script() is True


def test_run_validate_surfaces_nonzero_subprocess_via_exit_code(tmp_path: Path):
    """Validator non-zero exit must NOT raise when a TSV is still produced."""
    tsv = tmp_path / "rollup.tsv"

    def fake_runner(argv, check):
        _write_tsv(tsv, ["clean", "clean"])

        class Completed:
            returncode = 7

        return Completed()

    out = validate.run_validate(
        tmp_path / "results",
        output_tsv=tsv,
        runner=fake_runner,
    )
    assert out.script_returncode == 7
    assert out.exit_code() == 7
    assert out.clean_count == 2


def test_parse_validator_status_by_path_round_trip(tmp_path: Path):
    tsv = tmp_path / "rollup.tsv"
    _write_tsv(tsv, ["clean", "warning_only", "error"])
    status_by_path = validate.parse_validator_status_by_path(tsv)
    # _write_tsv writes /tmp/rN.json result_path values.
    keys = {str(p) for p in status_by_path}
    assert str(Path("/tmp/r0.json").resolve()) in keys
    assert status_by_path[Path("/tmp/r0.json").resolve()] == "clean"
    assert status_by_path[Path("/tmp/r1.json").resolve()] == "warning_only"
    assert status_by_path[Path("/tmp/r2.json").resolve()] == "error"


def test_parse_validator_status_by_path_normalizes_relative_paths(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tsv = tmp_path / "rollup.tsv"
    tsv.write_text(
        "platform\tbenchmark\tscale\tresult_path\tvalidator_status\terror_count\twarning_count\tfirst_error\n"
        "duckdb\ttpch\t0.01\tbenchmark_runs/results/r0.json\terror\t0\t0\t\n",
        encoding="utf-8",
    )

    status_by_path = validate.parse_validator_status_by_path(tsv)

    assert status_by_path == {(tmp_path / "benchmark_runs" / "results" / "r0.json").resolve(): "error"}


def test_parse_validator_status_by_path_handles_missing_columns(tmp_path: Path):
    tsv = tmp_path / "rollup.tsv"
    tsv.write_text("foo\tbar\n", encoding="utf-8")
    assert validate.parse_validator_status_by_path(tsv) == {}


def test_run_validate_raises_when_subprocess_fails_and_no_tsv(tmp_path: Path):
    """No TSV → ValidatePhaseError, never CalledProcessError."""
    missing_tsv = tmp_path / "rollup.tsv"

    def fake_runner(argv, check):
        class Completed:
            returncode = 5

        return Completed()

    with pytest.raises(validate.ValidatePhaseError, match="exited 5"):
        validate.run_validate(
            tmp_path / "results",
            output_tsv=missing_tsv,
            runner=fake_runner,
        )


def test_run_validate_ignores_stale_tsv_when_subprocess_fails(tmp_path: Path):
    """A previous rollup must not make a failed validator look parseable."""
    stale_tsv = tmp_path / "rollup.tsv"
    _write_tsv(stale_tsv, ["clean"])

    def fake_runner(argv, check):
        class Completed:
            returncode = 5

        return Completed()

    with pytest.raises(validate.ValidatePhaseError, match="exited 5"):
        validate.run_validate(
            tmp_path / "results",
            output_tsv=stale_tsv,
            runner=fake_runner,
        )
    assert not stale_tsv.exists()
