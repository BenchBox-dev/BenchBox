"""Require source and distribution binary verification before queue upload."""

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


def test_queue_artifact_job_installs_runtime_dependencies_only() -> None:
    # The job only runs two scripts that import the package, so it needs the runtime dependencies
    # and not the dev group. A cold full sync inside a short limit timed the job out, and a failed
    # dist-artifact fails the core unit and ejects the merge group. --locked makes a stale uv.lock
    # fail the job instead of installing older versions than pyproject declares.
    job = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]["dist-artifact"]
    assert job["timeout-minutes"] >= 20
    commands = [
        line.split("#", 1)[0].split()
        for step in job["steps"]
        for line in step.get("run", "").replace("\\\n", " ").splitlines()
        if "uv " in line.split("#", 1)[0]
    ]
    scripts = {"scripts/bundled_binary_manifest.py", "scripts/verify_distribution_binaries.py"}
    for script in scripts:
        (tokens,) = [c for c in commands if script in c]
        assert tokens[:2] == ["uv", "run"] and "--locked" in tokens and "--no-dev" in tokens, tokens
        assert tokens.index("--") < tokens.index("python"), tokens
    # Any other uv call must be `uv build` (isolated build env); nothing may sync the dev group.
    assert all(c[:2] == ["uv", "run"] or c[:2] == ["uv", "build"] for c in commands), commands
