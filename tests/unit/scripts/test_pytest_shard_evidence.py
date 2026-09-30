"""Exercise shard evidence against real serial and distributed pytest runs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("workers", [0, 2])
@pytest.mark.parametrize("case", ["complete", "missing", "failure", "skip"])
def test_actual_pytest_shard_execution(tmp_path: Path, workers: int, case: str) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    body = "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n"
    if case == "failure":
        body = body.replace("def test_b():\n    assert True", "def test_b():\n    assert False")
    if case == "skip":
        body = "import pytest\n" + body.replace("def test_b():", "@pytest.mark.skip(reason='fixture')\ndef test_b():")
    (tests / "test_cases.py").write_text(body)
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts =\n")
    assigned = ["tests/test_cases.py::test_a", "tests/test_cases.py::test_b"]
    assignment = tmp_path / "assignment.txt"
    assignment.write_text("\n".join(assigned) + "\n")
    evidence = tmp_path / "execution.json"
    selected = assigned[:1] if case == "missing" else assigned
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-n",
            str(workers),
            "-p",
            "xdist.plugin",
            "-p",
            "scripts.pytest_shard_evidence",
            "--assigned-nodeids",
            str(assignment),
            "--shard-evidence",
            str(evidence),
            "--checked-sha",
            "a" * 40,
            *selected,
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(evidence.read_text())
    assert result.returncode == (1 if case in {"missing", "failure"} else 0), result.stdout + result.stderr
    assert payload["complete"] is (case != "missing")
    assert payload["commit_sha"] == "a" * 40
    assert payload["assigned_node_ids"] == assigned
    assert len(payload["collected_node_ids"]) == (workers or 1)
    assert all(collection == selected for collection in payload["collected_node_ids"])
    assert payload["executed_node_ids"] == selected
    assert payload["pytest_exit_status"] == (1 if case == "failure" else 0)
