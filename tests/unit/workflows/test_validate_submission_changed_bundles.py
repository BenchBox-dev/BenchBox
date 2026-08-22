"""Regression tests for companion-only submission workflow changes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.utilities.posix_shell import run_posix_shell, skip_without_posix_shell

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "validate-submission.yml"


def _changed_bundle_discovery_script() -> str:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["validate"]["steps"] if step.get("id") == "changed")
    run = step["run"]
    start = run.index("CHANGED=$(git diff")
    end = run.index('if [ -z "$CHANGED" ]')
    return (
        run[start:end].replace("${{ github.event.pull_request.base.sha }}", "$BASE_SHA") + 'printf "%s\\n" "$CHANGED"\n'
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_applied_only_change_discovers_paired_primary_bundle(tmp_path: Path) -> None:
    """An applied-ledger-only edit must still invoke primary-bundle validation."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")

    primary = tmp_path / "results-data" / "bundles" / "result.json"
    primary.parent.mkdir(parents=True)
    primary.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", str(primary.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")

    applied = primary.with_name("result.applied.json")
    applied.write_text('{"status": "passed"}\n', encoding="utf-8")
    _git(tmp_path, "add", str(applied.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "applied")

    skip_without_posix_shell()
    env = os.environ.copy()
    env["BASE_SHA"] = base_sha
    result = run_posix_shell(
        _changed_bundle_discovery_script(),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["results-data/bundles/result.json"]


def test_case_insensitive_primary_bundle_discovery_matches_validator(tmp_path: Path) -> None:
    """Submission CI must validate every extension casing accepted by bundle discovery."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "commit", "--quiet", "--allow-empty", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")

    bundle_dir = tmp_path / "results-data" / "bundles"
    bundle_dir.mkdir(parents=True)
    primary = bundle_dir / "result.JSON"
    primary.write_text("{}\n", encoding="utf-8")
    (bundle_dir / "result.PLANS.JSON").write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", str(bundle_dir.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "uppercase bundle")

    skip_without_posix_shell()
    env = os.environ.copy()
    env["BASE_SHA"] = base_sha
    result = run_posix_shell(
        _changed_bundle_discovery_script(),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["results-data/bundles/result.JSON"]


def test_applied_companion_derivation_is_deletion_aware() -> None:
    """The workflow must inspect an existing primary when its companion is removed."""
    script = _changed_bundle_discovery_script()
    assert "--diff-filter=ACMRD" in script
    assert "CHANGED_APPLIED" in script
    assert 'awk -v stem="$stem"' in script
    assert 'git cat-file -e "HEAD:${bundle}"' in script


def test_applied_companion_rename_discovers_the_source_primary_bundle(tmp_path: Path) -> None:
    """A companion rename must validate the source primary bundle still in HEAD."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")

    primary = tmp_path / "results-data" / "bundles" / "result.json"
    primary.parent.mkdir(parents=True)
    primary.write_text("{}\n", encoding="utf-8")
    applied = primary.with_name("result.applied.json")
    applied.write_text('{"status": "passed"}\n', encoding="utf-8")
    _git(tmp_path, "add", str(primary.relative_to(tmp_path)), str(applied.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")

    renamed = applied.with_name("renamed.applied.json")
    applied.rename(renamed)
    _git(tmp_path, "add", "-u", str(applied.relative_to(tmp_path)))
    _git(tmp_path, "add", str(renamed.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "rename-applied")

    skip_without_posix_shell()
    env = os.environ.copy()
    env["BASE_SHA"] = base_sha
    result = run_posix_shell(
        _changed_bundle_discovery_script(),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["results-data/bundles/result.json"]


def test_companion_pairing_preserves_stem_case(tmp_path: Path) -> None:
    """Case-insensitive extensions must not conflate distinct case-sensitive stems."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")

    blob_file = tmp_path / "blob"
    blob_file.write_text("{}\n", encoding="utf-8")
    base_blob = _git(tmp_path, "hash-object", "-w", str(blob_file))
    for path in (
        "results-data/bundles/FOO.JSON",
        "results-data/bundles/foo.json",
        "results-data/bundles/foo.applied.json",
    ):
        _git(tmp_path, "update-index", "--add", "--cacheinfo", f"100644,{base_blob},{path}")
    _git(tmp_path, "commit", "--quiet", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")

    blob_file.write_text('{"status": "passed"}\n', encoding="utf-8")
    applied_blob = _git(tmp_path, "hash-object", "-w", str(blob_file))
    _git(
        tmp_path,
        "update-index",
        "--add",
        "--cacheinfo",
        f"100644,{applied_blob},results-data/bundles/foo.applied.json",
    )
    _git(tmp_path, "commit", "--quiet", "-m", "applied")

    skip_without_posix_shell()
    env = os.environ.copy()
    env["BASE_SHA"] = base_sha
    result = run_posix_shell(
        _changed_bundle_discovery_script(),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["results-data/bundles/foo.json"]


@pytest.mark.parametrize("companion_suffix", [".plans.json", ".tuning.json"])
def test_plans_or_tuning_only_change_discovers_paired_primary_bundle(tmp_path: Path, companion_suffix: str) -> None:
    """A plans- or tuning-only edit must still invoke primary-bundle validation.

    ``.manifest.json`` and ``.applied.json`` each have an explicit back-mapping
    block, but ``.plans.json`` and ``.tuning.json`` are filtered out of CHANGED
    with no equivalent. A companion-only PR would therefore skip bundle
    validation, public path scanning, companion hash validation, and corpus
    inventory validation - and the public privacy scanner explicitly targets
    exactly these two suffixes.
    """
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")

    primary = tmp_path / "results-data" / "bundles" / "result.json"
    primary.parent.mkdir(parents=True)
    primary.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", str(primary.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")

    companion = primary.with_name(f"result{companion_suffix}")
    companion.write_text('{"note": "companion only"}\n', encoding="utf-8")
    _git(tmp_path, "add", str(companion.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "companion only")

    skip_without_posix_shell()
    env = os.environ.copy()
    env["BASE_SHA"] = base_sha
    result = run_posix_shell(
        _changed_bundle_discovery_script(),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["results-data/bundles/result.json"]


@pytest.mark.parametrize("companion_suffix", [".plans.json", ".tuning.json"])
def test_live_orphan_companion_is_rejected(tmp_path: Path, companion_suffix: str) -> None:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    placeholder = tmp_path / "README"
    placeholder.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README")
    _git(tmp_path, "commit", "--quiet", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")

    companion = tmp_path / "results-data" / "bundles" / f"orphan{companion_suffix}"
    companion.parent.mkdir(parents=True)
    companion.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", str(companion.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "orphan")

    skip_without_posix_shell()
    env = {**os.environ, "BASE_SHA": base_sha}
    result = run_posix_shell(
        _changed_bundle_discovery_script(),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert str(companion.relative_to(tmp_path)) in result.stdout
    assert "has no primary bundle" in result.stdout


@pytest.mark.parametrize("companion_suffix", [".plans.json", ".tuning.json"])
def test_deleted_orphan_companion_is_allowed(tmp_path: Path, companion_suffix: str) -> None:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    companion = tmp_path / "results-data" / "bundles" / f"orphan{companion_suffix}"
    companion.parent.mkdir(parents=True)
    companion.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", str(companion.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "base orphan")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")
    companion.unlink()
    _git(tmp_path, "add", "-u")
    _git(tmp_path, "commit", "--quiet", "-m", "remove orphan")

    skip_without_posix_shell()
    env = {**os.environ, "BASE_SHA": base_sha}
    result = run_posix_shell(
        _changed_bundle_discovery_script(),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
