"""Tests for the standardized pytest command surface."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from configparser import ConfigParser
from pathlib import Path

import pytest
import yaml

from tests.integration.test_local_platform_benchmark_matrix import (
    LOCAL_SQL_STABLE_MATRIX,
    _validate_against_expected_results,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]

CI_FAST_EXPRESSION = "fast and not (slow or stress or resource_heavy or live_integration)"
CORRECTNESS_GATE_NODEID = (
    "tests/integration/test_local_platform_benchmark_matrix.py::test_local_platform_benchmark_matrix[tpch-duckdb]"
)
CORRECTNESS_GATE_QUERY_IDS = "1,2,3,4,5,6,7,8,9,10,12,13,14,15,17,19,21,22"


def _makefile_target_body(makefile_content: str, target_name: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(target_name)}:\n(?P<body>(?:\t.*\n|@.*\n|[ \t].*\n)*)", makefile_content)
    assert match, f"Makefile target not found: {target_name}"
    return match.group("body")


def _workflow_job_run_text(workflow_path: Path, job_name: str) -> str:
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"][job_name]["steps"]
    return "\n".join(str(step.get("run", "")) for step in steps)


def _load_ini_section(path: Path, section: str) -> dict[str, str]:
    parser = ConfigParser()
    parser.read(path)
    return dict(parser[section])


def _marker_names(path: Path) -> set[str]:
    marker_lines = _load_ini_section(path, "pytest")["markers"].splitlines()
    return {
        line.split(":", 1)[0].strip()
        for line in marker_lines
        if line.strip() and ":" in line and not line.strip().startswith("#")
    }


class TestStandardizedTestCommands:
    """Test the standardized test command system."""

    def test_pytest_marker_system_works(self):
        env = {**subprocess.os.environ, "BENCHBOX_SKIP_TEST_LOCK": "1"}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        assert result.returncode in (0, 2), f"Unexpected exit code: {result.returncode}"
        assert "test_" in result.stdout or "collected" in result.stdout.lower()

    def test_fast_marker_functionality(self):
        env = {**subprocess.os.environ, "BENCHBOX_SKIP_TEST_LOCK": "1"}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-m",
                "fast and not (slow or stress or resource_heavy or live_integration)",
                "--collect-only",
                "-q",
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        assert result.returncode in (0, 2), f"Unexpected exit code: {result.returncode}"
        assert "test_" in result.stdout or "collected" in result.stdout.lower()

    def test_unit_marker_functionality(self):
        env = {**subprocess.os.environ, "BENCHBOX_SKIP_TEST_LOCK": "1"}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "unit", "--collect-only", "-q"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        assert result.returncode in (0, 2), f"Unexpected exit code: {result.returncode}"
        assert "test_" in result.stdout or "collected" in result.stdout.lower()

    def test_makefile_commands_exist(self):
        makefile_path = Path.cwd() / "Makefile"
        assert makefile_path.exists(), "Makefile should exist"

        makefile_content = makefile_path.read_text()
        assert "test-fast:" in makefile_content
        assert "test-unit:" in makefile_content
        assert "test-integration:" in makefile_content
        assert "test-all:" in makefile_content
        assert "python -m pytest" in makefile_content
        assert "run_tests.py" not in makefile_content

    def test_no_legacy_run_tests_references(self):
        run_tests_path = Path.cwd() / "run_tests.py"
        assert not run_tests_path.exists(), "run_tests.py should not exist in project root"

    def test_pytest_configuration_is_valid(self):
        pytest_ini_path = Path.cwd() / "pytest.ini"
        assert pytest_ini_path.exists(), "pytest.ini should exist"

        pytest_ini_content = pytest_ini_path.read_text()
        assert "fast:" in pytest_ini_content
        assert "unit:" in pytest_ini_content
        assert "integration:" in pytest_ini_content
        assert "flaky:" in pytest_ini_content
        assert "local_only:" in pytest_ini_content
        assert "markers =" in pytest_ini_content
        assert "not slow and not stress and not live_integration and not resource_heavy" in pytest_ini_content

    def test_coverage_commands_use_pytest(self):
        makefile_path = Path.cwd() / "Makefile"
        makefile_content = makefile_path.read_text()

        coverage_section = False
        for line in makefile_content.split("\n"):
            if line.startswith("coverage:"):
                coverage_section = True
                continue
            if coverage_section and line.startswith("\t"):
                assert "python -m pytest" in line
                assert "--cov=" in line
                break


class TestMakefileCommands:
    """Test that Makefile commands work as expected."""

    def test_makefile_test_targets_defined(self):
        makefile_path = Path.cwd() / "Makefile"
        makefile_content = makefile_path.read_text()

        expected_targets = [
            "test:",
            "test-all:",
            "test-unit:",
            "test-integration:",
            "test-fast:",
            "test-medium:",
            "test-slow:",
            "coverage:",
            "coverage-html:",
        ]

        for target in expected_targets:
            assert target in makefile_content, f"Makefile should contain target: {target}"

    def test_makefile_test_unlock_expands_user_lock_dir_without_uv(self, tmp_path):
        home = tmp_path / "home"
        lock_dir = home / "tmp" / "benchbox-lock-probe"
        lock_dir.mkdir(parents=True)
        lock_path = lock_dir / "test.lock"
        lock_path.write_text("stale lock\n", encoding="utf-8")
        env = {
            **subprocess.os.environ,
            "BENCHBOX_TEST_LOCK_DIR": "~/tmp/benchbox-lock-probe",
            "HOME": str(home),
            "PATH": "/usr/bin:/bin",
        }

        result = subprocess.run(
            ["make", "--no-print-directory", "test-unlock"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        expected_path = str(lock_path)
        assert result.returncode == 0, result.stderr
        assert expected_path in result.stdout
        assert "~/tmp/benchbox-lock-probe/test.lock" not in result.stdout
        assert "uv:" not in result.stdout + result.stderr
        assert not lock_path.exists()

    def test_makefile_test_all_splits_parallel_and_serial_lanes_explicitly(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        assert "test-all:" in makefile_content
        assert '-m "not (slow or stress or resource_heavy or live_integration)"' in makefile_content
        assert '-m "(slow or resource_heavy) and not (stress or live_integration)" -n 0' in makefile_content

    def test_makefile_test_fast_excludes_heavy_and_opt_in_lanes(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        assert "test-fast:" in makefile_content
        assert '-m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short' in makefile_content

    def test_pr_preflight_fast_tests_uses_required_ci_marker_expression(self):
        repo_root = Path.cwd()
        makefile_content = (repo_root / "Makefile").read_text()
        preflight_body = _makefile_target_body(makefile_content, "pr-preflight-fast-tests")
        develop_pr_run_text = _workflow_job_run_text(repo_root / ".github" / "workflows" / "pr.yml", "code-test")
        main_pr_run_text = _workflow_job_run_text(repo_root / ".github" / "workflows" / "test.yml", "test")

        assert f'-m "{CI_FAST_EXPRESSION}"' in preflight_body
        assert "-m fast -q" not in preflight_body
        assert f'-m "{CI_FAST_EXPRESSION}"' in develop_pr_run_text
        assert f'-m "{CI_FAST_EXPRESSION}"' in main_pr_run_text
        assert "--cov-fail-under=70" in develop_pr_run_text
        assert "--cov-fail-under=70" in main_pr_run_text
        assert "coverage remains CI-only" in makefile_content

    def test_test_ci_is_maintained_broad_local_profile(self):
        repo_root = Path.cwd()
        makefile_content = (repo_root / "Makefile").read_text()
        pytest_ci_content = (repo_root / "pytest-ci.ini").read_text()
        pytest_ci_addopts = _load_ini_section(repo_root / "pytest-ci.ini", "pytest")["addopts"]

        test_ci_body = _makefile_target_body(makefile_content, "test-ci")
        assert "-c pytest-ci.ini" in test_ci_body
        assert '-m "not (slow or flaky or local_only)"' in test_ci_body
        assert "--cov=benchbox" in test_ci_body
        assert "Maintained broad local CI profile" in makefile_content
        assert "flaky:" in pytest_ci_content
        assert "local_only:" in pytest_ci_content
        assert "source = benchbox" in pytest_ci_content
        assert "--cov-config=.coveragerc_core" in pytest_ci_addopts
        assert _marker_names(repo_root / "pytest.ini") <= _marker_names(repo_root / "pytest-ci.ini")

    def test_coverage_threshold_policy_distinguishes_blocking_and_advisory_thresholds(self):
        repo_root = Path.cwd()
        makefile_content = (repo_root / "Makefile").read_text()
        pr_workflow = (repo_root / ".github" / "workflows" / "pr.yml").read_text()
        test_workflow = (repo_root / ".github" / "workflows" / "test.yml").read_text()
        conftest_content = (repo_root / "tests" / "conftest.py").read_text()

        assert "--cov-fail-under=70" in makefile_content
        assert "--cov-fail-under=70" in pr_workflow
        assert "--cov-fail-under=70" in test_workflow
        assert "70 is the blocking CI floor" in makefile_content
        assert "threshold = 80.0" in conftest_content
        assert "intentionally advisory" in conftest_content
        assert "pytest.fail" not in conftest_content.split("def pytest_terminal_summary", maxsplit=1)[1]

    def test_makefile_test_medium_uses_five_workers(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        assert "test-medium:" in makefile_content
        assert (
            '-m "medium and not (slow or stress or resource_heavy or live_integration)" --tb=short --timeout=60 -n 5'
            in makefile_content
        )

    def test_medium_marker_policy_is_documented_as_explicit_routing(self):
        repo_root = Path.cwd()
        readme_content = (repo_root / "tests" / "README.md").read_text()
        makefile_content = (repo_root / "Makefile").read_text()

        assert "Medium tests are an explicit local routing tier" in readme_content
        assert "Correctness-relevant medium tests must be promoted" in readme_content
        assert "test-medium:" in makefile_content

    def test_makefile_correctness_gate_runs_expected_results_backed_matrix_slice(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()
        gate_body = _makefile_target_body(makefile_content, "test-correctness-gate")

        assert "BENCHBOX_STRICT_EXPECTED_RESULTS=1" in gate_body
        # The value oracle: the gate must arm full-result digest emission so it
        # validates VALUES, not just row counts. Without this the digest check
        # silently no-ops (no digest emitted) and the gate regresses to
        # cardinality-only.
        assert "BENCHBOX_EMIT_RESULT_DIGEST=1" in gate_body
        assert f"BENCHBOX_CORRECTNESS_GATE_QUERY_IDS={CORRECTNESS_GATE_QUERY_IDS}" in gate_body
        assert CORRECTNESS_GATE_NODEID in gate_body
        assert "-m stress" in gate_body
        assert "-n 0" in gate_body
        assert "--timeout=1200" in gate_body

    def test_correctness_gate_nodeid_collects_under_stress(self):
        """The gate node-id must actually resolve under ``-m stress``.

        The string ratchet above only checks the Makefile spelling; a future
        reorder/rename of the matrix parametrize would keep that string valid while
        the node stops collecting (pytest exit 5). Collection is cheap (no benchmark
        runs), so assert the exact node-id resolves to exactly one test.
        """
        proc = subprocess.run(
            # -n 0 overrides the pytest.ini "-n auto" addopts so collection does not
            # spawn xdist workers; SKIP_TEST_LOCK bypasses the parallel-run lock held
            # by the parent run (safe: --collect-only executes no tests).
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "-n",
                "0",
                "-m",
                "stress",
                CORRECTNESS_GATE_NODEID,
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "BENCHBOX_SKIP_TEST_LOCK": "1"},
        )
        assert proc.returncode == 0, (
            f"Gate node-id failed to collect under -m stress (rc={proc.returncode}).\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )
        assert CORRECTNESS_GATE_NODEID in proc.stdout, f"Gate node-id not present in collection output:\n{proc.stdout}"

    def test_develop_pr_invokes_bounded_correctness_gate(self):
        repo_root = Path.cwd()
        workflow = yaml.safe_load((repo_root / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["correctness-gate"]
        aggregate = workflow["jobs"]["ci-required-result"]

        assert job["needs"] == "ci-paths"
        assert "needs-code-ci == 'true'" in job["if"]
        assert "make test-correctness-gate" in _workflow_job_run_text(
            repo_root / ".github" / "workflows" / "pr.yml",
            "correctness-gate",
        )
        assert "correctness-gate" in aggregate["needs"]
        assert "CORRECTNESS_RESULT" in _workflow_job_run_text(
            repo_root / ".github" / "workflows" / "pr.yml",
            "ci-required-result",
        )

    def test_correctness_gate_job_runs_value_level_equivalence_steps(self):
        """The required correctness-gate job runs VALUE-level gates, not only row counts.

        A reader who sees only ``make test-correctness-gate`` in the ratchet above
        could infer the required job is row-count-only. It is not: the same job runs
        the TPC-Havoc variant/DataFrame equivalence gates and the cross-surface
        SQL<->DataFrame equivalence gates, all of which compare full result VALUES.
        Pin that composition so dropping a value-level step is caught.
        """
        repo_root = Path.cwd()
        run_text = _workflow_job_run_text(repo_root / ".github" / "workflows" / "pr.yml", "correctness-gate")

        # Row-count + value-digest TPC-H gate.
        assert "make test-correctness-gate" in run_text
        # Value-level TPC-Havoc variant gates.
        assert "make tpchavoc-equivalence-report" in run_text
        assert "make tpchavoc-dataframe-equivalence-report" in run_text
        # Value-level cross-surface SQL<->DataFrame gates (enforced subset).
        for target in (
            "make ssb-cross-surface-equivalence-report",
            "make amplab-cross-surface-equivalence-report",
            "make coffeeshop-cross-surface-equivalence-report",
        ):
            assert target in run_text, f"required correctness-gate job missing value-level step: {target}"

    def test_main_release_required_includes_bounded_correctness_gate(self):
        repo_root = Path.cwd()
        workflow = yaml.safe_load((repo_root / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["correctness-gate"]
        aggregate = workflow["jobs"]["release-required-result"]

        assert "github.base_ref == 'main'" in job["if"]
        assert "make test-correctness-gate" in _workflow_job_run_text(
            repo_root / ".github" / "workflows" / "test.yml",
            "correctness-gate",
        )
        assert "correctness-gate" in aggregate["needs"]

    def test_lint_markers_runs_marker_strategy_policy_explicitly(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()
        lint_body = _makefile_target_body(makefile_content, "lint-markers")

        assert "--collect-only" in lint_body
        assert "tests/unit/test_marker_strategy.py -q" in lint_body

    def test_makefile_test_slow_runs_serially(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        assert "test-slow:" in makefile_content
        assert '-m "slow and not (stress or live_integration)" -n 0 --tb=short -v' in makefile_content

    def test_runtime_no_longer_depends_on_generated_bucket_files(self):
        assert not (Path.cwd() / "_project" / "config" / "test_speed_buckets.json").exists()
        assert not (Path.cwd() / "_project" / "scripts" / "generate_test_speed_buckets.py").exists()

    def test_makefile_uses_pytest_consistently(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        test_lines = [line for line in makefile_content.split("\n") if line.startswith("\tuv run -- python -m pytest")]

        assert len(test_lines) > 5, "Should have multiple pytest-based commands"
        for line in test_lines:
            assert line.startswith("\tuv run -- python -m pytest"), f"Line should use pytest: {line}"


def _gate_query_ids() -> list[str]:
    """Configured correctness-gate query ids.

    Derived from the ``CORRECTNESS_GATE_QUERY_IDS`` constant, which
    ``test_makefile_correctness_gate_runs_expected_results_backed_matrix_slice``
    already pins to the actual Makefile target, so this stays a single source of truth.
    """
    return [q for q in CORRECTNESS_GATE_QUERY_IDS.split(",") if q]


class TestCorrectnessGateOracle:
    """Ratchets and behavioral guards that keep the bounded correctness gate discriminating.

    These guard the *oracle* (query-set discrimination, strict-mode arming, no-skip), not
    just the command spelling. They stay in the module-default ``unit``/``medium`` tier:
    the correctness gate itself runs as a dedicated required CI job (``correctness-gate`` in
    ``.github/workflows/pr.yml``) on every code-impacting PR, so these meta-guards do not
    also need the fast lane -- they prevent local config regression and run via the medium
    lane and the explicit gate verification command.
    """

    # TPC-H queries whose SF=1 answer-set cardinality varies across dbgen builds because
    # their HAVING/threshold boundaries are data-sensitive. #744 deliberately excluded them
    # from the gate even with the reference seed pinned; keep them out (see Makefile note).
    DBGEN_UNSTABLE_QUERY_IDS = {"11", "16", "18", "20"}

    def test_gate_query_set_is_answer_backed_and_discriminating(self):
        """The gate subset must stay answer-backed and not regress to all/mostly one-row.

        #737 originally gated ``6,14,15,17,19`` -- every one of which returns exactly one
        row at SF=1, so row-count validation could not catch wrong joins, filters, or
        aggregate values that still emit a single row. This ratchet fails if the set drifts
        back toward that near-vacuous shape.
        """
        from benchbox.core.expected_results.tpch_results import load_tpch_expected_results

        ids = _gate_query_ids()
        row_counts = load_tpch_expected_results(scale_factor=1.0)

        missing = [q for q in ids if q not in row_counts]
        assert not missing, f"gate queries lack stored SF=1 answer cardinalities: {missing}"

        one_row = [q for q in ids if row_counts[q] == 1]
        multi_row = [q for q in ids if row_counts[q] > 1]
        high_card = [q for q in ids if row_counts[q] >= 100]

        assert len(multi_row) > len(one_row), (
            f"correctness gate is dominated by one-row queries "
            f"({len(one_row)} one-row vs {len(multi_row)} multi-row); add answer-backed "
            f"high/mid-cardinality queries so wrong single-row answers are detectable"
        )
        assert len(high_card) >= 2, (
            f"correctness gate needs at least two answer-backed queries with SF=1 cardinality "
            f">=100 for discrimination; have {sorted(high_card, key=int)}"
        )

    def test_gate_excludes_dbgen_unstable_threshold_queries(self):
        """The dbgen-build-unstable threshold queries must stay out of the gate."""
        included = self.DBGEN_UNSTABLE_QUERY_IDS.intersection(_gate_query_ids())
        assert not included, (
            f"correctness gate must exclude dbgen-build-unstable threshold queries "
            f"{sorted(included, key=int)}; their HAVING/threshold cardinality varies across "
            f"dbgen builds (see #744 and the test-correctness-gate Makefile note)"
        )

    def test_gate_target_enforces_no_skip(self):
        """The gate target must fail if its selected node skips or does not run exactly once.

        ``pytest`` exits 0 when a *selected* node SKIPs (e.g. duckdb unavailable, or the case
        is excluded from the stable matrix), which would let ``make test-correctness-gate``
        pass without running anything. The target must emit a JUnit report and assert exactly
        one test ran with zero skips/errors/failures.
        """
        gate_body = _makefile_target_body((Path.cwd() / "Makefile").read_text(), "test-correctness-gate")
        assert "--junitxml=" in gate_body, "gate must emit a JUnit report to verify the node actually ran"
        # The guard parses that report (no brittle stdout scraping) and must assert the exact
        # ran/skip condition. Pin the condition tokens so a disarmed guard (e.g. relaxing to
        # `skipped >= 0`, or dropping the exit) is caught, not just the presence of "skipped".
        assert "tests == 1" in gate_body, "gate guard must require exactly one node to run"
        assert "skipped == 0" in gate_body, "gate guard must require zero selected skips"
        assert "PYTEST_STATUS" in gate_body, "gate must also propagate the pytest exit status"

    def test_gate_node_is_in_stable_matrix(self):
        """The (duckdb, tpch) node the gate targets must remain in the stable matrix.

        If it is dropped/renamed, the parametrized node would skip and -- absent the no-skip
        guard above -- the gate would pass vacuously.
        """
        assert "tpch" in LOCAL_SQL_STABLE_MATRIX.get("duckdb", set()), (
            "gate node tpch-duckdb is no longer in LOCAL_SQL_STABLE_MATRIX; the gate would skip"
        )

    def test_strict_mode_fails_on_scale_drift(self, monkeypatch):
        """Strict expected-results mode must fail when configured checks SKIP under scale drift.

        Regression guard for the previously ``scale_factor >= 1.0``-gated strict block: a gate
        retargeted to SF<1 would SKIP every stored-answer check, silently disarming the oracle
        while still exiting 0. SF=0.1 has no stored TPC-H answer file, so validation SKIPs and
        ``checked`` stays 0 -- under strict mode that is now a hard failure.
        """
        monkeypatch.setenv("BENCHBOX_STRICT_EXPECTED_RESULTS", "1")
        payload = {"queries": [{"id": "9", "stream": 0, "status": "SUCCESS", "rows": 175}]}
        with pytest.raises(AssertionError, match="strict expected-results"):
            _validate_against_expected_results(payload, "tpch", 0.1, expected_query_ids={"9"})

    def test_strict_mode_fails_on_benchmark_drift(self, monkeypatch):
        """Strict mode must fail when a configured benchmark has no stored answers."""
        monkeypatch.setenv("BENCHBOX_STRICT_EXPECTED_RESULTS", "1")
        payload = {"queries": [{"id": "1", "stream": 0, "status": "SUCCESS", "rows": 5}]}
        with pytest.raises(AssertionError, match="strict expected-results"):
            _validate_against_expected_results(payload, "tpch_future_variant", 1.0, expected_query_ids={"1"})

    def test_strict_mode_passes_when_all_configured_queries_evaluate(self, monkeypatch):
        """Strict mode passes when every configured query evaluates against stored answers.

        At SF=1 the value oracle is armed too, so a configured query must supply BOTH
        the correct row count AND a matching value digest. The digest is read from the
        provider (not hard-coded) so the test tracks the stored reference.
        """
        from benchbox.core.expected_results import register_all_providers
        from benchbox.core.expected_results.registry import get_registry

        monkeypatch.setenv("BENCHBOX_STRICT_EXPECTED_RESULTS", "1")
        register_all_providers()
        q9_digest = get_registry().get_expected_result("tpch", "9", 1.0, 0).value_digest
        payload = {"queries": [{"id": "9", "stream": 0, "status": "SUCCESS", "rows": 175, "digest": q9_digest}]}
        _validate_against_expected_results(payload, "tpch", 1.0, expected_query_ids={"9"})

    def test_strict_mode_fails_on_value_digest_mismatch(self, monkeypatch):
        """At SF=1 a wrong VALUE (right cardinality) must fail strict mode RED.

        This is the headline value-oracle guarantee in the gate's own validation
        seam: Q9's row count is correct but the emitted digest is wrong.
        """
        monkeypatch.setenv("BENCHBOX_STRICT_EXPECTED_RESULTS", "1")
        payload = {
            "queries": [{"id": "9", "stream": 0, "status": "SUCCESS", "rows": 175, "digest": "deadbeefwrongdigest"}]
        }
        with pytest.raises(AssertionError, match="VALUE DIGEST mismatch"):
            _validate_against_expected_results(payload, "tpch", 1.0, expected_query_ids={"9"})

    def test_strict_mode_fails_when_value_digest_missing(self, monkeypatch):
        """At SF=1 a missing emitted digest disarms the value oracle -> strict RED."""
        monkeypatch.setenv("BENCHBOX_STRICT_EXPECTED_RESULTS", "1")
        payload = {"queries": [{"id": "9", "stream": 0, "status": "SUCCESS", "rows": 175}]}
        with pytest.raises(AssertionError, match="strict value-digest"):
            _validate_against_expected_results(payload, "tpch", 1.0, expected_query_ids={"9"})

    def test_non_strict_mode_tolerates_unsupported_validation(self, monkeypatch):
        """Default (non-strict) matrix behavior must still skip unsupported validation, not fail."""
        monkeypatch.delenv("BENCHBOX_STRICT_EXPECTED_RESULTS", raising=False)
        payload = {"queries": [{"id": "9", "stream": 0, "status": "SUCCESS", "rows": 175}]}
        _validate_against_expected_results(payload, "tpch", 0.1, expected_query_ids={"9"})
