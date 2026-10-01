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
    bind_index = next(
        index for index, step in enumerate(steps) if "release_artifact_consumer.py producer" in step.get("run", "")
    )
    upload_index = next(
        index for index, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    # Source check, then build with distribution verification and checksums, then the producer
    # receipt, then upload: a receipt must never bind bytes that were not verified first.
    assert source_index < build_index < bind_index < upload_index
    build = steps[build_index]["run"]
    assert "scripts/verify_distribution_binaries.py dist/*.whl dist/*.tar.gz" in build
    assert build.index("verify_distribution_binaries.py") < build.index("sha256sum")
    assert "sha256sum -- *.whl *.tar.gz > SHA256SUMS" in build
    # The receipt step runs the isolated interpreter and is the only step handed the token.
    assert steps[bind_index]["run"].startswith("python -I -S ")
    assert steps[bind_index]["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert [index for index, step in enumerate(steps) if "GH_TOKEN" in str(step.get("env", {}))] == [bind_index]
    assert jobs["dist-artifact"]["permissions"] == {"contents": "read", "actions": "read"}
    # One artifact per run attempt, so a re-run cannot be confused with the original producer.
    upload = steps[upload_index]["with"]
    assert upload["name"] == "dist-${{ github.sha }}-attempt-${{ github.run_attempt }}"
    assert "dist/producer-receipt.json" in upload["path"]
    assert "dist-artifact" in jobs["core"]["needs"]
