"""The submission workflow must reject non-data corpus paths via the allowlist.

A2 corpus trust isolation adds a positive data-only allowlist gate
(``corpus_permit_rejections`` in scripts/validate_submission.py) that refuses
any changed corpus file that is not a supported ``.json`` data file. This suite
pins the workflow step that feeds the PR's changed file set through the gate and
executes the real ``run:`` block under a real shell to prove it fails closed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

from tests.utilities.posix_shell import run_posix_shell, skip_without_posix_shell

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "validate-submission.yml"


def _corpus_step() -> dict:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return next(step for step in workflow["jobs"]["validate"]["steps"] if step.get("id") == "corpus-paths")


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_corpus_allowlist_step_present_and_feeds_changed_paths() -> None:
    step = _corpus_step()

    run = _collapse(step.get("run", ""))
    assert "--corpus-changed-paths" in run
    assert "/tmp/corpus_changed_paths.txt" in run
    assert "scripts/validate_submission.py" in run
    assert "results-data/bundles/**" in step["run"]


def test_corpus_allowlist_step_fails_closed_on_disallowed_path(tmp_path: Path) -> None:
    """A PR that only smuggles a non-data file under the corpus tree fails."""
    skip_without_posix_shell()

    script = _corpus_step()["run"]
    validator = f"{sys.executable} {REPO_ROOT / 'scripts' / 'validate_submission.py'}"
    script = script.replace("uv run -- python scripts/validate_submission.py", validator)

    run = run_posix_shell(
        f"set -e\n"
        f"git init -q && git config user.email t@t && git config user.name t\n"
        f"git commit -q --allow-empty -m seed\n"
        f"mkdir -p results-data/bundles\n"
        f"printf 'x' > results-data/bundles/evil.sh\n"
        f"git add -A && git commit -q -m evil\n"
        f"export BASE_SHA=$(git rev-parse HEAD~1)\n"
        f"{script}",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "CORPUS_CHANGED_PATHS_FILE": str(tmp_path / "changed.txt"),
        },
    )

    assert run.returncode != 0, f"allowlist gate failed open; stderr:\n{run.stderr}"
    assert "disallowed corpus path" in f"{run.stdout}\n{run.stderr}"


def test_corpus_allowlist_step_passes_for_only_supported_data(tmp_path: Path) -> None:
    """A submission of only supported .json data files must not be blocked."""
    skip_without_posix_shell()

    script = _corpus_step()["run"]
    validator = f"{sys.executable} {REPO_ROOT / 'scripts' / 'validate_submission.py'}"
    script = script.replace("uv run -- python scripts/validate_submission.py", validator)

    run = run_posix_shell(
        f"set -e\n"
        f"git init -q && git config user.email t@t && git config user.name t\n"
        f"git commit -q --allow-empty -m seed\n"
        f"mkdir -p results-data/bundles\n"
        f"printf '{{}}' > results-data/bundles/bundle.json\n"
        f"git add -A && git commit -q -m data\n"
        f"export BASE_SHA=$(git rev-parse HEAD~1)\n"
        f"{script}",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "CORPUS_CHANGED_PATHS_FILE": str(tmp_path / "changed.txt"),
        },
    )

    assert run.returncode == 0, (
        f"allowlist gate over-rejected supported data; rc={run.returncode}\n"
        f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    )
