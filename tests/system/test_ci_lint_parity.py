"""Local/CI lint-guard parity pin.

Guards that only run in CI (never locally) fire for the first time on a
pushed PR, costing a full remote round trip per miss. This test parses
``.github/workflows/pr.yml`` -- the source of truth -- and asserts that
every guard command the `lint` job (job id ``code-lint``) runs after its
dependency-install step also appears, verbatim, in the Makefile's
``ci-lint`` recipe. Parity is asserted at the COMMAND level (not just
target/step names): a local target that happens to share a name with a CI
step but runs different logic must NOT be treated as satisfying parity.

Steps that are genuinely CI-only stay out of ``ci-lint`` and must be listed
in ``EXCLUDED_STEPS`` below with a reason -- never silently dropped and
never faked by weakening the CI guard to pass locally. See
docs/operations/ci-local-parity.md for the parity invariant and how to add
a new lint guard without breaking this test.

This module also pins the `code-lint` job's report-all structure: every
guard step runs to completion in one CI cycle (via `continue-on-error`)
instead of the job stopping at the first failure, and a final
`lint-guard-summary` step derives the guard set from the `guard-*` id
naming convention -- never a hand-maintained id list, which would let a
newly added guard silently escape aggregation. See
docs/operations/ci-local-parity.md for the naming-convention contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# medium, not fast: at authoring time the fast-lane merge ref sat at exactly
# the max_fast_tests ceiling (25545); medium still runs in the required
# pre-merge lane (medium-test), so parity stays enforced without contending
# on the shared fast-lane budget this batch is in the middle of fixing.
pytestmark = pytest.mark.medium

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"
PUBLICATION_DOCS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publication-lane-docs.yml"
RELEASE_TEST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
MAKEFILE = REPO_ROOT / "Makefile"
LINT_JOB_ID = "code-lint"

# Naming convention the `code-lint` job's report-all aggregation relies on:
# every independent guard step gets `id: guard-<slug>` + `continue-on-error:
# true`, and the aggregator (below) discovers the guard set by filtering the
# `steps` context on this prefix -- never a hand-maintained id list, which
# would let a newly added guard silently escape aggregation.
GUARD_ID_PREFIX = "guard-"
AGGREGATOR_STEP_NAME = "lint-guard-summary"

# Steps whose `run:` command is a setup/install action, not a guard -- they
# have no failure-condition semantics of their own and ci-lint doesn't need
# a matching line (uv/make handle env sync implicitly). Identified by name
# so reordering the job doesn't silently stop excluding them.
SETUP_STEP_NAMES = {"Install dependencies"}

# Steps that are genuinely CI-only. Every entry needs a reason, and the test
# below fails if a listed step is renamed or removed -- so this dict can't
# rot into cover for a guard that quietly stopped existing.
EXCLUDED_STEPS: dict[str, str] = {
    "Fast lane ceiling delta vs develop": (
        "CI-cache-dependent, no local equivalent: the guard's input is "
        "`fast-lane-count.txt`, restored from the GitHub Actions cache "
        "(`actions/cache/restore@v4`, exact key "
        "`fast-lane-count-develop-<base-sha>`, populated by "
        "develop-post-merge.yml's own cache-save step) -- "
        "there is no Actions cache to restore from in a local shell. This "
        "is fail-open by design: `timing_policy_check.py --delta-check` "
        "prints `DELTA_CHECK_SKIPPED (no develop baseline available - "
        "absolute ceiling still enforced)` and exits 0 whenever the count "
        "file is missing, which is exactly the state a local run is always "
        "in. `guard-timing-policy` (the `--strict` step just above this "
        "one) already enforces the absolute `max_fast_tests` ceiling "
        "locally via `ci-lint` -- this guard is additive to that, not a "
        "replacement for it. See docs/operations/fast-lane-budget.md."
    ),
}

# The develop PR umbrella is not the only merge-gating workflow. Keep the
# guard-shaped steps in the release test workflow and the independent
# publication docs lane visible here as well. A local equivalent may be a
# stricter Make target; a hosted-only exception must name the missing input or
# service and is documented in docs/operations/ci-local-parity.md.
MERGE_GATE_WORKFLOWS = {
    "pr.yml": PR_WORKFLOW,
    "publication-lane-docs.yml": PUBLICATION_DOCS_WORKFLOW,
    "test.yml": RELEASE_TEST_WORKFLOW,
}
MERGE_GATE_SETUP_NAMES = {
    "Checkout code",
    "Checkout repository",
    "Install dependencies",
    "Install focused test dependencies",
    "Create virtual environment",
    "Fetch base branch",
    "Recreate path lists",
}
MERGE_GATE_NON_GUARD_JOBS = {
    "certification-identity",
    "ci-required-result",
    "release-required-result",
}
MERGE_GATE_GUARD_TOKENS = (
    "guard",
    "check",
    "verify",
    "validate",
    "drift",
    "parity",
    "hygiene",
    "isolation",
    "audit",
    "test",
    "lint",
)

# Step keys that have a local proving command. The value is deliberately a
# substring rather than a workflow-specific command parser: command-level
# parity for code-lint remains owned by _guard_commands() above, while these
# entries pin the other merge-gate surfaces to their local entry points.
MERGE_GATE_LOCAL_EQUIVALENTS: dict[tuple[str, str, str], str] = {
    ("pr.yml", "content-guard", "Validate YAML hygiene"): "pr-content-guard",
    ("pr.yml", "content-guard", "Validate artifact hygiene"): "pr-content-guard",
    ("pr.yml", "content-guard", "Validate markdown hygiene"): "pr-content-guard",
    ("pr.yml", "content-guard", "Validate docs references"): "pr-content-guard",
    ("pr.yml", "content-guard", "Validate public contract drift guard"): "pr-content-guard",
    ("pr.yml", "skill-integrity", "Validate skill config, receipt, and tool pin"): "skill-integrity-check",
    ("pr.yml", "skill-integrity", "Validate tracked artifact hygiene"): "skill-integrity-check",
    ("pr.yml", "skill-integrity", "Enforce untracked mirror boundary"): "ci-lint",
    ("pr.yml", "code-lint", "Lint and format check with ruff"): "ci-lint",
    ("pr.yml", "code-lint", "Type check with ty"): "ci-lint",
    ("pr.yml", "code-lint", "Validate test marker annotations"): "ci-lint",
    ("pr.yml", "code-lint", "Validate import layering"): "ci-lint",
    ("pr.yml", "code-lint", "Validate Windows antipatterns"): "ci-lint",
    ("pr.yml", "code-lint", "Validate artifact hygiene"): "ci-lint",
    ("pr.yml", "code-lint", "Validate agent instruction authority and efficiency"): "ci-lint",
    ("pr.yml", "code-lint", "Validate no agent authorship or attribution in PR commits"): "ci-lint",
    ("pr.yml", "code-lint", "UAT spec LOC table drift check"): "ci-lint",
    ("pr.yml", "code-lint", "Compatibility governance drift check"): "ci-lint",
    ("pr.yml", "code-lint", "Platform manifest drift check"): "ci-lint",
    ("pr.yml", "code-lint", "Oracle coverage map drift check"): "ci-lint",
    ("pr.yml", "code-lint", "Public contract drift check"): "ci-lint",
    ("pr.yml", "code-lint", "Dependency inventory drift check"): "ci-lint",
    ("pr.yml", "code-lint", "Release curation list drift check"): "ci-lint",
    ("pr.yml", "code-lint", "Untracked skill-mirror drift guard (cloud parity)"): "ci-lint",
    ("pr.yml", "parity-check", "Verify parity fixtures match Python source"): "parity-check",
    ("publication-lane-docs.yml", "build-docs-lane", "Verify lane isolation"): "lane-isolation-check",
    ("test.yml", "test", "Run linting"): "ci-lint",
    ("test.yml", "test", "Run type checking"): "ci-lint",
    ("test.yml", "compat-test", "Run linting"): "ci-lint",
    ("test.yml", "compat-test", "Run type checking"): "ci-lint",
    ("test.yml", "parity", "Verify parity fixtures match Python source"): "parity-check",
}

MERGE_GATE_EXEMPTIONS: dict[tuple[str, str, str], str] = {
    ("pr.yml", "ci-paths", "Validate TODO JSON/Git state contract"): (
        "Hosted classifier bootstrap; it runs before dependency installation and "
        "has no standalone Make target. The local preflight consumes the same "
        "classifier through pr-preflight."
    ),
    ("pr.yml", "tpch-binary-framing", "Verify bundled dbgen binaries emit clean framing"): (
        "Cross-platform macOS/Windows binary smoke; the local macOS checkout has no Windows runner equivalent."
    ),
    ("pr.yml", "skill-integrity", "Clone skill sources to the configured checkout paths"): (
        "Hosted provenance step; it clones published skill sources into a fresh "
        "runner home, which a local checkout must not overwrite."
    ),
    ("pr.yml", "skill-integrity", "Preview, apply, verify, and re-check the skill mirrors"): (
        "Hosted source-materialization step; skill-integrity-check proves the "
        "local committed payload but does not clone remote source checkouts."
    ),
    ("pr.yml", "skill-integrity", "Audit instruction authority and PR commit identity"): (
        "The hosted command checks the immutable PR base range; ci-lint covers the "
        "current checkout and agent-commit-range-check covers local commits."
    ),
    ("pr.yml", "code-test", "Run cross-surface mutation target drift guard"): (
        "Promoted slow regression guard; it is intentionally CI-gated and is not "
        "silently represented by the fast local test lane."
    ),
    ("pr.yml", "code-test", "Run cross-surface GATES Make/CI pinning guard"): (
        "Promoted medium regression guard; its explicit CI node prevents marker "
        "selection from dropping it and has no cheaper local equivalent."
    ),
    ("pr.yml", "code-test", "Run promoted TPC-DS power-test drain-before-commit reproducer"): (
        "Promoted slow regression guard; it is intentionally CI-gated and is not "
        "silently represented by the fast local test lane."
    ),
    ("pr.yml", "postgres-integration", "Wait for PostgreSQL service to be reachable"): (
        "Non-blocking service sample; the hosted container is deliberately not a "
        "local prerequisite for the required product lane."
    ),
    ("pr.yml", "postgres-integration", "Run PostgreSQL live integration tests"): (
        "Non-blocking live service sample; the hosted PostgreSQL container has no "
        "local equivalent in the required product lane."
    ),
    ("pr.yml", "publication-reconciliation", "Run publication plan reconciliation (live Git state)"): (
        "Hosted reconciliation reads the live tracker and publication refs; local "
        "preflight cannot safely substitute those mutable inputs."
    ),
    ("pr.yml", "audit-sha", "Validate changed audit develop SHA stamps"): (
        "Hosted audit lane compares the PR event base and merge-queue ancestry; "
        "those refs are not available as a stable local input."
    ),
    ("test.yml", "check-test-patterns", "Run patch safety check"): (
        "Release-branch-only patch audit; no local target exists and its absence "
        "is explicit rather than a silent CI-only guard."
    ),
    ("test.yml", "release-readiness", "Check dependency upper bounds"): (
        "Release-candidate-only artifact report; local develop preflight does not "
        "produce the release artifact it validates."
    ),
    ("test.yml", "release-readiness", "Check release branch curation"): (
        "Release-candidate-only curation of the curated branch; it is not a develop-tree contract."
    ),
    ("test.yml", "parity", "Detect results explorer"): (
        "Hosted Node-lane dependency sentinel; the local parity target assumes "
        "the checked-in application and does not manufacture its optional tree."
    ),
    ("test.yml", "parity", "Run Vitest parity suite"): (
        "Release parity's Node/npm suite is hosted in this workflow; it is not a "
        "silent omission because the exception names the exact runner surface."
    ),
    ("pr.yml", "skill-integrity", "Run skill policy and instruction audit contracts"): (
        "The hosted contract bundle runs the complete policy/audit test set; the "
        "same tests run as part of the local full preflight rather than a separate "
        "lightweight Make target."
    ),
    ("pr.yml", "code-test", "Run promoted h2odb mutation-catch reproducer (#901)"): (
        "Promoted slow mutation regression; it is intentionally CI-gated and is "
        "not silently represented by the fast local lane."
    ),
    ("pr.yml", "code-test", "Run promoted plan-capture-phase reproducers (#909)"): (
        "Promoted slow regression; it is intentionally CI-gated and is not silently represented by the fast local lane."
    ),
    ("pr.yml", "code-test", "Run DuckLake in-process adapter integration tests"): (
        "Optional integration dependency is hosted in this lane; the local "
        "required preflight does not manufacture the DuckLake service."
    ),
    ("pr.yml", "code-test", "Run promoted DuckDB FK tuning load-ordering reproducers"): (
        "Promoted slow regression; it is intentionally CI-gated and is not silently represented by the fast local lane."
    ),
    ("pr.yml", "code-test", "Run promoted TPC-H power/throughput boundary-query (w0 defect) reproducers"): (
        "Promoted slow regression; it is intentionally CI-gated and is not silently represented by the fast local lane."
    ),
    ("pr.yml", "code-test", "Run fast tests"): "Covered by the local `test-fast` target.",
    ("pr.yml", "medium-test", "Run medium speed tier"): "Covered by the local `test-medium` target.",
    ("pr.yml", "correctness-gate", "Run bounded real-result correctness gate"): (
        "Covered by the local `test-correctness-gate` target."
    ),
    ("pr.yml", "postgres-integration", "Run TPC-Havoc PostgreSQL variant-equivalence sample"): (
        "Hosted PostgreSQL is an optional service sample; the local required lane "
        "does not start or substitute that service."
    ),
    (
        "pr.yml",
        "datafusion-integration",
        "Run TPC-Havoc DataFusion variant-equivalence sample and .tbl load regression",
    ): ("Hosted integration sample with its own dependency/runtime; the local required lane does not substitute it."),
    ("pr.yml", "clickhouse-integration", "Run TPC-Havoc ClickHouse variant-equivalence sample"): (
        "Hosted ClickHouse is an optional service sample; the local required lane "
        "does not start or substitute that service."
    ),
    ("pr.yml", "explorer-tokens", "Run explorer token scan"): "Covered by the local `lint-explorer-tokens` target.",
    (
        "pr.yml",
        "site-theme-tokens",
        "Run public site theme token scan",
    ): "Covered by the local `lint-site-theme-tokens` target.",
    ("pr.yml", "package-smoke", "Test package installation"): "Covered by the local `test-package` target.",
    ("pr.yml", "dependency-audit", "Run security audit"): "Covered by the local `security-audit` target.",
    ("pr.yml", "explorer-vitest", "Run Explorer Vitest suite"): (
        "Hosted Node/npm lane; the local required Python preflight does not manufacture the Explorer dependency tree."
    ),
    ("pr.yml", "audit-sha", "Fetch PR head for audit ancestry (merge queue only)"): (
        "Merge-queue-only ref preparation; those ephemeral refs do not exist in a stable local checkout."
    ),
    ("test.yml", "test", "Run linting"): "Covered by the local `ci-lint` target.",
    ("test.yml", "test", "Run type checking"): "Covered by the local `ci-lint` target.",
    ("test.yml", "test", "Run fast tests"): "Covered by the local `test-fast` target.",
    ("test.yml", "compat-test", "Run linting"): "Covered by the local `ci-lint` target.",
    ("test.yml", "compat-test", "Run type checking"): "Covered by the local `ci-lint` target.",
    ("test.yml", "compat-test", "Run fast tests"): "Covered by the local `test-fast` target.",
    ("test.yml", "security", "Run security audit"): "Covered by the local `security-audit` target.",
    ("test.yml", "integration-smoke", "Run integration smoke tests"): (
        "Covered by the local `test-integration-smoke` target."
    ),
    ("test.yml", "integration-table-formats", "Run table-format integration tests"): (
        "Covered by the local integration test target; the hosted job selects an optional table-format marker."
    ),
    ("test.yml", "integration", "Run integration tests"): "Covered by the local `test-integration` target.",
    ("test.yml", "correctness-gate", "Run bounded real-result correctness gate"): (
        "Covered by the local `test-correctness-gate` target."
    ),
    ("test.yml", "test-package", "Test package installation"): "Covered by the local `test-package` target.",
    ("test.yml", "pyspark-tests", "Run PySpark tests"): "Covered by the local `test-pyspark` target.",
}


def _workflow_steps(path: Path) -> list[tuple[str, dict]]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        (job_name, step)
        for job_name, job in workflow.get("jobs", {}).items()
        for step in job.get("steps", [])
        if isinstance(step, dict)
    ]


def _is_guard_shaped_step(job_name: str, step: dict) -> bool:
    name = str(step.get("name", ""))
    run = str(step.get("run", ""))
    if not run or name in MERGE_GATE_SETUP_NAMES or job_name in MERGE_GATE_NON_GUARD_JOBS:
        return False
    if name == AGGREGATOR_STEP_NAME:
        return False
    # The code-lint parser above remains the detailed command-level contract;
    # this broader inventory catches guard/check steps in other merge gates.
    return job_name != LINT_JOB_ID and any(token in f"{name} {run}".lower() for token in MERGE_GATE_GUARD_TOKENS)


def _load_lint_job_steps() -> list[dict]:
    workflow = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"][LINT_JOB_ID]
    return job["steps"]


def _guard_commands() -> dict[str, list[str]]:
    """Map step name -> list of individual shell command lines.

    Steps with no `run:` key (pure `uses:` actions like checkout/setup-python),
    the dependency-install step, and the `lint-guard-summary` aggregator itself
    are excluded here; everything else is a candidate guard. The aggregator
    has no local equivalent to mirror -- it's the report-all mechanism, not a
    policy guard -- so ci-lint's own report-all block (see the `ci-lint`
    target's comment) covers the same job without needing a matching line.
    """
    commands: dict[str, list[str]] = {}
    for step in _load_lint_job_steps():
        name = step.get("name")
        run = step.get("run")
        if not name or not run:
            continue
        if name in SETUP_STEP_NAMES or name == AGGREGATOR_STEP_NAME:
            continue
        lines = [line.strip() for line in run.splitlines() if line.strip()]
        commands[name] = lines
    return commands


def _ci_lint_recipe_text() -> str:
    """Extract the tab-indented recipe body of the `ci-lint:` Makefile target."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line == "ci-lint:":
            start = i + 1
            break
    assert start is not None, "Makefile has no top-level 'ci-lint:' target"

    recipe_lines = []
    for line in lines[start:]:
        if line.startswith("\t"):
            recipe_lines.append(line[1:])
        elif line.strip() == "":
            continue
        else:
            break
    return "\n".join(recipe_lines)


