"""Require source and distribution binary verification before queue upload."""

import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]
ROOT = Path(__file__).resolve().parents[3]


def test_queue_artifact_verifies_exact_distributions_before_upload() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    steps = jobs["dist-artifact"]["steps"]
    source_index = next(
        index for index, step in enumerate(steps) if "bundled_binary_manifest.py" in step.get("run", "")
    )
    build_index = next(index for index, step in enumerate(steps) if "uv build" in step.get("run", ""))
    upload_index = next(
        index for index, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert source_index < build_index < upload_index
    build = steps[build_index]["run"]
    assert "scripts/verify_distribution_binaries.py dist/*.whl dist/*.tar.gz" in build
    assert build.index("verify_distribution_binaries.py") < build.index("sha256sum")
    assert "sha256sum -- *.whl *.tar.gz > SHA256SUMS" in build
    assert steps[upload_index]["with"]["name"] == "dist-${{ github.sha }}"
    assert "dist-artifact" in jobs["core"]["needs"]


def _uv_commands(job: dict) -> list[list[str]]:
    """Return every uv command the job runs, split on shell separators.

    A segment that mentions uv anywhere but its first word (`env uv ...`, `sudo uv ...`, an
    absolute path) is unsupported syntax and is returned as-is so the caller rejects it.
    """
    commands: list[list[str]] = []
    for step in job["steps"]:
        script = step.get("run", "").replace("\\\n", " ")
        for line in script.splitlines():
            code = line.split("#", 1)[0]
            for segment in re.split(r"[;&|()`]|\$\(", code):
                tokens = segment.split()
                if any(Path(token).name == "uv" for token in tokens):
                    commands.append(tokens)
    return commands


def test_queue_artifact_job_installs_runtime_dependencies_only() -> None:
    # The job only runs two scripts that import the package, so it needs the runtime dependencies
    # and not the dev group. A cold full sync inside a short limit timed the job out, and a failed
    # dist-artifact fails the core unit and ejects the merge group. --locked makes a stale uv.lock
    # fail the job instead of installing older versions than pyproject declares.
    job = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]["dist-artifact"]
    assert job["timeout-minutes"] >= 20
    commands = _uv_commands(job)
    expected_scripts = [
        "scripts/bundled_binary_manifest.py",
        "scripts/verify_distribution_binaries.py",
    ]
    runs = [command for command in commands if command[:2] == ["uv", "run"]]
    builds = [command for command in commands if command == ["uv", "build"]]
    # Exactly the two verifiers and one build: any other uv call (a third `uv run`, `uv sync`,
    # an absolute path, `env uv`) re-syncs the dev group or is syntax this test cannot judge.
    assert len(runs) == 2 and len(builds) == 1 and len(commands) == 3, commands
    for script, command in zip(expected_scripts, runs, strict=True):
        separator = command.index("--")
        # The flags must be uv's own, so they have to come before the `--` that ends them.
        assert {"--locked", "--no-dev"} <= set(command[2:separator]), command
        assert command[separator + 1 : separator + 3] == ["python", script], command
