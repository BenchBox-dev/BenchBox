"""Tests for release infrastructure.

Validates release-related configurations, workflows, and files to ensure
proper project release setup.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import itertools
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).parent.parent.parent
CI_FAST_EXPRESSION = "fast and not (slow or stress or resource_heavy or live_integration)"
RELEASE_INTEGRATION_EXPRESSION = "integration and not (slow or stress or resource_heavy or live_integration)"
RELEASE_CANARY_NON_FAST_EXPRESSION = "(slow or resource_heavy) and not (stress or live_integration)"
RELEASE_PR_BRANCH_SKIP = (
    "(github.event_name != 'pull_request' || github.base_ref != 'main' || !startsWith(github.head_ref, 'v'))"
)
RELEASE_REQUIRED_CONTEXTS = ("validate-base", "release-required-result")


def _makefile_text() -> str:
    return (REPO_ROOT / "Makefile").read_text(encoding="utf-8")


def _make_target_recipe(target: str) -> str:
    lines = _makefile_text().splitlines()
    start = lines.index(f"{target}:") + 1
    recipe_lines: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith("\t"):
            break
        recipe_lines.append(line)
    return "\n".join(recipe_lines)


def _workflow_job_run_text(workflow_name: str, job_name: str) -> str:
    workflow_path = REPO_ROOT / ".github" / "workflows" / workflow_name
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    return "\n".join(str(step.get("run", "")) for step in workflow["jobs"][job_name]["steps"])


def _workflow(workflow_name: str) -> dict:
    workflow_path = REPO_ROOT / ".github" / "workflows" / workflow_name
    return yaml.safe_load(workflow_path.read_text(encoding="utf-8"))


if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]


class TestReleaseInfrastructure:
    """Test release infrastructure configuration and files."""

    def test_changelog_exists(self):
        """Test that CHANGELOG.md exists."""
        changelog_path = REPO_ROOT / "CHANGELOG.md"
        assert changelog_path.exists(), "CHANGELOG.md file must exist"

    def test_pyproject_toml_release_config(self):
        """Test that pyproject.toml has correct release configuration."""
        pyproject_path = REPO_ROOT / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        # Check project metadata
        project = config["project"]
        assert "name" in project
        assert project["name"] == "benchbox"
        assert "version" in project
        assert "description" in project
        assert "readme" in project
        assert "license" in project
        assert "authors" in project

        # Check URLs point to correct repository
        urls = project["urls"]
        expected_repo = "https://github.com/joeharris76/benchbox"
        assert urls["Homepage"] == expected_repo
        assert urls["Repository"] == f"{expected_repo}.git"
        assert urls["Bug Tracker"] == f"{expected_repo}/issues"
        assert urls["Changelog"] == f"{expected_repo}/blob/main/CHANGELOG.md"

        # No incorrect repository references
        for url in urls.values():
            assert "anthropics/claude-code" not in url
            assert "anthropic" not in url

    def test_import_benchbox_succeeds_without_pandas(self):
        """`import benchbox` must work on a clean core install even when pandas is absent.

        This is the real contract behind the v0.3.0 clean-install failure: the
        base import surface must not require an optional engine/DataFrame
        dependency. Run in a fresh interpreter with pandas made unimportable.
        """
        code = (
            "import sys; sys.modules['pandas'] = None; "  # any `import pandas` now raises ImportError
            "import benchbox; "
            "print(benchbox.__version__)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"import benchbox failed without pandas:\n{result.stderr}"

    def test_import_benchbox_does_not_pull_pandas(self):
        """Importing benchbox must not eagerly import pandas onto the base surface.

        Guards against a future top-level `import pandas` silently re-entering the
        import path and forcing pandas back into the core dependency set.
        """
        code = "import benchbox, sys; assert 'pandas' not in sys.modules, sorted(m for m in sys.modules if m == 'pandas' or m.startswith('pandas.'))"
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"import benchbox eagerly imported pandas:\n{result.stdout}{result.stderr}"

    def test_github_issue_url_fix(self):
        """Test that exceptions.py has correct GitHub issue URL."""
        exceptions_path = REPO_ROOT / "benchbox" / "cli" / "exceptions.py"

        with open(exceptions_path, encoding="utf-8") as f:
            content = f.read()

        # Should have correct repository URL
        assert "https://github.com/joeharris76/benchbox/issues" in content
        # Should not have incorrect URLs
        assert "anthropics/claude-code" not in content

    def test_github_workflows_exist(self):
        """Test that GitHub workflows exist and are properly configured."""
        workflows_dir = REPO_ROOT / ".github" / "workflows"
        assert workflows_dir.exists(), "GitHub workflows directory must exist"

        # Required workflows
        required_workflows = ["test.yml", "lint.yml", "release.yml"]
        for workflow in required_workflows:
            workflow_path = workflows_dir / workflow
            assert workflow_path.exists(), f"{workflow} workflow must exist"

    def test_test_workflow_configuration(self):
        """Test that test workflow is properly configured."""
        test_workflow_path = REPO_ROOT / ".github" / "workflows" / "test.yml"

        with open(test_workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        # Check basic structure
        assert "name" in workflow
        assert True in workflow  # YAML parses "on" as boolean True
        assert "jobs" in workflow

        # Check trigger events (YAML parses 'on' as True)
        on_events = workflow[True]  # YAML parses "on" as boolean True
        assert "push" in on_events
        assert "pull_request" in on_events

        # Check jobs
        jobs = workflow["jobs"]
        assert "test" in jobs

        test_job = jobs["test"]
        assert test_job["name"] == "test (ubuntu-latest, 3.12)"
        assert test_job["runs-on"] == "ubuntu-latest"
        assert "strategy" not in test_job, "Required main test job is intentionally a single 3.12 lane"

        steps = test_job["steps"]
        uv_step_found = any("uv" in str(step).lower() for step in steps)
        assert uv_step_found, "Workflow should use uv for dependency management"

        workflow_text = test_workflow_path.read_text(encoding="utf-8")
        assert f'-m "{CI_FAST_EXPRESSION}"' in workflow_text
        assert "--cov-fail-under=70" in workflow_text

    def test_required_fast_marker_expression_is_consistent(self):
        """Pin required PR fast-test marker selection across local and CI surfaces."""
        makefile_content = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        develop_pr_run_text = _workflow_job_run_text("pr.yml", "code-test")
        main_pr_run_text = _workflow_job_run_text("test.yml", "test")

        expected_marker_flag = f'-m "{CI_FAST_EXPRESSION}"'
        assert expected_marker_flag in makefile_content
        assert "-m fast -q" not in makefile_content
        assert expected_marker_flag in develop_pr_run_text
        assert expected_marker_flag in main_pr_run_text
        assert "--cov-fail-under=70" in develop_pr_run_text
        assert "--cov-fail-under=70" in main_pr_run_text
        assert "coverage remains CI-only" in makefile_content

    def test_release_workflow_configuration(self):
        """Test that release workflow is properly configured."""
        release_workflow_path = REPO_ROOT / ".github" / "workflows" / "release.yml"

        with open(release_workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        # Check basic structure
        assert "name" in workflow
        assert workflow["name"] == "Release"
        assert True in workflow  # YAML parses "on" as boolean True
        assert "jobs" in workflow

        # Check trigger events (YAML parses 'on' as True)
        on_events = workflow[True]  # YAML parses "on" as boolean True
        assert "push" in on_events
        assert "tags" in on_events["push"]
        assert "v*" in on_events["push"]["tags"]
        assert "workflow_dispatch" in on_events

        # Check jobs exist
        jobs = workflow["jobs"]
        required_jobs = ["dependency-bounds", "build", "publish", "github-release", "test-installation"]
        for job in required_jobs:
            assert job in jobs, f"Release workflow must have {job} job"
        assert "check-ci-passed" not in jobs

        release_workflow_text = release_workflow_path.read_text(encoding="utf-8")
        forbidden_pytest_invocations = ["python -m pytest", "uv run pytest", "uv run -- pytest"]
        for invocation in forbidden_pytest_invocations:
            assert invocation not in release_workflow_text, "release.yml publishes from tags and does not run pytest"

        # Check that publish job uses trusted publishing
        publish_job = jobs["publish"]
        assert "permissions" in publish_job
        assert "id-token" in publish_job["permissions"]
        assert publish_job["permissions"]["id-token"] == "write"

    def test_release_smoke_test_pins_installed_version(self):
        """#1072 review: the post-publish smoke test must install the exact
        version this workflow run just built, not an unqualified `benchbox`
        - PyPI/Test PyPI propagation lag or a pre-existing Test PyPI version
        could otherwise mask a broken current wheel."""
        jobs = _workflow("release.yml")["jobs"]
        test_installation_job = jobs["test-installation"]

        needs = test_installation_job["needs"]
        needs = [needs] if isinstance(needs, str) else needs
        assert "build" in needs, "test-installation must depend on build to reach needs.build.outputs.version"

        release_workflow_text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        assert "pip install benchbox" not in release_workflow_text, "smoke test must not install an unpinned benchbox"
        assert release_workflow_text.count("needs.build.outputs.version") >= 3, (
            "the build/publish version pin, plus both PyPI and Test PyPI install steps, must reference it"
        )

    def test_release_required_result_contract(self):
        """Test the main-PR release-required umbrella check shape."""
        jobs = _workflow("test.yml")["jobs"]

        assert jobs["integration"]["if"] == (
            "github.event_name == 'push' || (github.event_name == 'pull_request' && github.base_ref == 'main')"
        )
        integration_run_text = _workflow_job_run_text("test.yml", "integration")
        assert f'tests/integration -m "{RELEASE_INTEGRATION_EXPRESSION}"' in integration_run_text

        test_package_run_text = _workflow_job_run_text("test.yml", "test-package")
        assert "wheel_count=$(find dist -maxdepth 1 -name '*.whl'" in test_package_run_text
        assert 'uv run --isolated --no-project --with "$wheel"' in test_package_run_text
        assert "benchbox --help" in test_package_run_text

        for job_name in ["compat-test", "integration-smoke"]:
            condition = jobs[job_name]["if"]
            assert "github.event.pull_request.title" not in condition
            assert RELEASE_PR_BRANCH_SKIP in condition

        make_test_package = _make_target_recipe("test-package")
        assert "test-venv" not in make_test_package
        assert "Expected exactly one wheel" in make_test_package
        assert 'uv run --isolated --no-project --with "$$wheel"' in make_test_package

        release_readiness = jobs["release-readiness"]
        assert release_readiness["if"] == "${{ github.event_name == 'pull_request' && github.base_ref == 'main' }}"
        readiness_run_text = _workflow_job_run_text("test.yml", "release-readiness")
        assert "scripts/check_dependency_bounds.py" in readiness_run_text
        assert "--fail-on=cap-reached" in readiness_run_text
        assert "Check release branch curation" in str(jobs["release-readiness"]["steps"])
        assert "Release branch still contains curated path" in readiness_run_text
        assert "_project" in readiness_run_text
        assert ".github/workflows/validate-submission.yml" in readiness_run_text

        result_job = jobs["release-required-result"]
        assert result_job["name"] == "release-required-result"
        assert set(result_job["needs"]) == {
            "test",
            "integration",
            "correctness-gate",
            "test-package",
            "release-readiness",
        }
        assert result_job["if"] == "${{ always() && github.event_name == 'pull_request' && github.base_ref == 'main' }}"
        aggregate_run_text = _workflow_job_run_text("test.yml", "release-required-result")
        for expected in [
            "test (ubuntu-latest, 3.12)",
            "integration",
            "correctness-gate",
            "test-package",
            "release-readiness",
            "Release-required checks passed.",
        ]:
            assert expected in aggregate_run_text

    def test_release_docs_name_required_contexts(self):
        """Release docs must name the same stable required contexts."""
        docs_paths = [
            REPO_ROOT / "docs" / "operations" / "release-guide.md",
            REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md",
            REPO_ROOT / ".github" / "RELEASE_PR_TEMPLATE.md",
        ]

        for path in docs_paths:
            content = path.read_text(encoding="utf-8")
            for context in RELEASE_REQUIRED_CONTEXTS:
                assert context in content

    def test_release_canary_workflow_contract(self):
        """Release canary must produce scheduled non-fast and ruleset drift evidence."""
        workflow = _workflow("release-canary.yml")
        on_events = workflow[True]
        assert "workflow_dispatch" in on_events
        assert on_events["schedule"] == [{"cron": "0 8 * * *"}]
        assert workflow["permissions"]["actions"] == "read"
        assert workflow["permissions"]["contents"] == "read"
        assert workflow["env"]["RELEASE_CANARY_REF"] == "develop"

        jobs = workflow["jobs"]
        assert set(jobs) == {
            "credential-free-non-fast",
            "ruleset-drift",
            "pypi-latest-installability",
            "release-canary-result",
        }
        assert jobs["credential-free-non-fast"]["steps"][0]["with"]["ref"] == "${{ env.RELEASE_CANARY_REF }}"
        assert jobs["ruleset-drift"]["steps"][0]["with"]["ref"] == "${{ env.RELEASE_CANARY_REF }}"

        # pypi-latest-installability must not gate on (or be gated by) the
        # other canary jobs, and must not check out the repo (it installs
        # the published PyPI artifact, not local source).
        pypi_latest_job = jobs["pypi-latest-installability"]
        assert "needs" not in pypi_latest_job
        assert not any(step.get("uses", "").startswith("actions/checkout") for step in pypi_latest_job["steps"])
        pypi_latest_text = _workflow_job_run_text("release-canary.yml", "pypi-latest-installability")
        assert "uv run --isolated --no-project --with benchbox --" in pypi_latest_text
        assert "importlib.util.find_spec('pandas') is None" in pypi_latest_text
        assert "mktemp -d" in pypi_latest_text

        non_fast_text = _workflow_job_run_text("release-canary.yml", "credential-free-non-fast")
        assert RELEASE_CANARY_NON_FAST_EXPRESSION in non_fast_text
        assert "--collect-only" in non_fast_text
        assert "release-canary-artifacts/non-fast-summary.json" in non_fast_text
        assert '"checked_ref": "develop"' in non_fast_text
        assert '"commit_sha": os.environ["CHECKED_SHA"]' in non_fast_text
        assert "raw" not in non_fast_text.lower()
        # Exit code must propagate via rc= variable, not be swallowed by set+e/exit 0.
        assert "set +e" not in non_fast_text
        assert "exit 0" not in non_fast_text

        ruleset_text = _workflow_job_run_text("release-canary.yml", "ruleset-drift")
        assert "scripts/ruleset_drift_check.py" in ruleset_text
        assert "RULESET_DRIFT_TOKEN" in ruleset_text
        assert "--require-bypass-actor-visibility" in ruleset_text
        assert "release-canary-artifacts/ruleset-drift.json" in ruleset_text
        assert "set +e" not in ruleset_text
        assert "exit 0" not in ruleset_text

        result_job = jobs["release-canary-result"]
        assert result_job["name"] == "release-canary-result"
        assert set(result_job["needs"]) == {
            "credential-free-non-fast",
            "ruleset-drift",
            "pypi-latest-installability",
        }
        result_text = _workflow_job_run_text("release-canary.yml", "release-canary-result")
        assert '"checked_ref": "develop"' in result_text
        assert '"commit_sha": "${CHECKED_SHA}"' in result_text
        assert '"freshness_contract_hours": 48' in result_text
        assert "Release canary passed." in result_text

    def test_canary_collect_count_regex_matches_pytest_deselect_format(self):
        """The canary collect-step grep regex must match the actual pytest --collect-only output format."""
        collect_text = _workflow_job_run_text("release-canary.yml", "credential-free-non-fast")
        assert "'^[0-9]+/[0-9]+ tests collected'" in collect_text

        # Verify the regex semantics using Python re (same logic as the grep ERE pattern).
        pattern = re.compile(r"^\d+/\d+ tests collected")
        assert pattern.match("92/24795 tests collected (24703 deselected) in 16.98s")
        assert pattern.match("1/100 tests collected")
        assert not pattern.match("24795 tests collected in 16.98s")
        assert not pattern.match("0 tests collected")

    def test_validate_main_pr_checks_release_canary_freshness(self):
        """The required validate-base context must include release canary freshness."""
        workflow = _workflow("validate-main-pr.yml")
        assert workflow["permissions"]["actions"] == "read"
        assert workflow["permissions"]["contents"] == "read"

        job = workflow["jobs"]["validate-base"]
        steps = job["steps"]
        checkout_step = next(step for step in steps if step.get("uses") == "actions/checkout@v4")
        assert checkout_step["name"] == "Checkout trusted release policy"
        assert checkout_step["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
        assert checkout_step["with"]["fetch-depth"] == 0
        assert "${{ github.event.pull_request.head.sha }}" not in str(checkout_step)

        run_text = _workflow_job_run_text("validate-main-pr.yml", "validate-base")
        assert "git fetch --prune origin develop" in run_text
        assert "refs/pull/${{ github.event.pull_request.number }}/head" in run_text
        assert "scripts/release_readiness_check.py" in run_text
        assert '--head-sha "${{ github.event.pull_request.head.sha }}"' in run_text
        assert "--bootstrap-on-missing-workflow" in run_text
        assert "bootstrap_required=true" in run_text
        canary_run_text = _workflow_job_run_text("release-canary.yml", "credential-free-non-fast")
        assert run_text.count(RELEASE_CANARY_NON_FAST_EXPRESSION) == 2
        assert RELEASE_CANARY_NON_FAST_EXPRESSION in canary_run_text
        assert " or e2e" not in run_text
        assert "TestFractionalScaleFactors" not in run_text
        assert "scripts/ruleset_drift_check.py" in run_text
        assert "--require-bypass-actor-visibility" in run_text

        readiness_step = next(step for step in steps if step["name"] == "Check release canary freshness")
        assert readiness_step["env"]["RELEASE_CANARY_WORKFLOW"] == "release-canary.yml"
        assert readiness_step["env"]["RELEASE_CANARY_BRANCH"] == "main"
        assert readiness_step["env"]["RELEASE_CANARY_CHECKED_REF"] == "develop"
        assert readiness_step["env"]["RELEASE_CANARY_MAX_AGE_HOURS"] == "48"
        assert "RELEASE_READINESS_OVERRIDE_SHA" in readiness_step["env"]

    def test_validate_main_pr_restores_ruleset_helper_before_drift_check(self):
        """scripts/ruleset_drift_check.py imports its enforcement helper from
        _project/scripts, which release-cut curation strips from both the
        release head and (once a release has been cut) the trusted main
        base. The restore-from-develop step must run, and must run before
        the ruleset drift check, or bootstrap evidence would ModuleNotFoundError
        on every real release PR.

        The helper itself imports auto_merge_soundness_paths from the same
        curated-out directory, so restoring only the helper still fails
        (v0.3.1 release PR #1072). Both modules must be restored.
        """
        job = _workflow("validate-main-pr.yml")["jobs"]["validate-base"]
        step_names = [step.get("name") for step in job["steps"]]
        restore_index = step_names.index("Restore ruleset review enforcement helper for bootstrap")
        drift_check_index = step_names.index("Bootstrap ruleset drift evidence")
        assert restore_index < drift_check_index

        restore_step = job["steps"][restore_index]
        assert restore_step["if"] == "steps.release-readiness.outputs.bootstrap_required == 'true'"
        assert "_project/scripts/ruleset_review_enforcement.py" in restore_step["run"]
        assert "_project/scripts/auto_merge_soundness_paths.py" in restore_step["run"]
        assert "origin/develop" in restore_step["run"]

    def test_release_docs_name_canary_and_ruleset_drift(self):
        """Release docs must name freshness, ruleset drift, and the override contract."""
        docs_paths = [
            REPO_ROOT / "docs" / "operations" / "release-guide.md",
            REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md",
            REPO_ROOT / ".github" / "RELEASE_PR_TEMPLATE.md",
        ]

        for path in docs_paths:
            content = path.read_text(encoding="utf-8")
            assert "canary" in content
            assert "ruleset drift" in content
            assert "48" in content
            assert "RELEASE_READINESS_OVERRIDE_SHA" in content

    def test_release_finalize_checks_required_context_before_merge_and_tag(self):
        """release-finalize must hard-stop unless required release contexts are required and green."""
        makefile_content = _makefile_text()
        recipe = _make_target_recipe("release-finalize")

        assert "RELEASE_REQUIRED_CONTEXTS := validate-base release-required-result" in makefile_content
        assert 'gh pr checks "$$PR" --required --json name,bucket,state' in recipe
        assert 'select(.name == \\"$$context\\")' in recipe
        assert "for context in $(RELEASE_REQUIRED_CONTEXTS)" in recipe
        assert "--watch" not in recipe
        assert 'CHECK_RC" = "8"' in recipe
        assert 'CHECK_RC" != "0"' in recipe
        assert 'CHECK_RC" != "0" ] && [ "$$CHECK_RC" != "8"' not in recipe

        assert recipe.index("no open PR found for v$(VERSION)") < recipe.index("gh pr checks")
        assert recipe.index("gh pr checks") < recipe.index("gh pr merge --squash")
        assert recipe.index("gh pr merge --squash") < recipe.index("git fetch origin --tags")
        assert recipe.index("git tag v$(VERSION)") < recipe.index("git push origin v$(VERSION)")

    def test_release_finalize_blocks_pending_required_check_exit_code(self):
        """gh pr checks exit 8 means at least one required check is still pending."""
        recipe = _make_target_recipe("release-finalize")

        assert 'if [ "$$CHECK_RC" = "8" ]; then' in recipe
        assert "required PR checks are pending. Wait for GitHub Actions, then rerun" in recipe
        assert 'CHECK_RC" != "0" ] && [ "$$CHECK_RC" != "8"' not in recipe
        assert recipe.index('if [ "$$CHECK_RC" = "8" ]') < recipe.index('case "$$CHECK_BUCKET"')

    def test_release_finalize_failure_modes_are_explicit(self):
        """The one-shot release-finalize precondition must fail closed for drift and non-green states."""
        recipe = _make_target_recipe("release-finalize")

        for expected in [
            "missing)",
            "pending)",
            "fail|cancel|skipping)",
            "duplicate)",
            "unexpected $$context status",
        ]:
            assert expected in recipe

        assert "no open PR found for v$(VERSION)" in recipe
        assert "required release context '$$context' is missing" in recipe
        assert "Wait for GitHub Actions, then rerun" in recipe
        assert "Fix the release PR before finalizing" in recipe
        assert "Fix workflow/ruleset drift" in recipe
        assert "gh pr merge --squash" in recipe
        assert "|| true" not in recipe

    def test_release_finalize_docs_separate_premerge_and_postmerge_signals(self):
        """Release docs must not imply post-merge push checks are pre-publish blockers."""
        makefile_content = _makefile_text()
        release_guide = (REPO_ROOT / "docs" / "operations" / "release-guide.md").read_text(encoding="utf-8")
        release_template = (REPO_ROOT / ".github" / "RELEASE_PR_TEMPLATE.md").read_text(encoding="utf-8")

        assert "Wait for CI green" not in makefile_content
        assert "CI is not green" not in makefile_content
        assert "required release contexts: $(RELEASE_REQUIRED_CONTEXTS)" in makefile_content
        assert "Push-to-main jobs are post-merge signals" in makefile_content

        for content in [release_guide, release_template]:
            normalized = content.lower()
            for context in RELEASE_REQUIRED_CONTEXTS:
                assert context in content
            assert "post-merge" in normalized
            assert "pre-merge" in normalized
            assert "patch release or incident" in content

    def test_release_cut_generates_changelog_from_main_delta(self):
        """The release branch changelog boundary is the main patch delta, not tag ancestry."""
        recipe = _make_target_recipe("release-cut")
        release_guide = (REPO_ROOT / "docs" / "operations" / "release-guide.md").read_text(encoding="utf-8")
        release_template = (REPO_ROOT / ".github" / "RELEASE_PR_TEMPLATE.md").read_text(encoding="utf-8")

        assert "scripts/generate_changelog_entry.py --version $(VERSION) --since-ref origin/main" in recipe
        assert "`origin/main` patch delta" in release_template
        assert "git log origin/main..HEAD" in release_guide
        assert "origin/main" in release_guide
        assert "intentionally does not replay release commits onto" in release_guide

    def test_release_cut_gates_on_changelog_curation_not_on_editor(self):
        """`EDITOR=true` must not wave a raw commit dump into a release.

        The old gate refused to skip curation only when EDITOR was unset AND
        there was no TTY, so setting EDITOR to any no-op binary defeated it.
        The gate is now the drafted section's own text.
        """
        recipe = _make_target_recipe("release-cut")

        assert "scripts/generate_changelog_entry.py --check-curation --version $(VERSION)" in recipe
        assert "refusing to skip changelog curation" not in recipe
        gen_idx = recipe.index("--version $(VERSION) --since-ref origin/main")
        check_idx = recipe.index("--check-curation")
        rm_idx = recipe.index("git rm")
        assert gen_idx < check_idx < rm_idx, "curation check must gate between changelog draft and `git rm`"

    def test_release_cut_is_resumable_and_has_an_abort_target(self):
        """An interrupted cut must be resumable or discardable, not a manual cleanup.

        The v0.3.1 cut died at the changelog step twice, each time leaving the
        vX.Y.Z branch created, versions bumped and uv.lock rewritten with no
        commit.
        """
        recipe = _make_target_recipe("release-cut")
        assert "Resuming interrupted cut" in recipe
        assert "already carries its release commit" in recipe
        assert "git checkout -b v$(VERSION) develop" in recipe
        assert "git rev-parse --verify --quiet refs/heads/v$(VERSION)" in recipe

        assert "--first-parent" in recipe, (
            "the resume guard must walk first-parent: the `-s ours` alignment merge puts "
            "origin/main's release ledger (full of 'Release vX.Y.Z' subjects) on the second parent, "
            "and a plain `git log -1` misses a release commit sitting beneath that merge"
        )

        abort = _make_target_recipe("release-cut-abort")
        assert "git reset --hard HEAD" in abort
        assert "git checkout develop" in abort
        assert "git branch -D v$(VERSION)" in abort
        assert "git ls-remote --exit-code --heads origin" in abort, (
            "abort must refuse to discard a release branch that already exists on origin"
        )
        assert ".PHONY: release-cut release-cut-abort release-finalize" in _makefile_text()

    def test_release_cut_curation_survives_untracked_paths(self):
        """Curation `git rm` lines must use --ignore-unmatch and abort on real failures.

        Without --ignore-unmatch, one untracked pathspec aborts the entire
        `git rm`, and the old `-` prefix hid that — the v0.3.1 cut shipped an
        uncurated release branch because .codex/.gemini/todo.config.yaml were
        untracked at cut time.
        """
        recipe = _make_target_recipe("release-cut")
        rm_lines = [line.strip() for line in recipe.splitlines() if re.search(r"git rm (?:-rf|-f) ", line)]
        assert rm_lines, "expected git rm curation lines in release-cut"
        for line in rm_lines:
            assert "--ignore-unmatch" in line, f"curation line missing --ignore-unmatch: {line}"
            assert not line.startswith("-"), f"real git rm failures must abort the cut (drop `-` prefix): {line}"

    def test_release_cut_post_curation_guard_covers_every_curated_path(self):
        """The git ls-files guard must re-check every path the git rm lines curate."""
        recipe = _make_target_recipe("release-cut")
        rm_paths: set[str] = set()
        for line in recipe.splitlines():
            rm_match = re.search(r"git rm (?:-rf|-f) --ignore-unmatch (.+?)$", line.strip())
            if rm_match:
                rm_paths.update(rm_match.group(1).split())
        assert rm_paths, "expected git rm curation paths in release-cut"
        guard_match = re.search(r"git ls-files (.+?)\)", recipe)
        assert guard_match, "expected a `git ls-files <curated paths>` post-curation guard in release-cut"
        guard_paths = set(guard_match.group(1).split())
        assert rm_paths == guard_paths, (
            f"post-curation guard out of sync with git rm lines; "
            f"missing from guard: {sorted(rm_paths - guard_paths)}, "
            f"extra in guard: {sorted(guard_paths - rm_paths)}"
        )

    def test_release_cut_refreshes_and_stages_uv_lock(self):
        """release-cut must regenerate uv.lock after the version bump and stage it.

        The v0.3.1 cut aborted mid-commit because the tracked uv.lock was stale
        and the pre-commit uv-lock hook rewrote it during `git commit`.
        """
        recipe = _make_target_recipe("release-cut")
        lock_match = re.search(r"^\tuv lock\s*$", recipe, re.MULTILINE)
        assert lock_match, "release-cut must run `uv lock` to refresh the lockfile"
        bump_idx = recipe.index("scripts/update_version.py")
        assert bump_idx < lock_match.start(), "`uv lock` must run after the pyproject version bump"
        add_match = re.search(r"^\tgit add (.+?)$", recipe, re.MULTILINE)
        assert add_match, "expected explicit git add line in release-cut"
        assert "uv.lock" in add_match.group(1).split(), "uv.lock must be staged with the release commit"

    def test_release_cut_commit_skips_hooks_after_curation_removes_them(self):
        """The curation `git rm` lines delete .pre-commit-config.yaml and
        _project/scripts/ (the repo:local hook entrypoints) from the working
        tree before the release commit. The installed pre-commit git hook
        would otherwise run against a now-missing config/entrypoints and
        abort the commit, breaking every release cut."""
        recipe = _make_target_recipe("release-cut")
        commit_match = re.search(r"^\tgit commit (.+?)$", recipe, re.MULTILINE)
        assert commit_match, "expected a git commit line in release-cut"
        assert "--no-verify" in commit_match.group(1).split(), (
            f"release commit must skip hooks (curation already deleted the hook config): {commit_match.group(1)}"
        )

    def test_release_cut_aligns_release_histories_before_pushing(self):
        """release-cut must merge `origin/main` with `-s ours` before it pushes.

        `main` and `develop` have unrelated roots (Phase 4 filter-merge) and
        diverge permanently — `main` gains one squash commit per release that
        `develop` never sees, and A4 step 6 (rebase develop onto main) was
        removed by the 2026-04-27 amendment. A `vX.Y.Z` branch cut cleanly from
        `develop` is therefore not mergeable into `main`: GitHub cannot compute
        a merge ref, the PR sits at CONFLICTING, and *no CI runs at all* —
        neither `validate-base` nor `release-required-result` ever trigger.
        Every cut before v0.3.1 fixed this by hand (#711/#712/#1029/#1043/#1072).
        """
        recipe = _make_target_recipe("release-cut")
        # `\t@?git merge`, not `\t.*git merge`: recipe comments are `\t@# ...` lines
        # that precede the command, so a loose anchor would match a comment first.
        merge_match = re.search(r"^\t@?git merge (.+?)$", recipe, re.MULTILINE)
        assert merge_match, "release-cut must merge origin/main to make the release PR mergeable"

        merge_args = merge_match.group(1).split()
        # `-s ours` keeps the curated release tree byte-for-byte and only records
        # origin/main as a second parent; any other strategy drags main-only
        # content back into the release tree, silently un-curating the release.
        assert "-s" in merge_args and merge_args[merge_args.index("-s") + 1] == "ours", (
            f"alignment merge must use `-s ours` to preserve the curated tree: {merge_match.group(1)}"
        )
        assert "--allow-unrelated-histories" in merge_args, (
            "main and develop have unrelated roots; the merge needs --allow-unrelated-histories"
        )
        assert "origin/main" in merge_args, "the alignment merge must target the fetched origin/main"

        # A `-s ours` merge cannot change the tree by construction, so the guard is
        # really an assertion that the strategy above is still `ours`. It must stay.
        assert "alignment merge changed the curated release tree" in recipe, (
            "expected a post-merge guard asserting the curated release tree is unchanged"
        )

        # Ordering: changelog (--since-ref origin/main) needs main to still be a
        # non-ancestor; the merge must land on top of the release commit; and the
        # push must carry the merge, or the PR is born CONFLICTING again.
        commit_match = re.search(r"^\tgit commit .*Release v\$\(VERSION\)", recipe, re.MULTILINE)
        push_match = re.search(r"^\tgit push -u origin v\$\(VERSION\)", recipe, re.MULTILINE)
        assert commit_match, "expected the `Release v$(VERSION)` commit line in release-cut"
        assert push_match, "expected `git push -u origin v$(VERSION)` in release-cut"
        changelog_idx = recipe.index("generate_changelog_entry.py")
        assert changelog_idx < commit_match.start() < merge_match.start() < push_match.start(), (
            "alignment merge must run after the `Release v$(VERSION)` commit and before the push"
        )

    def test_release_cut_branch_sweep_matches_only_release_branches(self):
        """The Option-c stale-branch sweep must filter full refs, not `ls-remote 'v*'` alone.

        `git ls-remote --heads origin 'v*'` matches the LAST path component of a ref,
        so it also matches non-release branches like `fix/validate-submission-...`
        (last component starts with "v") — the 2026-07-08 v0.3.1 re-cut deleted exactly
        such a branch. The sweep must additionally filter the full `refs/heads/...` path
        against the release-branch shape, mirroring `_RELEASE_BRANCH_RE` in
        scripts/generate_changelog_entry.py.
        """
        recipe = _make_target_recipe("release-cut")
        sweep_match = re.search(r"^\t@?for br in \$\$\((.+?)\); do", recipe, re.MULTILINE)
        assert sweep_match, "expected the stale release-branch sweep `for br in $$(...)` in release-cut"
        pipeline = sweep_match.group(1)
        assert "awk" in pipeline, "sweep must filter with awk against the full ref, not just `ls-remote 'v*'`"

        awk_match = re.search(r"awk '(.+?)'", pipeline)
        assert awk_match, "expected an awk filter in the sweep pipeline"
        awk_program = awk_match.group(1)
        # $2 is `refs/heads/<name>` per `git ls-remote --heads` output.
        assert re.search(r"\$2\s*~", awk_program), "awk filter must match against the full ref ($2), not $1/$NF"
        assert r"refs\/heads\/" in awk_program or "refs/heads/" in awk_program, (
            "awk filter must anchor to refs/heads/ to avoid matching bare tag-ish names"
        )

        # Simulate `git ls-remote --heads` output for a realistic mix of refs and confirm
        # the sweep pipeline (minus the trailing version-exclusion) keeps only true
        # release branches, dropping the branch that caused the 2026-07-08 incident.
        sample_refs = [
            "refs/heads/v0.3.0",
            "refs/heads/v0.3.1",
            "refs/heads/v0.3.1-rc1",
            "refs/heads/fix/validate-submission-self-green-guard",
            "refs/heads/version-bump-tooling",
            "refs/heads/vendor/foo",
        ]
        sample_input = "\n".join(f"deadbeef\t{ref}" for ref in sample_refs)
        # Isolate the ref-filtering stages (awk + sed) from `ls-remote` (replaced by
        # piped-in sample data) and the trailing `grep -Fxv "v$(VERSION)"` (a Make
        # variable this test doesn't expand, and unrelated to the ref-shape bug).
        pipeline_without_ls_remote = re.sub(r"^git ls-remote --heads origin 'v\*'\s*\|\s*", "", pipeline)
        pipeline_without_version_grep = re.sub(
            r'\s*\|\s*grep -Fxv "v\$\(VERSION\)"\s*$', "", pipeline_without_ls_remote
        )
        assert pipeline_without_version_grep != pipeline_without_ls_remote, (
            "expected to isolate the awk/sed stages from the trailing version-exclusion grep"
        )
        # Make collapses `$$` to a literal `$` in recipes before the shell ever sees it;
        # emulate that here since this test runs the extracted text via bash directly.
        shell_pipeline = pipeline_without_version_grep.replace("$$", "$")
        result = subprocess.run(
            ["bash", "-c", shell_pipeline],
            input=sample_input,
            capture_output=True,
            text=True,
            check=True,
        )
        matched = set(result.stdout.split())
        assert matched == {"v0.3.0", "v0.3.1", "v0.3.1-rc1"}, (
            f"sweep must match only true release branches, got: {sorted(matched)}"
        )

    def test_issue_templates_exist(self):
        """Test that GitHub issue templates exist."""
        templates_dir = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
        assert templates_dir.exists(), "Issue templates directory must exist"

        # Required templates
        required_templates = ["bug_report.yml", "feature_request.yml", "platform_support.yml", "config.yml"]

        for template in required_templates:
            template_path = templates_dir / template
            assert template_path.exists(), f"{template} template must exist"

    def test_pr_template_exists(self):
        """Test that pull request template exists."""
        pr_template_path = REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
        assert pr_template_path.exists(), "Pull request template must exist"

        with open(pr_template_path, encoding="utf-8") as f:
            content = f.read()

        # Should have key sections
        required_sections = [
            "## Description",
            "## Type of Change",
            "## Testing",
            "## Public Contract Check",
            "## Artifact Hygiene",
            "## Notes",
        ]

        for section in required_sections:
            assert section in content, f"PR template must have {section} section"

    @pytest.mark.slow
    def test_package_build_succeeds(self):
        """Test that the package can be built successfully."""
        import subprocess
        import tempfile
        from pathlib import Path

        project_root = REPO_ROOT

        # Run uv build in a temporary directory to avoid conflicts
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["uv", "build", "--out-dir", tmpdir], cwd=project_root, capture_output=True, text=True
            )

            # Build should succeed (exit code 0)
            if result.returncode != 0:
                pytest.fail(f"Package build failed: {result.stderr}")

            # Should create both wheel and source distribution
            built_files = list(Path(tmpdir).glob("*"))
            wheel_files = [f for f in built_files if f.suffix == ".whl"]
            sdist_files = [f for f in built_files if f.suffix == ".gz"]

            assert len(wheel_files) > 0, "Build should create wheel file"
            assert len(sdist_files) > 0, "Build should create source distribution"

    def test_cli_entry_point_works(self):
        """Test that CLI entry point is properly configured."""
        import subprocess
        from pathlib import Path

        project_root = REPO_ROOT

        # Test that benchbox command works
        result = subprocess.run(["uv", "run", "benchbox", "--help"], cwd=project_root, capture_output=True, text=True)

        assert result.returncode == 0, "CLI entry point should work"
        assert "BenchBox" in result.stdout
        assert "database benchmark" in result.stdout.lower()

    def test_no_incorrect_repository_references(self):
        """Test that no files contain incorrect repository references."""
        from pathlib import Path

        project_root = REPO_ROOT

        # Directories to search (explicitly avoid large cache/build directories)
        search_dirs = [
            "benchbox",
            "tests",
            "docs",
            ".github",
        ]

        # Files to search in project root
        root_files = [
            "README.md",
            "CHANGELOG.md",
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
        ]

        problematic_files = []

        # Search in specified directories
        for search_dir in search_dirs:
            dir_path = project_root / search_dir
            if not dir_path.exists():
                continue

            for file_path in dir_path.rglob("*"):
                if not file_path.is_file():
                    continue

                # Skip binary and cache files
                if (
                    any(skip in str(file_path) for skip in ["__pycache__", ".egg-info", ".pytest_cache", ".mypy_cache"])
                    or file_path.suffix == ".pyc"
                ):
                    continue

                # Skip this test file itself
                if file_path.name == "test_release_infrastructure.py":
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    if "anthropics/claude-code" in content:
                        problematic_files.append(str(file_path.relative_to(project_root)))
                except (UnicodeDecodeError, OSError):
                    # Skip files that can't be read as text
                    pass

        # Search root files
        for root_file in root_files:
            file_path = project_root / root_file
            if not file_path.exists():
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                if "anthropics/claude-code" in content:
                    problematic_files.append(root_file)
            except (UnicodeDecodeError, OSError):
                pass

        # Filter out acceptable references
        problematic_files = [
            f for f in problematic_files if not any(acceptable in f for acceptable in ["_project/PROJECT_TODO.md"])
        ]

        if problematic_files:
            pytest.fail(f"Found incorrect repository references in: {problematic_files}")


class TestVersionConsistency:
    """Test version consistency across different files."""

    def test_version_in_pyproject_toml(self):
        """Test that version is properly defined in pyproject.toml."""
        pyproject_path = REPO_ROOT / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        version = config["project"]["version"]
        assert version is not None
        assert isinstance(version, str)
        assert len(version) > 0

        # Should be semantic version format
        import re

        semver_pattern = r"^\d+\.\d+\.\d+(-\w+)?$"
        assert re.match(semver_pattern, version), f"Version {version} should follow semantic versioning"

    def test_version_in_init_file(self):
        """Test that version is defined in __init__.py."""
        init_path = REPO_ROOT / "benchbox" / "__init__.py"

        with open(init_path, encoding="utf-8") as f:
            content = f.read()

        assert "__version__" in content, "__init__.py should define __version__"

    def test_version_consistency(self):
        """Test that version is consistent between pyproject.toml and __init__.py."""
        # Get version from pyproject.toml
        pyproject_path = REPO_ROOT / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)
        pyproject_version = config["project"]["version"]

        # Get version from __init__.py
        init_path = REPO_ROOT / "benchbox" / "__init__.py"
        with open(init_path, encoding="utf-8") as f:
            content = f.read()

        # Extract version from __init__.py
        import re

        version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        assert version_match, "Could not find __version__ in __init__.py"
        init_version = version_match.group(1)

        assert pyproject_version == init_version, (
            f"Version mismatch: pyproject.toml has {pyproject_version}, __init__.py has {init_version}"
        )


class TestReleaseWorkflowValidation:
    """Test that release workflows are valid YAML and properly structured."""

    def test_workflows_are_valid_yaml(self):
        """Test that all workflow files are valid YAML."""
        workflows_dir = REPO_ROOT / ".github" / "workflows"

        for workflow_file in workflows_dir.glob("*.yml"):
            with open(workflow_file, encoding="utf-8") as f:
                try:
                    yaml.safe_load(f)
                except yaml.YAMLError as e:
                    pytest.fail(f"Invalid YAML in {workflow_file}: {e}")

    def test_issue_templates_are_valid_yaml(self):
        """Test that issue templates are valid YAML."""
        templates_dir = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"

        for template_file in templates_dir.glob("*.yml"):
            with open(template_file, encoding="utf-8") as f:
                try:
                    yaml.safe_load(f)
                except yaml.YAMLError as e:
                    pytest.fail(f"Invalid YAML in {template_file}: {e}")


class TestPackageMetadata:
    """Test package metadata and configuration."""

    def test_license_file_exists(self):
        """Test that LICENSE file exists."""
        license_path = REPO_ROOT / "LICENSE"
        assert license_path.exists(), "LICENSE file must exist"

    def test_readme_file_exists(self):
        """Test that README.md exists."""
        readme_path = REPO_ROOT / "README.md"
        assert readme_path.exists(), "README.md file must exist"

    def test_pyproject_toml_build_config(self):
        """Test that pyproject.toml has proper build configuration."""
        pyproject_path = REPO_ROOT / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        # Should have build system configuration
        assert "build-system" in config
        build_system = config["build-system"]
        assert "requires" in build_system
        assert "build-backend" in build_system

        # Should have entry points
        assert "project" in config
        project = config["project"]
        assert "scripts" in project
        assert "benchbox" in project["scripts"]


class TestBetaReleaseSurface:
    """Ratchet tests for Beta release-surface coherence.

    These assertions prevent the status/install/packaging drift that was
    found in the 2026-04-01 pre-Beta review from recurring silently.
    """

    REPO_ROOT = Path(__file__).parent.parent.parent

    # Canonical current-state entry-point docs where release status must be Beta.
    STATUS_DOCS = [
        "README.md",
        "docs/usage/faq.md",
    ]

    # Canonical install docs that must not claim DuckDB ships with the plain install.
    INSTALL_DOCS = [
        "README.md",
        "docs/usage/installation.md",
        "docs/platforms/platform-selection-guide.md",
        "docs/platforms/duckdb.md",
        "docs/usage/faq.md",
    ]

    # Stale phrases that must not appear in canonical install docs.
    DUCKDB_DEFAULT_PHRASES = [
        "DuckDB is included with BenchBox by default",
        "included by default with BenchBox",
        "DuckDB is automatically installed as a dependency",
        "works with DuckDB out of the box",
        "DuckDB is embedded and ready to go",
    ]

    def test_pyproject_has_beta_classifier(self):
        """pyproject.toml must carry the Beta Development Status classifier."""
        pyproject_path = self.REPO_ROOT / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)
        classifiers = config["project"].get("classifiers", [])
        beta_classifiers = [c for c in classifiers if "4 - Beta" in c]
        assert beta_classifiers, (
            "pyproject.toml must have a '4 - Beta' Development Status classifier. "
            "Found classifiers: " + str(classifiers)
        )

    def test_canonical_docs_say_beta_not_alpha(self):
        """README and FAQ must describe Beta status, not Alpha."""
        alpha_pattern = re.compile(
            r"\b(alpha software|is ALPHA software|Status-Alpha|## Alpha Software)\b",
            re.IGNORECASE,
        )
        for rel_path in self.STATUS_DOCS:
            path = self.REPO_ROOT / rel_path
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            match = alpha_pattern.search(content)
            assert match is None, (
                f"{rel_path} still contains Alpha status language: {match.group()!r}. "
                "Update it to Beta before releasing."
            )

    def test_install_docs_do_not_claim_duckdb_is_default(self):
        """Install docs must not claim DuckDB ships with the plain base install."""
        for rel_path in self.INSTALL_DOCS:
            path = self.REPO_ROOT / rel_path
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            for phrase in self.DUCKDB_DEFAULT_PHRASES:
                assert phrase not in content, (
                    f"{rel_path} claims DuckDB is a default dependency ({phrase!r}). "
                    "DuckDB is an optional extra ([duckdb]). "
                    "Fix the docs or update pyproject.toml dependencies to match."
                )

    def test_duckdb_is_optional_in_pyproject(self):
        """DuckDB must be listed as an optional extra, not a core dependency."""
        pyproject_path = self.REPO_ROOT / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)
        core_deps = config["project"].get("dependencies", [])
        duckdb_in_core = [d for d in core_deps if d.startswith("duckdb")]
        assert not duckdb_in_core, (
            "DuckDB must stay in [project.optional-dependencies], not [project.dependencies]. "
            "If you intentionally restored it to core deps, also update all install docs "
            "to remove the [duckdb] extra requirement."
        )
        optional_deps = config["project"].get("optional-dependencies", {})
        assert "duckdb" in optional_deps, (
            "Expected a 'duckdb' entry in [project.optional-dependencies]. "
            "If the extra was renamed or removed, update this test and all install docs."
        )

    def test_experimental_not_in_benchbox_all(self):
        """benchbox.experimental must not be re-exported via benchbox.__all__."""
        import benchbox

        public_exports = getattr(benchbox, "__all__", [])
        experimental_exports = [name for name in public_exports if "experimental" in name.lower()]
        assert not experimental_exports, "benchbox.__all__ must not expose the experimental namespace: " + str(
            experimental_exports
        )

    def test_experimental_namespace_has_unsupported_docstring(self):
        """benchbox/experimental/__init__.py must document that it is unsupported."""
        exp_init = self.REPO_ROOT / "benchbox" / "experimental" / "__init__.py"
        assert exp_init.exists(), "benchbox/experimental/__init__.py must exist"
        content = exp_init.read_text(encoding="utf-8")
        assert "unsupported" in content.lower(), (
            "benchbox/experimental/__init__.py must contain the word 'unsupported' "
            "to document the Beta support boundary. "
            "Do not silently expand the supported product surface."
        )

    @pytest.mark.slow
    def test_ty_clean_on_beta_critical_entrypoints(self):
        """Release-critical entrypoints must produce zero ty diagnostics.

        Keeps the targeted typecheck gate durable without expanding to the
        full repository backlog.  Mark @slow so it only runs in CI and on
        explicit slow-test invocations, not on every fast-test pass.
        """
        import subprocess

        beta_critical = [
            "benchbox/cli/commands/run.py",
            "benchbox/base.py",
            "benchbox/__init__.py",
        ]
        result = subprocess.run(
            ["uv", "run", "ty", "check", *beta_critical],
            cwd=self.REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "ty check reported diagnostics on Beta-critical entrypoints.\n"
            "Fix the diagnostics before releasing Beta:\n" + result.stdout + result.stderr
        )


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    """Init a scratch repo insulated from the developer's ambient git config."""
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", ".", cwd=root)
    # A global commit.gpgsign or core.hooksPath would otherwise break _commit_all.
    for key, value in (
        ("user.email", "test@benchbox.invalid"),
        ("user.name", "BenchBox Test"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
        ("core.hooksPath", str(root / ".no-hooks")),
    ):
        _git("config", key, value, cwd=root)


def _commit_all(root: Path, message: str) -> None:
    _git("add", "-A", cwd=root)
    result = _git("commit", "-q", "--no-verify", "-m", message, cwd=root)
    assert result.returncode == 0, f"scratch commit failed: {result.stdout}{result.stderr}"


def _default_branch(root: Path) -> str:
    return _git("symbolic-ref", "--short", "HEAD", cwd=root).stdout.strip()


def _probe(root: Path, theirs: str) -> subprocess.CompletedProcess:
    """Run the exact merge probe `pr-conflict-scan` uses, HEAD vs `theirs`."""
    return _git("merge-tree", "--write-tree", "--name-only", "HEAD", theirs, cwd=root)


def _git_version() -> tuple[int, ...]:
    out = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    assert match is not None, f"unparseable git version: {out!r}"
    return tuple(int(part) for part in match.groups())


# `git merge-tree --write-tree` landed in git 2.38.
requires_modern_merge_tree = pytest.mark.skipif(
    _git_version() < (2, 38, 0),
    reason="pr-conflict-scan requires git >= 2.38 for `merge-tree --write-tree`",
)


class TestPrConflictScan:
    """`pr-conflict-scan` must warn on real conflicts and stay silent otherwise.

    Regression guard for the false-positive storm caused by parsing the
    deprecated three-arg `git merge-tree <base> <ours> <theirs>` output: its
    `changed in both` / `added in both` / `removed in {local,remote}` lines are
    informational trivial-merge headers emitted for any file both sides touched,
    not conflicts. Because nearly every PR edits CHANGELOG.md, the old probe
    warned on almost every pair.
    """

    def test_probe_uses_modern_write_tree_form(self):
        """The recipe must use the modern form and gate on a verified ref."""
        recipe = _make_target_recipe("pr-conflict-scan")

        assert 'git merge-tree --write-tree --name-only HEAD "origin/$$branch"' in recipe
        # A bad ref also exits 1, indistinguishable from a conflict, so the ref
        # must be verified before the probe runs.
        assert 'git rev-parse --verify --quiet "origin/$$branch^{commit}"' in recipe
        assert recipe.index("rev-parse --verify") < recipe.index("merge-tree")
        # Only exit status 1 means conflict; >1 is an error and must not warn.
        assert "[ $$? -eq 1 ] || continue" in recipe

    def test_probe_does_not_parse_legacy_informational_headers(self):
        """The legacy trivial-merge headers must never be treated as conflicts."""
        # _make_target_recipe returns recipe lines only, so the explanatory
        # comment above the target -- which names these headers -- is excluded.
        recipe = _make_target_recipe("pr-conflict-scan")

        for header in ("changed in both", "added in both", "removed in local", "removed in remote"):
            assert header not in recipe, f"{header!r} is an informational header, not a conflict"
        # The legacy three-arg form takes an explicit merge base as $1.
        assert 'git merge-tree "$$base"' not in recipe

    def test_scan_is_warn_only(self):
        """The probe reports; it must never fail the caller's `pr-open`."""
        recipe = _make_target_recipe("pr-conflict-scan")
        assert recipe.rstrip().endswith("done; true")

    @requires_modern_merge_tree
    def test_probe_is_silent_when_sides_touch_disjoint_files(self, tmp_path: Path):
        repo = tmp_path / "disjoint"
        _init_repo(repo)
        (repo / "ours.txt").write_text("a\n")
        (repo / "theirs.txt").write_text("b\n")
        _commit_all(repo, "base")
        base = _default_branch(repo)

        _git("checkout", "-q", "-b", "feature", cwd=repo)
        (repo / "theirs.txt").write_text("theirs edit\n")
        _commit_all(repo, "feature")

        _git("checkout", "-q", base, cwd=repo)
        (repo / "ours.txt").write_text("ours edit\n")
        _commit_all(repo, "ours")

        assert _probe(repo, "feature").returncode == 0

    @requires_modern_merge_tree
    def test_probe_is_silent_when_both_sides_edit_one_file_cleanly(self, tmp_path: Path):
        """The exact false positive: both sides edit one file, far-apart hunks."""
        repo = tmp_path / "same_file_clean"
        _init_repo(repo)
        (repo / "CHANGELOG.md").write_text("".join(f"line{i}\n" for i in range(1, 21)))
        _commit_all(repo, "base")
        base = _default_branch(repo)

        _git("checkout", "-q", "-b", "feature", cwd=repo)
        lines = (repo / "CHANGELOG.md").read_text().splitlines(keepends=True)
        lines[-1] = "feature entry\n"
        (repo / "CHANGELOG.md").write_text("".join(lines))
        _commit_all(repo, "feature")

        _git("checkout", "-q", base, cwd=repo)
        lines = (repo / "CHANGELOG.md").read_text().splitlines(keepends=True)
        lines[0] = "ours entry\n"
        (repo / "CHANGELOG.md").write_text("".join(lines))
        _commit_all(repo, "ours")

        assert _probe(repo, "feature").returncode == 0, "clean auto-merge must not warn"

        # The legacy probe the recipe used to run would have warned here.
        merge_base = _git("merge-base", "HEAD", "feature", cwd=repo).stdout.strip()
        legacy = _git("merge-tree", merge_base, "HEAD", "feature", cwd=repo).stdout
        assert "changed in both" in legacy, "the legacy false-positive trigger is still reproducible"

    @requires_modern_merge_tree
    def test_probe_warns_on_a_true_conflict(self, tmp_path: Path):
        repo = tmp_path / "conflict"
        _init_repo(repo)
        (repo / "Makefile").write_text("target:\n\techo base\n")
        _commit_all(repo, "base")
        base = _default_branch(repo)

        _git("checkout", "-q", "-b", "feature", cwd=repo)
        (repo / "Makefile").write_text("target:\n\techo feature\n")
        _commit_all(repo, "feature")

        _git("checkout", "-q", base, cwd=repo)
        (repo / "Makefile").write_text("target:\n\techo ours\n")
        _commit_all(repo, "ours")

        result = _probe(repo, "feature")
        assert result.returncode == 1, "a same-line conflict must be detected"
        # Line 1 is the tree OID; conflicted names follow, terminated by a blank line.
        conflicted = list(itertools.takewhile(bool, result.stdout.splitlines()[1:]))
        assert conflicted == ["Makefile"]

    @requires_modern_merge_tree
    def test_legacy_conflict_marker_is_diff_prefixed(self, tmp_path: Path):
        """`^<<<<<<<` can never match legacy output, so that fallback is unsafe.

        Guards against "just anchor the grep to `<<<<<<<`" — in the legacy
        format the marker is emitted inside a diff body as `+<<<<<<< .our`,
        so an anchored grep matches nothing and the scan goes permanently
        silent: a false negative on every real conflict.
        """
        repo = tmp_path / "legacy_marker"
        _init_repo(repo)
        (repo / "f.txt").write_text("base\nkeep\n")
        _commit_all(repo, "base")
        base = _default_branch(repo)

        _git("checkout", "-q", "-b", "feature", cwd=repo)
        (repo / "f.txt").write_text("feature\nkeep\n")
        _commit_all(repo, "feature")

        _git("checkout", "-q", base, cwd=repo)
        (repo / "f.txt").write_text("ours\nkeep\n")
        _commit_all(repo, "ours")

        merge_base = _git("merge-base", "HEAD", "feature", cwd=repo).stdout.strip()
        legacy = _git("merge-tree", merge_base, "HEAD", "feature", cwd=repo).stdout

        assert "<<<<<<<" in legacy
        assert not any(line.startswith("<<<<<<<") for line in legacy.splitlines())