def _normalize_recipe_lines(recipe_text: str) -> list[str]:
    normalized = []
    for line in recipe_text.splitlines():
        stripped = line.strip()
        stripped = stripped.lstrip("@")
        if not stripped or stripped.startswith("#"):
            continue
        # ci-lint runs every guard inside one shell invocation (the whole
        # recipe is a single logical line joined with `\` continuations) so
        # it can collect every guard's exit code instead of `make` aborting
        # at the first failure -- see the report-all comment on the
        # `ci-lint` target. Each guard-command line therefore ends with a
        # `; \` continuation marker that isn't part of the guard command
        # itself, so strip it before comparing.
        if stripped.endswith("\\"):
            stripped = stripped[:-1].rstrip()
        if stripped.endswith(";"):
            stripped = stripped[:-1].rstrip()
        normalized.append(stripped)
    return normalized


def _command_satisfied(command: str, recipe_lines: list[str]) -> bool:
    """Return True if `command` (a single guard shell command) is present in
    the ci-lint recipe at the COMMAND level.

    `make <target>` commands are matched against a `$(MAKE) <target>` or
    `make <target>` recipe line (Makefile convention uses $(MAKE) so
    sub-invocations respect -n/-j, but tolerate a literal `make` too).
    Everything else (uv run ..., sh script.sh, npx ...) must appear
    verbatim as its own recipe line -- this is what prevents a
    same-named-but-different local command from faking parity.
    """
    make_target_match = re.match(r"^make\s+(\S+)$", command)
    if make_target_match:
        target = make_target_match.group(1)
        pattern = re.compile(rf"^(\$\(MAKE\)|make)\s+{re.escape(target)}$")
        return any(pattern.match(line) for line in recipe_lines)
    return command in recipe_lines


