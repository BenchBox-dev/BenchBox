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

# Non-deploy peer workflows that are always present in the tree.
PEER_WORKFLOWS = ["release.yml", "lint.yml"]
INTENDED = "publication-deploy.yml"
LEGACY = "docs.yml"


def _wf_yaml(jobs: dict, name: str = "Test Workflow") -> str:
    return yaml.dump({"name": name, "jobs": jobs}, default_flow_style=False)


def _isolated_deploy_workflow() -> str:
    """publication-deploy.yml shape: separate build job feeds a separate deploy job."""
    return _wf_yaml(
        {
            "build": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"run": "uv run python scripts/assemble_public_site.py --site-dir site"},
                    {"run": "npm run build"},
                    {"uses": "actions/upload-pages-artifact@v3", "with": {"path": "site"}},
                ],
            },
            "deploy": {
                "needs": "build",
                "runs-on": "ubuntu-latest",
                "steps": [{"uses": "actions/deploy-pages@v4"}],
            },
        }
    )


def _legacy_two_job_deploy_workflow() -> str:
    """Realistic docs.yml: a build job AND a separate release-only deploy job.

    This is the exact shape the old detector whitelisted as 'correct' — it is
    a *second* deploy source and must fail isolation.
    """
    return _wf_yaml(
        {
            "build": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"run": "cd docs && uv run sphinx-build -b html . _build/html"},
                    {"run": "uv run -- python scripts/assemble_public_site.py --site-dir site"},
                    {"uses": "actions/upload-pages-artifact@v3", "with": {"path": "site"}},
                ],
            },
            "deploy": {
                "if": "github.event_name == 'push' && github.ref == 'refs/heads/release'",
                "needs": "build",
                "runs-on": "ubuntu-latest",
                "steps": [{"uses": "actions/deploy-pages@v4"}],
            },
        }
    )


def _coupled_workflow() -> str:
    """A single job that both builds and deploys."""
    return _wf_yaml(
        {
            "build-and-deploy": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"run": "uv run python scripts/assemble_public_site.py"},
                    {"uses": "actions/deploy-pages@v4"},
                ],
            }
        }
    )


def _sha_pinned_deploy_workflow() -> str:
    return _wf_yaml(
        {
            "deploy": {
                "runs-on": "ubuntu-latest",
                "steps": [{"uses": "actions/deploy-pages@" + "a" * 40}],
            }
        }
    )


def _reusable_call_workflow() -> str:
    return _wf_yaml({"call": {"uses": "./.github/workflows/some-reusable.yml"}})


def _ls_tree(workflow_files: list[str]) -> subprocess.CompletedProcess[str]:
    stdout = "\n".join(f".github/workflows/{n}" for n in workflow_files)
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _show(content: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=content, stderr="")


def _git_effects(wf_contents: dict[str, str]) -> list:
    """One ls-tree result, then one `git show` per workflow file (sorted, as the
    verifier reads them)."""
    effects: list = [_ls_tree(list(wf_contents))]
    for name in sorted(wf_contents):
        effects.append(_show(wf_contents[name]))
    return effects


def _run_main(argv: list[str], git_side_effects: list) -> int:
    with mock.patch.object(verify_release_isolation, "_run_git", side_effect=git_side_effects):
        return verify_release_isolation.main(argv)


def _empty_peers() -> dict[str, str]:
    return {name: _wf_yaml({"job": {"runs-on": "ubuntu-latest", "steps": []}}) for name in PEER_WORKFLOWS}


class TestSingleDeploySourceProven:
    def test_single_intended_source_is_proven(self, capsys):
        contents = {**_empty_peers(), INTENDED: _isolated_deploy_workflow()}
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(contents))
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["isolation_proven"] is True
        assert payload["deploy_source_count"] == 1
        assert payload["deploy_sources"][0]["workflow"] == INTENDED
        assert payload["intended_deploy_workflow_present"] is True
        assert payload["legacy_deploy_workflow_deploys"] is False

    def test_text_output_ok(self, capsys):
        contents = {**_empty_peers(), INTENDED: _isolated_deploy_workflow()}
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal"], _git_effects(contents))
        assert exit_code == 0
        assert "[OK] Release isolation proven" in capsys.readouterr().out


