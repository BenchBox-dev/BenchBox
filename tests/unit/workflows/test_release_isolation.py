"""Contract tests for the release isolation rehearsal verifier."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "publication" / "verify_release_isolation.py"

spec = importlib.util.spec_from_file_location("verify_release_isolation", SCRIPT_PATH)
verify_release_isolation = importlib.util.module_from_spec(spec)
sys.modules["verify_release_isolation"] = verify_release_isolation
assert spec.loader is not None
spec.loader.exec_module(verify_release_isolation)

REF = "origin/release"
ISOLATED_WORKFLOWS = [
    "publication-deploy.yml",
    "docs.yml",
    "release.yml",
]
COUPLED_WORKFLOW_NAME = "legacy-deploy.yml"


def _make_workflow_yaml(
    jobs: dict | None = None,
    permissions: dict | None = None,
    trigger_branches: list[str] | None = None,
) -> str:
    wf: dict = {"name": "Test Workflow", "jobs": jobs or {}}
    if permissions:
        wf["permissions"] = permissions
    if trigger_branches:
        wf["on"] = {"push": {"branches": trigger_branches}}
    return yaml.dump(wf, default_flow_style=False)


def _isolated_deploy_workflow() -> str:
    return _make_workflow_yaml(
        jobs={
            "build": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"run": "uv run python scripts/assemble_public_site.py"},
                    {"run": "npm run build"},
                    {"uses": "actions/upload-artifact@v4", "with": {"name": "prose_site"}},
                ],
            },
            "deploy": {
                "needs": "build",
                "runs-on": "ubuntu-latest",
                "steps": [{"uses": "actions/deploy-pages@v4"}],
            },
        }
    )


def _coupled_workflow() -> str:
    return _make_workflow_yaml(
        jobs={
            "build-and-deploy": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"run": "uv run python scripts/assemble_public_site.py"},
                    {"uses": "actions/upload-artifact@v4", "with": {"name": "api_docs"}},
                    {"uses": "actions/deploy-pages@v4"},
                ],
            },
        }
    )


def _stub_git_ls_tree(workflow_files: list[str]):
    stdout = "\n".join(f".github/workflows/{name}" for name in workflow_files)
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _stub_git_show(content: str):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=content, stderr="")


def _stub_git_show_missing(path: str):
    return subprocess.CompletedProcess(
        args=[], returncode=128, stdout="", stderr=f"fatal: path '{path}' does not exist"
    )


def _make_git_effects(workflow_files: list[str], wf_contents: dict[str, str] | None = None):
    """Build mock _run_git side effects: one ls-tree result, then one show per
    workflow file that will actually be read (workflows skipped by the verifier
    are excluded so list-based consumption stays aligned)."""
    effects = [_stub_git_ls_tree(workflow_files)]
    for wf_name in workflow_files:
        if wf_name == verify_release_isolation.INTENDED_DEPLOY_WORKFLOW:
            continue
        content = (wf_contents or {}).get(wf_name, _make_workflow_yaml(jobs={}))
        effects.append(_stub_git_show(content))
    return effects


def _run_main(argv: list[str], git_side_effects: list) -> int:
    with mock.patch.object(verify_release_isolation, "_run_git", side_effect=git_side_effects):
        return verify_release_isolation.main(argv)


class TestRehearsalModeReadOnly:
    def test_rehearsal_never_deploys(self, capsys):
        git_effects = _make_git_effects(
            ISOLATED_WORKFLOWS,
            {"publication-deploy.yml": _isolated_deploy_workflow()},
        )
        exit_code = _run_main(
            ["--ref", REF, "--mode", "rehearsal", "--json"],
            git_side_effects=git_effects,
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["mode"] == "rehearsal"
        assert payload["isolation_proven"] is True

    def test_rehearsal_mode_explicit(self, capsys):
        git_effects = _make_git_effects(
            ISOLATED_WORKFLOWS,
            {"publication-deploy.yml": _isolated_deploy_workflow()},
        )
        exit_code = _run_main(
            ["--ref", REF, "--mode", "rehearsal"],
            git_side_effects=git_effects,
        )
        assert exit_code == 0
        assert "[OK] Release isolation proven" in capsys.readouterr().out


class TestHiddenCouplingDetection:
    def test_hidden_coupling_detected_exit_nonzero(self, capsys):
        coupled_wfs = ISOLATED_WORKFLOWS + [COUPLED_WORKFLOW_NAME]
        git_effects = _make_git_effects(
            coupled_wfs,
            {
                "publication-deploy.yml": _isolated_deploy_workflow(),
                COUPLED_WORKFLOW_NAME: _coupled_workflow(),
            },
        )
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal"], git_side_effects=git_effects)
        assert exit_code != 0
        captured = capsys.readouterr()
        assert "HIDDEN COUPLING" in captured.err or "FAIL" in captured.out

    def test_hidden_coupling_detected_json(self, capsys):
        coupled_wfs = ISOLATED_WORKFLOWS + [COUPLED_WORKFLOW_NAME]
        git_effects = _make_git_effects(
            coupled_wfs,
            {
                "publication-deploy.yml": _isolated_deploy_workflow(),
                COUPLED_WORKFLOW_NAME: _coupled_workflow(),
            },
        )
        exit_code = _run_main(
            ["--ref", REF, "--mode", "rehearsal", "--json"],
            git_side_effects=git_effects,
        )
        assert exit_code != 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["hidden_couplings"]) == 1
        assert payload["hidden_couplings"][0]["workflow"] == COUPLED_WORKFLOW_NAME


class TestIsolatedRelease:
    def test_isolated_deploy_source_present(self, capsys):
        git_effects = _make_git_effects(
            ISOLATED_WORKFLOWS,
            {"publication-deploy.yml": _isolated_deploy_workflow()},
        )
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], git_side_effects=git_effects)
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["deploy_source_present"] is True
        assert payload["deploy_source_workflow"] in ("publication-deploy.yml", "docs.yml")


class TestProdModeRejected:
    def test_prod_mode_exit_two(self):
        exit_code = _run_main(["--ref", REF, "--mode", "prod"], git_side_effects=[])
        assert exit_code == 2

    def test_prod_mode_json_exit_two(self, capsys):
        exit_code = _run_main(["--ref", REF, "--mode", "prod", "--json"], git_side_effects=[])
        assert exit_code == 2
        payload = json.loads(capsys.readouterr().out)
        assert any("rejected" in e.lower() for e in payload["errors"])


class TestJsonSchemaShape:
    def test_json_has_required_fields(self, capsys):
        git_effects = _make_git_effects(
            ISOLATED_WORKFLOWS,
            {"publication-deploy.yml": _isolated_deploy_workflow()},
        )
        _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], git_side_effects=git_effects)
        payload = json.loads(capsys.readouterr().out)
        assert set(payload.keys()) == {
            "mode",
            "ref",
            "deploy_source_present",
            "deploy_source_workflow",
            "hidden_couplings",
            "isolation_proven",
            "errors",
        }


class TestGitFetchFailure:
    def test_git_ls_tree_failure_is_operational_error(self, capsys):
        git_effects = [
            subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal: Not a valid object name")
        ]
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal"], git_side_effects=git_effects)
        assert exit_code != 0


class TestNoDeploySource:
    def test_no_deploy_source_detected(self, capsys):
        git_effects = _make_git_effects(["release.yml", "lint.yml"])
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], git_side_effects=git_effects)
        assert exit_code != 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["deploy_source_present"] is False
        assert any("deploy source" in e.lower() for e in payload["errors"])