def test_lint_job_guards_run_in_ci_lint() -> None:
    """Every non-excluded pr.yml `lint`-job guard command must appear,
    command-for-command, in the `ci-lint` Makefile recipe."""
    guard_commands = _guard_commands()
    recipe_lines = _normalize_recipe_lines(_ci_lint_recipe_text())

    missing: list[str] = []
    for step_name, commands in guard_commands.items():
        if step_name in EXCLUDED_STEPS:
            continue
        for command in commands:
            if not _command_satisfied(command, recipe_lines):
                missing.append(f"{step_name!r}: {command!r}")

    assert not missing, (
        "pr.yml `lint` job guard(s) not mirrored in `make ci-lint` -- these "
        "will fire for the FIRST time in CI instead of locally. Add the "
        "command to the ci-lint recipe in the Makefile (or, if genuinely "
        "CI-only, add it to EXCLUDED_STEPS with a reason):\n  " + "\n  ".join(missing)
    )


def test_non_lint_merge_gate_guards_have_local_equivalent_or_documented_exemption() -> None:
    """Check-shaped merge gates must not be silently CI-only.

    ``code-lint`` keeps its detailed command-by-command assertion above. This
    inventory extends the same policy to the independent PR publication lane
    and release test workflow, where a newly added ``--check``/guard step
    would otherwise bypass the lint-only parity pin.
    """
    missing: list[str] = []
    for workflow_name, workflow_path in MERGE_GATE_WORKFLOWS.items():
        for job_name, step in _workflow_steps(workflow_path):
            if not _is_guard_shaped_step(job_name, step):
                continue
            key = (workflow_name, job_name, str(step.get("name", "")))
            if key in MERGE_GATE_LOCAL_EQUIVALENTS:
                continue
            if key in MERGE_GATE_EXEMPTIONS:
                continue
            missing.append(f"{workflow_name}:{job_name}:{key[2]}")

    assert not missing, (
        "merge-gate guard/check step(s) have neither a local equivalent nor a "
        "documented exemption; add one to MERGE_GATE_LOCAL_EQUIVALENTS or "
        f"MERGE_GATE_EXEMPTIONS: {missing}"
    )


