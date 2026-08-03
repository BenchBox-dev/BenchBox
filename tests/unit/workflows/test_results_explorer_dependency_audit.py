"""Regression checks for the blocking Results Explorer dependency audit."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).parents[3]


def test_browser_and_nightly_lanes_run_the_high_severity_audit() -> None:
    browser = (ROOT / ".github/workflows/results-explorer-browser.yml").read_text(encoding="utf-8")
    nightly = (ROOT / ".github/workflows/nightly.yml").read_text(encoding="utf-8")

    assert browser.count("npm run audit:high") >= 1
    assert nightly.count("npm run audit:high") >= 1


def test_audit_script_is_not_force_fix_or_unbounded() -> None:
    package_text = (ROOT / "results-explorer/package.json").read_text(encoding="utf-8")

    assert '"audit:high": "npm audit --audit-level=high"' in package_text
    assert "audit fix --force" not in package_text
