"""Tests for scripts/post_merge_signature.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# scripts/ has no __init__.py and is not on sys.path by default; mirror the
# sys.path injection tests/unit/scripts/conftest.py does for path_filter_decision,
# inline here since this test file lives directly under tests/unit/ (scope_limit
# for this TODO does not permit adding a conftest.py).
_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from post_merge_signature import (  # noqa: E402
    SignatureError,
    build_signature_from_job_failure,
    build_signature_from_junit,
    diff_signatures,
    load_signature,
    main,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


JUNIT_WITH_FAILURES = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="4" failures="1" errors="1" skipped="1">
    <testcase classname="tests.unit.test_foo" name="test_pass" file="tests/unit/test_foo.py" line="3" time="0.01" />
    <testcase classname="tests.unit.test_foo" name="test_fail" file="tests/unit/test_foo.py" line="8" time="0.01">
      <failure message="assert 1 == 2">AssertionError</failure>
    </testcase>
    <testcase classname="tests.unit.test_foo" name="test_error" file="tests/unit/test_foo.py" line="14" time="0.01">
      <error message="boom">RuntimeError</error>
    </testcase>
    <testcase classname="tests.unit.test_foo" name="test_skip" file="tests/unit/test_foo.py" line="20" time="0.0">
      <skipped message="not today" />
    </testcase>
  </testsuite>
</testsuites>
"""

JUNIT_ALL_PASS = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0">
    <testcase classname="tests.unit.test_foo" name="test_pass" file="tests/unit/test_foo.py" line="3" time="0.01" />
  </testsuite>
</testsuites>
"""

JUNIT_NO_FILE_ATTR = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="1" failures="1" errors="0" skipped="0">
    <testcase classname="tests.unit.test_bar" name="test_fail_no_file" time="0.01">
      <failure message="boom">AssertionError</failure>
    </testcase>
  </testsuite>
</testsuites>
"""


# ---------------------------------------------------------------------------
# build_signature_from_junit
# ---------------------------------------------------------------------------


def test_build_signature_from_junit_extracts_failures_and_errors(tmp_path: Path) -> None:
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(JUNIT_WITH_FAILURES, encoding="utf-8")

    signature = build_signature_from_junit("fast-test", junit_path)

    assert signature["job"] == "fast-test"
    assert signature["kind"] == "junit"
    assert signature["failure_ids"] == sorted(
        [
            "tests/unit/test_foo.py::test_fail",
            "tests/unit/test_foo.py::test_error",
        ]
    )
    # Passing and skipped testcases must not be counted as failures.
    assert not any("test_pass" in fid or "test_skip" in fid for fid in signature["failure_ids"])


def test_build_signature_from_junit_no_failures(tmp_path: Path) -> None:
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(JUNIT_ALL_PASS, encoding="utf-8")

    signature = build_signature_from_junit("fast-test", junit_path)

    assert signature["kind"] == "junit"
    assert signature["failure_ids"] == []


def test_build_signature_from_junit_falls_back_to_classname_without_file(tmp_path: Path) -> None:
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(JUNIT_NO_FILE_ATTR, encoding="utf-8")

    signature = build_signature_from_junit("medium-test", junit_path)

    assert signature["failure_ids"] == ["tests.unit.test_bar::test_fail_no_file"]


def test_build_signature_from_junit_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SignatureError, match="not found"):
        build_signature_from_junit("fast-test", tmp_path / "does-not-exist.xml")


def test_build_signature_from_junit_malformed_xml_raises(tmp_path: Path) -> None:
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text("<testsuites><testsuite>not closed", encoding="utf-8")

    with pytest.raises(SignatureError, match="could not parse"):
        build_signature_from_junit("fast-test", junit_path)


# ---------------------------------------------------------------------------
# build_signature_from_job_failure
# ---------------------------------------------------------------------------


def test_build_signature_from_job_failure_with_step() -> None:
    signature = build_signature_from_job_failure("lint", "Run CI lint mirror")

    assert signature == {
        "job": "lint",
        "kind": "job-failure",
        "failure_ids": ["lint:Run CI lint mirror"],
    }


def test_build_signature_from_job_failure_without_step_is_empty() -> None:
    signature = build_signature_from_job_failure("lint", None)

    assert signature == {"job": "lint", "kind": "none", "failure_ids": []}


# ---------------------------------------------------------------------------
# diff_signatures
# ---------------------------------------------------------------------------


def test_diff_signatures_returns_only_new_ids() -> None:
    previous = {"failure_ids": ["tests/a.py::test_a"]}
    current = {"failure_ids": ["tests/a.py::test_a", "tests/b.py::test_b"]}

    assert diff_signatures(previous, current) == ["tests/b.py::test_b"]


def test_diff_signatures_no_new_failures_returns_empty() -> None:
    previous = {"failure_ids": ["tests/a.py::test_a", "tests/b.py::test_b"]}
    current = {"failure_ids": ["tests/a.py::test_a"]}

    assert diff_signatures(previous, current) == []


def test_diff_signatures_empty_previous_all_current_are_new() -> None:
    previous = {"failure_ids": []}
    current = {"failure_ids": ["tests/a.py::test_a", "tests/b.py::test_b"]}

    assert diff_signatures(previous, current) == sorted(["tests/a.py::test_a", "tests/b.py::test_b"])