def test_merge_gate_local_equivalents_and_exemptions_are_documented() -> None:
    """Keep the parity inventory fail-closed and its exceptions reviewable."""
    docs = (REPO_ROOT / "docs" / "operations" / "ci-local-parity.md").read_text(encoding="utf-8")
    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "Hosted-only guard inventory" in docs

    for key, target in MERGE_GATE_LOCAL_EQUIVALENTS.items():
        workflow_name, job_name, step_name = key
        if workflow_name == "publication-lane-docs.yml" and step_name == "Verify lane isolation":
            assert target in makefile, f"{key} no longer names a Make target"
        elif target not in makefile and target not in docs:
            raise AssertionError(f"{key} local equivalent {target!r} is not discoverable")

    assert all(reason.strip() for reason in MERGE_GATE_EXEMPTIONS.values())


def test_ci_lint_identity_check_is_gated_rather_than_fed_a_synthetic_identity() -> None:
    """The runner has no Git identity, so the audit is skipped, not faked.

    This test used to pin a ``GIT_CONFIG_COUNT=2 ... / unset ...`` pair that
    injected a synthetic ``BenchBox CI`` identity so the resolved-config audit
    had something to read on a runner. That only ever swapped one input the
    audit cannot fail on for another: a synthetic identity matches no known
    agent either, so the guard passed without verifying anything.

    The guard is now skipped on a runner via the environment gate, and the
    synthetic identity is gone because nothing consumed it. Pinning the old
    text here would have made this test assert recipe content with no
    behaviour behind it - a vacuous pass, which is the exact defect class the
    gate exists to remove.

    ``agent-commit-range-check`` stays unconditional and is the real
    merge-time authorship control; it is asserted separately below.
    """
    recipe = _ci_lint_recipe_text()
    assert "ci_lint_environment_gate.py agent-identity" in recipe, (
        "ci-lint no longer consults the environment gate before agent-identity-check"
    )
    assert "GIT_CONFIG_COUNT" not in recipe, (
        "the synthetic runner identity is back; the audit it fed is skipped on CI, so it feeds nothing"
    )
    # The control that must never be gated.
    assert "ci_lint_environment_gate.py agent-commit-range" not in recipe, (
        "agent-commit-range-check is gated; it is the merge-time authorship control and must always run"
    )
    assert "$(MAKE) agent-commit-range-check" in recipe


