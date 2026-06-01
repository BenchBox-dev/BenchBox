"""Drift guard: the CLI and UAT must agree on submit terminal state.

`benchbox submit` (benchbox/cli/commands/submit.py) and the UAT runner
(tests/uat/runner.py) both consume
benchbox.core.results.submit_classification. This contract drives a matrix of
result fixtures through every surface and asserts the verdicts cannot diverge:
add a refused compliance class or change the policy in one place and this test
fails if the other surface does not follow.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from benchbox.core.results.loader import load_result_file
from benchbox.core.results.submit_classification import (
    SubmitTerminalState,
    classify_loaded_result,
    classify_result_path,
)
from tests.uat import runner

sub = importlib.import_module("benchbox.cli.commands.submit")

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _write_result_json(
    path: Path,
    *,
    failed: int = 0,
    validation: str = "passed",
    compliance_class: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    passed = 1 if failed == 0 else 0
    payload: dict = {
        "version": "2.1",
        "run": {"id": "contract", "timestamp": "2026-01-01T00:00:00", "total_duration_ms": 1},
        "benchmark": {"id": "tpch", "name": "TPC-H", "scale_factor": 0.01, "test_type": "power"},
        "platform": {"name": "DuckDB"},
        "summary": {
            "queries": {"total": 1, "passed": passed, "failed": failed},
            "validation": {"status": validation},
        },
        "queries": [{"id": "Q1", "status": "SUCCESS" if failed == 0 else "ERROR", "execution_time_ms": 1}],
        "phases": {},
    }
    if compliance_class is not None:
        payload["benchmark"]["compliance_class"] = compliance_class
    path.write_text(json.dumps(payload), encoding="utf-8")


# Each entry: label -> (file-builder | None for missing, expected terminal state, loadable?)
def _loadable_cases(tmp_path: Path) -> list[tuple[str, Path, SubmitTerminalState]]:
    clean = tmp_path / "clean.json"
    _write_result_json(clean)

    query_failure = tmp_path / "query-failure.json"
    _write_result_json(query_failure, failed=1)

    schema_violation = tmp_path / "schema-violation.json"
    _write_result_json(schema_violation, failed=0, validation="failed")

    unofficial = tmp_path / "unofficial.json"
    _write_result_json(unofficial, compliance_class="unofficial_subscale")

    return [
        ("clean", clean, SubmitTerminalState.submittable),
        ("query_failure", query_failure, SubmitTerminalState.query_failure),
        ("schema_violation", schema_violation, SubmitTerminalState.schema_violation),
        ("unofficial", unofficial, SubmitTerminalState.unofficial),
    ]


def test_submit_classifier_contract_loaded_and_path_agree(tmp_path: Path):
    """Loaded-result policy (CLI side) and path policy (UAT side) agree per state."""
    for label, path, expected in _loadable_cases(tmp_path):
        # Path-based policy (used by UAT's classify_for_submit).
        assert classify_result_path(path) is expected, label
        # UAT adapter delegates to the shared path policy.
        assert runner.classify_for_submit(path) is runner.SubmitTerminalState.__members__[expected.name], label
        # Loaded-result policy (used by `benchbox submit`) agrees on the same file.
        loaded, _raw = load_result_file(path)
        assert classify_loaded_result(loaded) is expected, label


def test_submit_classifier_contract_path_only_states(tmp_path: Path):
    """Missing and malformed inputs resolve identically via the shared path policy."""
    missing = tmp_path / "does-not-exist.json"
    assert classify_result_path(missing) is SubmitTerminalState.missing_manifest
    assert classify_result_path(None) is SubmitTerminalState.missing_manifest
    assert runner.classify_for_submit(missing) is runner.SubmitTerminalState.missing_manifest

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not valid json", encoding="utf-8")
    assert classify_result_path(malformed) is SubmitTerminalState.schema_violation
    assert runner.classify_for_submit(malformed) is runner.SubmitTerminalState.schema_violation


def test_submit_classifier_contract_cli_refusal_tracks_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The CLI's externally observable refuse/accept verdict equals the shared state."""
    out_dir = tmp_path / "out"
    for label, path, expected in _loadable_cases(tmp_path):
        loaded, _raw = load_result_file(path)
        monkeypatch.setattr(sub, "load_result_file", lambda *_a, _r=loaded, **_k: (_r, {}))
        result = CliRunner().invoke(sub.submit, [str(path), "--dry-run", "--output", str(out_dir)])

        if expected is SubmitTerminalState.submittable:
            # The classifier accepts: the CLI must not refuse on classification
            # grounds. (Downstream bundle/dry-run validation is orthogonal and
            # may still flag a minimal fixture — that is not this contract.)
            assert "Submission refused" not in result.output, f"{label}: {result.output}"
        else:
            assert result.exit_code == 1, f"{label}: {result.output}"
            assert "Submission refused" in result.output, label
            if expected is SubmitTerminalState.unofficial:
                assert "compliance_class" in result.output, label
            else:
                assert "not a clean pass" in result.output, label
