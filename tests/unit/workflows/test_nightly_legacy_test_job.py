from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
LONGEST_EXPECTED_RUN_MINUTES = 40
MAX_TIMEOUT_MINUTES = 3 * LONGEST_EXPECTED_RUN_MINUTES


def _test_job() -> dict[str, Any]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/nightly.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]["test"]


def test_the_matrix_test_job_has_an_explicit_timeout_below_the_platform_default() -> None:
    timeout = _test_job().get("timeout-minutes")

    assert isinstance(timeout, int)
    assert LONGEST_EXPECTED_RUN_MINUTES < timeout <= MAX_TIMEOUT_MINUTES


def test_the_windows_legs_stay_in_the_matrix() -> None:
    includes = _test_job()["strategy"]["matrix"]["include"]

    windows = sorted(entry["python-version"] for entry in includes if entry["os"] == "windows-latest")
    assert windows == ["3.11", "3.12"]