def test_diff_signatures_missing_previous_key_treated_as_empty() -> None:
    previous: dict[str, object] = {"job": "lint", "kind": "none"}
    current = {"failure_ids": ["lint:Run CI lint mirror"]}

    assert diff_signatures(previous, current) == ["lint:Run CI lint mirror"]


def test_diff_signatures_identical_signature_is_not_new() -> None:
    # The #1100 case at the function level: an already-red develop whose
    # signature is unchanged must not surface any "new" IDs.
    signature = {"failure_ids": ["tests/a.py::test_a"]}

    assert diff_signatures(signature, signature) == []


# ---------------------------------------------------------------------------
# load_signature
# ---------------------------------------------------------------------------


def test_load_signature_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SignatureError, match="not found"):
        load_signature(tmp_path / "missing.json")


def test_load_signature_malformed_json_raises(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(SignatureError, match="not valid json"):
        load_signature(bad_path)


def test_load_signature_missing_failure_ids_key_raises(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({"job": "lint"}), encoding="utf-8")

    with pytest.raises(SignatureError, match="failure_ids"):
        load_signature(bad_path)


def test_load_signature_non_object_json_raises(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    with pytest.raises(SignatureError, match="failure_ids"):
        load_signature(bad_path)


def test_load_signature_round_trips_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "sig.json"
    path.write_text(json.dumps({"job": "lint", "kind": "none", "failure_ids": []}), encoding="utf-8")

    signature = load_signature(path)

    assert signature["job"] == "lint"
    assert signature["failure_ids"] == []


# ---------------------------------------------------------------------------
# CLI (main())
# ---------------------------------------------------------------------------


def test_cli_build_from_junit_writes_signature_file(tmp_path: Path) -> None:
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(JUNIT_WITH_FAILURES, encoding="utf-8")
    out_path = tmp_path / "signature.json"

    exit_code = main(["build", "--job", "fast-test", "--junit", str(junit_path), "--out", str(out_path)])

    assert exit_code == 0
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["job"] == "fast-test"
    assert len(written["failure_ids"]) == 2


def test_cli_build_from_job_failure_writes_signature_file(tmp_path: Path) -> None:
    out_path = tmp_path / "signature.json"

    exit_code = main(
        [
            "build",
            "--job",
            "lint",
            "--failed-step",
            "Run CI lint mirror",
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["failure_ids"] == ["lint:Run CI lint mirror"]


def test_cli_build_without_junit_or_failed_step_is_empty_signature(tmp_path: Path) -> None:
    out_path = tmp_path / "signature.json"

    exit_code = main(["build", "--job", "lint", "--out", str(out_path)])

    assert exit_code == 0
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["kind"] == "none"
    assert written["failure_ids"] == []


def test_cli_build_from_missing_junit_returns_error_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_path = tmp_path / "signature.json"

    exit_code = main(
        [
            "build",
            "--job",
            "fast-test",
            "--junit",
            str(tmp_path / "missing.xml"),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 1
    assert not out_path.exists()
    captured = capsys.readouterr()
    assert "error:" in captured.err


def test_cli_build_from_malformed_junit_returns_error_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The workflow's emit steps rely on this non-zero exit to trigger their
    # `|| build --failed-step "... (junit xml unparseable)"` fallback when
    # pytest was killed mid-write and left a truncated junit file behind.
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text("<testsuites><testsuite>truncated mid-write", encoding="utf-8")
    out_path = tmp_path / "signature.json"

    exit_code = main(
        [
            "build",
            "--job",
            "fast-test",
            "--junit",
            str(junit_path),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 1
    assert not out_path.exists()
    captured = capsys.readouterr()
    assert "error:" in captured.err


def test_cli_diff_writes_new_failure_ids(tmp_path: Path) -> None:
    previous_path = tmp_path / "previous.json"
    current_path = tmp_path / "current.json"
    out_path = tmp_path / "diff.json"
    previous_path.write_text(json.dumps({"failure_ids": ["tests/a.py::test_a"]}), encoding="utf-8")
    current_path.write_text(json.dumps({"failure_ids": ["tests/a.py::test_a", "tests/b.py::test_b"]}), encoding="utf-8")

    exit_code = main(
        [
            "diff",
            "--previous",
            str(previous_path),
            "--current",
            str(current_path),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["new_failure_ids"] == ["tests/b.py::test_b"]


def test_cli_diff_missing_previous_file_errors_out(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    current_path = tmp_path / "current.json"
    current_path.write_text(json.dumps({"failure_ids": []}), encoding="utf-8")

    exit_code = main(
        [
            "diff",
            "--previous",
            str(tmp_path / "missing.json"),
            "--current",
            str(current_path),
        ]
    )

    # Failing loudly (non-zero exit) is required so the workflow's
    # `if ! ... ; then fail-open ; fi` pattern can catch it - the diff must
    # never be silently treated as "no new failures".
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err


def test_cli_diff_prints_new_ids_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    previous_path = tmp_path / "previous.json"
    current_path = tmp_path / "current.json"
    previous_path.write_text(json.dumps({"failure_ids": []}), encoding="utf-8")
    current_path.write_text(json.dumps({"failure_ids": ["tests/a.py::test_a"]}), encoding="utf-8")

    exit_code = main(["diff", "--previous", str(previous_path), "--current", str(current_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "tests/a.py::test_a"
