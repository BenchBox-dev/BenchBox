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
    # dist-artifact fails the core unit and ejects the merge group.
    job = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]["dist-artifact"]
    assert job["timeout-minutes"] >= 20
    for step in job["steps"]:
        run = step.get("run", "")
        for line in (line.strip() for line in run.splitlines()):
            if line.startswith("uv run ") or " uv run " in line:
                assert "--no-dev" in line and "--frozen" in line, f"{step['name']}: {line}"
            assert "uv sync" not in line, f"{step['name']}: {line}"
