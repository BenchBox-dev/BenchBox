from __future__ import annotations

from pathlib import Path

import pytest

from _project.scripts.oracle_reviewers.policy import Policy, load_policy

REPO_ROOT = Path(__file__).resolve().parents[4]
POLICY_PATH = REPO_ROOT / ".github" / "oracle-reviewers.yml"


@pytest.fixture(scope="session")
def policy() -> Policy:
    return load_policy(POLICY_PATH)