def test_excluded_steps_still_exist() -> None:
    """EXCLUDED_STEPS must only reference lint-job steps that still exist,
    under their current name -- otherwise a rename/removal could silently
    leave a stale, unenforced exclusion (or hide that the step's guard is no
    longer excluded/covered at all)."""
    current_step_names = {step.get("name") for step in _load_lint_job_steps()}
    stale = sorted(name for name in EXCLUDED_STEPS if name not in current_step_names)
    assert not stale, (
        "EXCLUDED_STEPS references pr.yml `lint`-job step name(s) that no "
        f"longer exist (renamed or removed) -- update the exclusion: {stale}"
    )


def test_guard_steps_follow_naming_convention() -> None:
    """Every independent guard step in `code-lint` must carry both
    `id: guard-*` and `continue-on-error: true` -- that's what lets the
    `lint-guard-summary` aggregator discover the guard set programmatically
    (see GUARD_ID_PREFIX) instead of a hand-maintained id list that a new
    guard could silently escape. Non-guard steps (checkout/setup-python/
    setup-uv/install-deps, and the aggregator itself) must carry neither."""
    violations: list[str] = []
    for step in _load_lint_job_steps():
        name = step.get("name")
        step_id = step.get("id", "")
        has_run = "run" in step
        is_setup = name in SETUP_STEP_NAMES or "run" not in step
        is_aggregator = name == AGGREGATOR_STEP_NAME
        is_guard = has_run and not is_setup and not is_aggregator

        has_guard_id = step_id.startswith(GUARD_ID_PREFIX)
        has_continue_on_error = step.get("continue-on-error") is True

        if is_guard:
            if not has_guard_id:
                violations.append(f"{name!r}: guard step missing id prefix {GUARD_ID_PREFIX!r}")
            if not has_continue_on_error:
                violations.append(f"{name!r}: guard step missing `continue-on-error: true`")
        else:
            if has_guard_id:
                violations.append(f"{name!r}: non-guard step must not carry a {GUARD_ID_PREFIX!r} id")
            if has_continue_on_error:
                violations.append(f"{name!r}: non-guard step must not carry `continue-on-error: true`")

    assert not violations, (
        "code-lint step(s) violate the guard naming convention (id prefix "
        f"{GUARD_ID_PREFIX!r} + continue-on-error: true for guards, neither "
        "for setup/aggregator steps):\n  " + "\n  ".join(violations)
    )


