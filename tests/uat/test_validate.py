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
