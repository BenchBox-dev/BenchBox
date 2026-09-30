"""Exercise both soundness policies without sharing imports or manifest state."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import heavy_tier_needed as heavy

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_FILES = (
    "_project/scripts/auto_merge_soundness_paths.py",
    "_project/scripts/soundness_paths.py",
    ".github/soundness-paths.txt",
)


@pytest.fixture
def policy_sources() -> dict[str, str]:
    return {path: (REPO_ROOT / path).read_text(encoding="utf-8") for path in POLICY_FILES}


def _decision(paths: list[str]) -> dict:
    return {"needs_code_ci": True, "packaging_needed": False, "changed_paths": paths}


def _classify(paths: list[str], base: dict[str, str], pr: dict[str, str]) -> dict:
    return heavy.heavy_needed(
        _decision(paths),
        "pull_request",
        "base",
        REPO_ROOT,
        read_base=lambda *_: base,
        read_pr=lambda *_: pr,
    )


def test_real_base_policy_does_not_expand_an_ordinary_code_change() -> None:
    result = heavy.heavy_needed(
        _decision(["benchbox/core/platform_registry.py"]), "pull_request", "origin/develop", REPO_ROOT
    )
    assert result["heavy_needed"] is False, result["reason"]


@pytest.mark.parametrize(
    "base_rule,pr_rule,expected", [(True, False, True), (False, True, True), (False, False, False)]
)
def test_policy_union_keeps_base_removals_and_pr_additions(
    policy_sources: dict[str, str], base_rule: bool, pr_rule: bool, expected: bool
) -> None:
    manifest = policy_sources[POLICY_FILES[2]].replace("file\tAGENTS.md\n", "")
    base = {**policy_sources, POLICY_FILES[2]: manifest + ("file\tAGENTS.md\n" if base_rule else "")}
    pr = {**policy_sources, POLICY_FILES[2]: manifest + ("file\tAGENTS.md\n" if pr_rule else "")}
    result = _classify(["AGENTS.md"], base, pr)
    assert result["heavy_needed"] is expected, result["reason"]


def test_ambient_imports_and_manifest_cannot_replace_either_policy(
    policy_sources: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "soundness_paths.py").write_text("raise RuntimeError('ambient module used')\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("SOUNDNESS_PATH_MANIFEST", str(tmp_path / "absent"))
    monkeypatch.setitem(sys.modules, "soundness_paths", object())
    assert _classify(["AGENTS.md"], policy_sources, policy_sources)["heavy_needed"] is True
    result = _classify(["ordinary.py"], policy_sources, policy_sources)
    assert result["heavy_needed"] is False, result["reason"]


@pytest.mark.parametrize("bad_copy", ["base", "pr"])
@pytest.mark.parametrize(
    "defect",
    ["missing-wrapper", "missing-helper", "missing-manifest", "invalid-manifest", "bad-output", "execution-error"],
)
def test_invalid_policy_copies_fail_closed(policy_sources: dict[str, str], bad_copy: str, defect: str) -> None:
    invalid = dict(policy_sources)
    if defect.startswith("missing-"):
        invalid.pop(POLICY_FILES[{"missing-wrapper": 0, "missing-helper": 1, "missing-manifest": 2}[defect]])
    elif defect == "invalid-manifest":
        invalid[POLICY_FILES[2]] = "not a rule\n"
    elif defect == "bad-output":
        invalid[POLICY_FILES[0]] = "print('soundness_path=false\\nsoundness_path=true')\n"
    else:
        invalid[POLICY_FILES[0]] = "raise RuntimeError('broken policy')\n"
    result = _classify(
        ["ordinary.py"],
        invalid if bad_copy == "base" else policy_sources,
        invalid if bad_copy == "pr" else policy_sources,
    )
    assert result["heavy_needed"] is True
    assert "failed closed" in result["reason"]


def test_standalone_legacy_predicate_still_runs() -> None:
    legacy = {
        POLICY_FILES[
            0
        ]: "import sys\nprint('soundness_path=' + str('protected.py' in sys.stdin.read().splitlines()).lower())\n"
    }
    assert _classify(["protected.py"], legacy, legacy)["heavy_needed"] is True
    result = _classify(["ordinary.py"], legacy, legacy)
    assert result["heavy_needed"] is False, result["reason"]


def test_unreadable_base_ref_fails_closed() -> None:
    result = heavy.heavy_needed(_decision(["ordinary.py"]), "pull_request", "refs/heads/not-present", REPO_ROOT)
    assert result["heavy_needed"] is True
    assert "failed closed" in result["reason"]


@pytest.mark.parametrize("raw", ["null", "[]", "not json"])
def test_invalid_cli_decisions_publish_the_safe_direction(tmp_path: Path, raw: str) -> None:
    decision = tmp_path / "decision.json"
    decision.write_text(raw, encoding="utf-8")
    output = tmp_path / "github-output"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/heavy_tier_needed.py"),
            "--decision-in",
            str(decision),
            "--github-output",
            str(output),
        ],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text().strip() == "heavy-needed=true"


def test_event_and_packaging_carve_outs_preserve_the_full_tier() -> None:
    assert heavy.heavy_needed(_decision([]), "merge_group", "absent", REPO_ROOT)["heavy_needed"] is True
    decision = {**_decision([]), "packaging_needed": True}
    assert heavy.heavy_needed(decision, "pull_request", "absent", REPO_ROOT)["heavy_needed"] is True
    assert heavy.heavy_needed({"needs_code_ci": False}, "pull_request", "absent", REPO_ROOT)["heavy_needed"] is False