def test_lint_guard_summary_step_exists() -> None:
    """The report-all aggregator step must exist, be named exactly
    `lint-guard-summary`, and run with `if: always()` so it still executes
    (and reports) after an earlier guard fails with continue-on-error."""
    steps = _load_lint_job_steps()
    matches = [step for step in steps if step.get("name") == AGGREGATOR_STEP_NAME]
    assert matches, f"code-lint job has no {AGGREGATOR_STEP_NAME!r} step"
    assert len(matches) == 1, f"code-lint job has multiple {AGGREGATOR_STEP_NAME!r} steps"

    aggregator = matches[0]
    assert aggregator.get("id") == AGGREGATOR_STEP_NAME, (
        f"{AGGREGATOR_STEP_NAME!r} step must use a matching `id:` (found {aggregator.get('id')!r})"
    )
    assert aggregator.get("if") == "always()", (
        f"{AGGREGATOR_STEP_NAME!r} step must run with `if: always()` so it still reports after an earlier guard fails"
    )
    # Must be the last step -- it aggregates every guard that ran before it.
    assert steps[-1] is aggregator, f"{AGGREGATOR_STEP_NAME!r} must be the last step in the code-lint job"


def test_lint_guard_summary_only_marks_success_as_passing() -> None:
    aggregator = next(step for step in _load_lint_job_steps() if step.get("name") == AGGREGATOR_STEP_NAME)
    run = aggregator["run"]

    assert 'if [ "$outcome" = "success" ]; then' in run
    assert 'echo "FAILED: $id ($outcome)"' in run
    assert "All lint guards passed." in run


def test_delta_baseline_restore_is_keyed_to_the_pr_base_sha() -> None:
    step = next(
        step for step in _load_lint_job_steps() if step.get("name") == "Restore fast-lane develop baseline count"
    )
    cache_key = step["with"]["key"]

    assert (
        cache_key
        == "fast-lane-count-develop-${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}"
    )
    assert "restore-keys" not in step["with"]
