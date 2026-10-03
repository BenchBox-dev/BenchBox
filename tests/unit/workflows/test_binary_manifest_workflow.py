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
    assert source_index < build_index < bind_index < upload_index
    build = steps[build_index]["run"]
    assert "scripts/verify_distribution_binaries.py dist/*.whl dist/*.tar.gz" in build
    assert build.index("verify_distribution_binaries.py") < build.index("sha256sum")
    assert "sha256sum -- *.whl *.tar.gz > SHA256SUMS" in build
    assert steps[bind_index]["run"].startswith("python -I -S ")
    assert steps[bind_index]["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert [index for index, step in enumerate(steps) if "GH_TOKEN" in str(step.get("env", {}))] == [bind_index]
    assert jobs["dist-artifact"]["permissions"] == {"contents": "read", "actions": "read"}
    upload = steps[upload_index]["with"]
    assert upload["name"] == "dist-${{ github.sha }}-attempt-${{ github.run_attempt }}"
    assert "dist/producer-receipt.json" in upload["path"]
    assert "dist-artifact" in jobs["core"]["needs"]


BIND_STEP = "Bind distributions to the producer attempt"
BIND_RUN = "python -I -S scripts/release_artifact_consumer.py producer --dist dist"
VERIFY_SOURCE_RUN = "uv run --locked --no-dev -- python scripts/bundled_binary_manifest.py"
BUILD_AND_VERIFY_RUN = """\
set -euo pipefail
uv build
wheel_count=$(find dist -maxdepth 1 -name '*.whl' | wc -l | tr -d '[:space:]')
sdist_count=$(find dist -maxdepth 1 -name '*.tar.gz' | wc -l | tr -d '[:space:]')
if [ "$wheel_count" != "1" ] || [ "$sdist_count" != "1" ]; then
  echo "::error::Expected exactly one wheel and one sdist, found $wheel_count wheel(s) and $sdist_count sdist(s)"
  find dist -maxdepth 1 -type f -print
  exit 1
fi
uv run --locked --no-dev -- python scripts/verify_distribution_binaries.py dist/*.whl dist/*.tar.gz
(cd dist && sha256sum -- *.whl *.tar.gz > SHA256SUMS)
cat dist/SHA256SUMS
"""


def test_queue_artifact_job_installs_runtime_dependencies_only() -> None:
    job = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]["dist-artifact"]
    assert set(job) == {"name", "needs", "if", "runs-on", "permissions", "timeout-minutes", "steps"}
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    assert job["timeout-minutes"] >= 20

    shape = [(step["name"], step["uses"].split("@")[0] if "uses" in step else "run") for step in job["steps"]]
    assert shape == [
        ("Checkout code", "actions/checkout"),
        ("Set up Python 3.12", "actions/setup-python"),
        ("Install uv", "astral-sh/setup-uv"),
        ("Verify source bundled binary manifest", "run"),
        ("Build wheel and sdist", "run"),
        ("Bind distributions to the producer attempt", "run"),
        ("Upload dist artifact", "actions/upload-artifact"),
    ]
    runs = {step["name"]: step for step in job["steps"] if "run" in step}
    for name, step in runs.items():
        allowed = {"name", "run", "env"} if name == BIND_STEP else {"name", "run"}
        assert set(step) == allowed, step
    assert runs["Verify source bundled binary manifest"]["run"].strip() == VERIFY_SOURCE_RUN
    assert runs["Build wheel and sdist"]["run"] == BUILD_AND_VERIFY_RUN
    assert runs[BIND_STEP]["run"].strip() == BIND_RUN
    assert runs[BIND_STEP]["env"] == {"GH_TOKEN": "${{ github.token }}"}
    uses = {step["name"]: step for step in job["steps"] if "uses" in step}
    assert uses["Install uv"].keys() <= {"name", "uses"}
    assert uses["Set up Python 3.12"]["with"] == {"python-version": "3.12"}
