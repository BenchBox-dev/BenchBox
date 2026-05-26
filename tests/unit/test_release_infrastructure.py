"""Tests for release infrastructure.

Validates release-related configurations, workflows, and files to ensure
proper project release setup.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import re
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
        assert set(result_job["needs"]) == {"test", "integration", "test-package", "release-readiness"}
        assert result_job["if"] == "${{ always() && github.event_name == 'pull_request' && github.base_ref == 'main' }}"
        aggregate_run_text = _workflow_job_run_text("test.yml", "release-required-result")
        for expected in [
            "test (ubuntu-latest, 3.12)",
            "integration",
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
        assert set(jobs) == {"credential-free-non-fast", "ruleset-drift", "release-canary-result"}
        assert jobs["credential-free-non-fast"]["steps"][0]["with"]["ref"] == "${{ env.RELEASE_CANARY_REF }}"
        assert jobs["ruleset-drift"]["steps"][0]["with"]["ref"] == "${{ env.RELEASE_CANARY_REF }}"

        non_fast_text = _workflow_job_run_text("release-canary.yml", "credential-free-non-fast")
        assert "(slow or resource_heavy) and not (stress or live_integration)" in non_fast_text
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
        assert set(result_job["needs"]) == {"credential-free-non-fast", "ruleset-drift"}
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
        assert "(slow or resource_heavy) and not (stress or live_integration)" in run_text
        assert "scripts/ruleset_drift_check.py" in run_text
        assert "--require-bypass-actor-visibility" in run_text

        readiness_step = next(step for step in steps if step["name"] == "Check release canary freshness")
        assert readiness_step["env"]["RELEASE_CANARY_WORKFLOW"] == "release-canary.yml"
        assert readiness_step["env"]["RELEASE_CANARY_BRANCH"] == "main"
        assert readiness_step["env"]["RELEASE_CANARY_CHECKED_REF"] == "develop"
        assert readiness_step["env"]["RELEASE_CANARY_MAX_AGE_HOURS"] == "48"
        assert "RELEASE_READINESS_OVERRIDE_SHA" in readiness_step["env"]

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
