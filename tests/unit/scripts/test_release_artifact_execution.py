"""Exercise tag objects, isolated producer execution and fail-closed admission."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import release_artifact_consumer as consumer
from tests.unit.scripts.test_release_artifact_consumer import (
    ROOT,
    distributions as distributions,
    metadata as metadata,
    write_zip,
    zip_members,
)

pytestmark = [pytest.mark.unit, pytest.mark.medium]


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "tag.gpgSign=false",
            "-C",
            str(root),
            *args,
        ],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


@pytest.fixture
def tagged_source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-b", "develop")
    git(root, "config", "user.name", "Test Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / "pyproject.toml").write_text('[project]\nname = "benchbox"\nversion = "0.4.2"\n')
    git(root, "add", "pyproject.toml")
    git(root, "commit", "-m", "Tagged package")
    git(root, "update-ref", "refs/remotes/origin/develop", "HEAD")
    git(root, "tag", "-a", "v0.4.2", "-m", "Release")
    return root


def test_real_annotated_tag_on_develop_resolves_exact_commit(tagged_source):
    source = consumer.resolve_tag(tagged_source, "v0.4.2")
    assert source["head_sha"] == git(tagged_source, "rev-parse", "HEAD")
    assert source["tag_object"] != source["head_sha"]
    assert source["version"] == "0.4.2"


@pytest.mark.parametrize("case", ["tracked", "untracked", "staged"])
def test_dirty_tagged_source_is_not_trusted(tagged_source, case):
    if case == "tracked":
        (tagged_source / "pyproject.toml").write_text("changed source")
    else:
        (tagged_source / "injected.py").write_text("untrusted verifier bytes")
        if case == "staged":
            git(tagged_source, "add", "injected.py")
    with pytest.raises(ValueError, match="checkout is dirty"):
        consumer.resolve_tag(tagged_source, "v0.4.2")


@pytest.mark.parametrize("case", ["lightweight", "off_develop", "version", "checkout", "branch"])
def test_real_invalid_tag_or_checkout_refuses_admission(tagged_source, case):
    tag = "v0.4.2"
    if case == "lightweight":
        git(tagged_source, "tag", "-d", tag)
        git(tagged_source, "tag", tag)
    elif case in {"off_develop", "checkout"}:
        (tagged_source / "later.txt").write_text("Later source")
        git(tagged_source, "add", "later.txt")
        git(tagged_source, "commit", "-m", "Later source")
        if case == "off_develop":
            git(tagged_source, "tag", "-d", tag)
            git(tagged_source, "tag", "-a", tag, "-m", "Off develop")
    elif case == "version":
        tag = "v0.4.3"
        git(tagged_source, "tag", "-a", tag, "-m", "Wrong version")
    else:
        tag = "develop"
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        consumer.resolve_tag(tagged_source, tag)


def test_release_candidate_uses_existing_version_normalization(tagged_source):
    (tagged_source / "pyproject.toml").write_text('[project]\nname = "benchbox"\nversion = "0.4.2rc1"\n')
    git(tagged_source, "add", "pyproject.toml")
    git(tagged_source, "commit", "-m", "Candidate version")
    git(tagged_source, "update-ref", "refs/remotes/origin/develop", "HEAD")
    git(tagged_source, "tag", "-a", "v0.4.2-rc.1", "-m", "Candidate")
    assert consumer.resolve_tag(tagged_source, "v0.4.2-rc.1")["version"] == "0.4.2rc1"


def install_gh(tmp_path, monkeypatch, responses=None, archive=None):
    executable = tmp_path / "gh"
    executable.write_text(
        f"#!{sys.executable}\nimport json,sys,pathlib\n"
        f"responses={responses!r}\narchive={str(archive)!r}\n"
        "endpoint=sys.argv[2]\n"
        "if endpoint.endswith('/zip'):\n"
        " sys.stdout.buffer.write(pathlib.Path(archive).read_bytes())\n"
        "else:\n"
        " print(json.dumps(responses[endpoint]))\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))


@pytest.mark.parametrize("attempt", ["2", "3"])
def test_producer_command_uses_real_isolated_process_and_attempt_api(
    tmp_path, monkeypatch, distributions, metadata, attempt
):
    receipt_path = distributions / consumer.PRODUCER_RECEIPT
    receipt_path.unlink()
    metadata["run"].update(status="in_progress", conclusion=None)
    metadata["job"].update(status="in_progress", conclusion=None)
    prefix = f"repos/{consumer.REPOSITORY}/"
    responses = {
        prefix + "actions/runs/7": metadata["run"],
        prefix + "actions/runs/7/attempts/2/jobs?per_page=100&page=1": {"total_count": 1, "jobs": [metadata["job"]]},
    }
    install_gh(tmp_path, monkeypatch, responses=responses)
    for key, value in {
        "GITHUB_RUN_ID": "7",
        "GITHUB_RUN_ATTEMPT": attempt,
        "GITHUB_SHA": metadata["run"]["head_sha"],
        "GITHUB_REPOSITORY_ID": "1135770337",
    }.items():
        monkeypatch.setenv(key, value)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "scripts/release_artifact_consumer.py"),
            "producer",
            "--dist",
            str(distributions),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    if attempt == "3":
        assert result.returncode != 0 and "workflow context differs" in result.stderr
        assert not receipt_path.exists()
    else:
        assert result.returncode == 0, result.stderr
        receipt = json.loads(receipt_path.read_text())
        assert (receipt["run_id"], receipt["run_attempt"], receipt["job_id"]) == (7, 2, 9)
        for name, info in receipt["files"].items():
            assert info["sha256"] == hashlib.sha256((distributions / name).read_bytes()).hexdigest()


def test_missing_actual_binary_verifier_fails_without_admission_output(
    tmp_path, monkeypatch, tagged_source, distributions, metadata
):
    sha = git(tagged_source, "rev-parse", "HEAD")
    metadata["run"]["head_sha"] = sha
    metadata["job"]["head_sha"] = sha
    metadata["artifact"]["workflow_run"]["head_sha"] = sha
    metadata["artifact"]["name"] = f"dist-{sha}-attempt-2"
    receipt = consumer.producer_receipt(distributions, metadata["run"], metadata["job"])
    (distributions / consumer.PRODUCER_RECEIPT).write_text(json.dumps(receipt))
    archive = tmp_path / "download.zip"
    digest = write_zip(archive, zip_members(distributions))
    metadata["artifact"].update(digest)
    install_gh(tmp_path, monkeypatch, archive=archive)
    output = tmp_path / "admitted"
    with pytest.raises(ValueError, match="lacks required distribution binary verifier"):
        consumer.admit(tagged_source, "v0.4.2", output, metadata["api"])
    assert not output.exists()
    assert not list(tmp_path.glob("release-admission-*"))


def test_oversized_download_stream_refused(tmp_path, monkeypatch):
    archive = tmp_path / "large.zip"
    archive.write_bytes(b"x" * 64)
    install_gh(tmp_path, monkeypatch, archive=archive)
    monkeypatch.setattr(consumer, "MAX_PAYLOAD_BYTES", 16)
    target = tmp_path / "download.zip"
    with pytest.raises(ValueError, match="size limit"):
        consumer._download(11, target)


def test_existing_output_is_never_overwritten(tmp_path, tagged_source, metadata):
    sha = git(tagged_source, "rev-parse", "HEAD")
    metadata["run"]["head_sha"] = sha
    metadata["job"]["head_sha"] = sha
    metadata["artifact"]["workflow_run"]["head_sha"] = sha
    metadata["artifact"]["name"] = f"dist-{sha}-attempt-2"
    metadata["artifact"]["digest"] = "sha256:" + "b" * 64
    output = tmp_path / "admitted"
    output.mkdir()
    (output / "keep").write_text("prior")
    with pytest.raises(ValueError, match="output already exists"):
        consumer.admit(tagged_source, "v0.4.2", output, metadata["api"])
    assert (output / "keep").read_text() == "prior"
