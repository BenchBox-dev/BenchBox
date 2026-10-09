from __future__ import annotations

import sys
from pathlib import Path

import pytest

from _project.scripts.oracle_reviewers.policy import Policy, load_policy

REPO_ROOT = Path(__file__).resolve().parents[4]
POLICY_PATH = REPO_ROOT / ".github" / "oracle-reviewers.yml"


@pytest.fixture(scope="session")
def policy() -> Policy:
    return load_policy(POLICY_PATH)


WINDOWS_SKIP = pytest.mark.skip(
    reason="the oracle reviewer tooling runs on Linux Actions runners: it uses POSIX paths, process groups and shebang CLIs"
)


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    for item in items:
        if Path(__file__).parent in Path(str(item.path)).parents:
            item.add_marker(WINDOWS_SKIP)