class TestSecondDeploySourceFails:
    def test_two_deploy_sources_fail(self, capsys):
        contents = {
            **_empty_peers(),
            INTENDED: _isolated_deploy_workflow(),
            LEGACY: _legacy_two_job_deploy_workflow(),
        }
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(contents))
        assert exit_code != 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["isolation_proven"] is False
        assert payload["deploy_source_count"] == 2
        assert payload["legacy_deploy_workflow_deploys"] is True
        assert any("2 Pages deploy sources" in e for e in payload["errors"])
        assert any("docs.yml" in e and "still contains a Pages deploy" in e for e in payload["errors"])

    def test_legacy_two_job_shape_is_not_whitelisted(self, capsys):
        """The old detector treated a separate build-job/deploy-job docs.yml as
        'the correct pattern'. It is a second deploy source and must fail."""
        contents = {**_empty_peers(), LEGACY: _legacy_two_job_deploy_workflow()}
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(contents))
        assert exit_code != 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["deploy_sources"][0]["workflow"] == LEGACY
        assert payload["deploy_sources"][0]["jobs"] == ["deploy"]


class TestHiddenCoupling:
    def test_single_job_build_and_deploy_detected(self, capsys):
        contents = {**_empty_peers(), "legacy-deploy.yml": _coupled_workflow()}
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(contents))
        assert exit_code != 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["hidden_couplings"]) == 1
        assert payload["hidden_couplings"][0]["workflow"] == "legacy-deploy.yml"


class TestFailOpenDeployDetection:
    def test_sha_pinned_deploy_pages_is_detected(self, capsys):
        contents = {**_empty_peers(), INTENDED: _sha_pinned_deploy_workflow()}
        # Only source + intended present, but this fixture has no build job, so
        # it still counts as the single deploy source and passes.
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(contents))
        payload = json.loads(capsys.readouterr().out)
        assert payload["deploy_source_count"] == 1
        assert exit_code == 0

    def test_second_source_with_sha_pin_fails(self, capsys):
        contents = {
            **_empty_peers(),
            INTENDED: _isolated_deploy_workflow(),
            "extra-deploy.yml": _sha_pinned_deploy_workflow(),
        }
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(contents))
        assert exit_code != 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["deploy_source_count"] == 2

    def test_raw_gh_pages_push_is_detected(self, capsys):
        wf = _wf_yaml({"publish": {"runs-on": "ubuntu-latest", "steps": [{"run": "git push origin HEAD:gh-pages"}]}})
        contents = {**_empty_peers(), INTENDED: _isolated_deploy_workflow(), "raw.yml": wf}
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(contents))
        assert exit_code != 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["deploy_source_count"] == 2


class TestReusableWorkflowUnanalyzable:
    def test_reusable_call_job_flagged(self, capsys):
        contents = {**_empty_peers(), INTENDED: _isolated_deploy_workflow(), "call.yml": _reusable_call_workflow()}
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(contents))
        assert exit_code != 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["unanalyzable_jobs"]) == 1
        assert payload["unanalyzable_jobs"][0]["workflow"] == "call.yml"


class TestProdModeRejected:
    def test_prod_mode_exit_two(self):
        assert _run_main(["--ref", REF, "--mode", "prod"], []) == 2

    def test_prod_mode_json_exit_two(self, capsys):
        assert _run_main(["--ref", REF, "--mode", "prod", "--json"], []) == 2
        payload = json.loads(capsys.readouterr().out)
        assert any("rejected" in e.lower() for e in payload["errors"])


class TestJsonSchemaShape:
    def test_json_has_required_fields(self, capsys):
        contents = {**_empty_peers(), INTENDED: _isolated_deploy_workflow()}
        _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(contents))
        payload = json.loads(capsys.readouterr().out)
        assert set(payload.keys()) == {
            "mode",
            "ref",
            "deploy_sources",
            "deploy_source_count",
            "intended_deploy_workflow_present",
            "legacy_deploy_workflow_deploys",
            "hidden_couplings",
            "unanalyzable_jobs",
            "isolation_proven",
            "errors",
        }


class TestGitFetchFailure:
    def test_git_ls_tree_failure_is_operational_error(self):
        effects = [subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal: bad object")]
        assert _run_main(["--ref", REF, "--mode", "rehearsal"], effects) != 0


class TestNoDeploySource:
    def test_no_deploy_source_detected(self, capsys):
        exit_code = _run_main(["--ref", REF, "--mode", "rehearsal", "--json"], _git_effects(_empty_peers()))
        assert exit_code != 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["deploy_source_count"] == 0
        assert any("no pages deploy source" in e.lower() for e in payload["errors"])


class TestLiveTreeIntegration:
    """Run the verifier against the real .github/workflows tree at HEAD."""

    def test_current_tree_is_not_isolated_while_docs_yml_deploys(self):
        docs_yml = REPO_ROOT / ".github" / "workflows" / "docs.yml"
        if not docs_yml.exists() or "deploy-pages" not in docs_yml.read_text():
            pytest.skip("docs.yml no longer carries a Pages deploy step")
        report = verify_release_isolation.verify_release_isolation(ref="HEAD", mode="rehearsal")
        assert report.isolation_proven is False
        assert report.legacy_deploy_workflow_deploys is True
        assert any("docs.yml" in e for e in report.errors)
