"""`make ci-lint` must not confuse "runs on CI" with "means something on CI".

`develop-post-merge.yml` runs `make ci-lint` directly on a real, ephemeral
GitHub-hosted runner (not as a local-parity convenience -- as a blocking gate
wired into `auto-revert-on-failure`). Two of its ~23 guards read state that
only exists on a developer machine and used to handle that badly:
`agent-identity-check` resolves a Git identity the runner does not have (a
noisy, environment-caused failure before #1558), and `skill-sync-check`
shells out to a hardcoded local absolute path that plainly does not exist on
a runner (a *silent* no-op that exits 0 and reads as coverage in the Actions
log while checking nothing -- the more dangerous failure mode, because nobody
investigates a green check).

`_project/scripts/ci_lint_environment_gate.py` is the fix: one declarative
table of guards that cannot produce a meaningful result on
`GITHUB_ACTIONS=true`, consulted by the `ci-lint` recipe before each listed
guard, replacing the ad hoc per-guard `if $GITHUB_ACTIONS` special case.

Every test below is chosen to fail for a specific wrong "fix", not just to
exercise the happy path:

* `..._never_gates_the_commit_range_control` and
  `..._leaves_real_guards_unconditional` fail if the exception table (or the
  Makefile wiring) is widened past the two documented guards -- the
  "disable everything on CI" cheat that would satisfy a shallower test
  asserting only "ci-lint exits 0 on a runner".
* `..._gates_agent_identity_check_on_a_runner` and
  `..._gates_skill_sync_check_on_a_runner` parse the actual `ci-lint` recipe
  text and fail if the gate script exists and classifies correctly but was
  never wired into the Makefile -- the specific way a "fix" could add a
  correct-looking module that changes nothing about what `make ci-lint`
  actually runs.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = REPO_ROOT / "Makefile"
GATE_SCRIPT = REPO_ROOT / "_project" / "scripts" / "ci_lint_environment_gate.py"
GATE_INVOCATION = "_project/scripts/ci_lint_environment_gate.py"

# Guards that stay unconditional on CI: a representative sample spanning
# every invocation shape `ci-lint` uses (bare `uv run ...`, `$(MAKE) <target>`
# with and without a `-check` suffix on its failure tag), plus the one guard
# the task explicitly forbids ever gating. If a "fix" widened the exception
# table to cover any of these -- even accidentally, e.g. by keying the table
# on a prefix instead of an exact slug -- real CI coverage would shrink and
# these assertions catch it.
ALWAYS_ON_GUARDS = (
    "ruff-check",
    "ruff-format",
    "ty-check",
    "artifact-hygiene",
    "agent-instructions",
    "audit-deps",
    "spellcheck",
    "agent-commit-range",
)


def _load_gate():
    spec = importlib.util.spec_from_file_location("ci_lint_environment_gate_under_test", GATE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ci_lint_recipe_text() -> str:
    """Tab-indented recipe body of the `ci-lint:` Makefile target."""
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(r"^ci-lint:.*?\n((?:\t.*\n|\n)*)", text, re.MULTILINE)
    assert match, "Makefile has no top-level 'ci-lint:' target"
    return match.group(1)


class TestClassificationTable:
    """The gate's own decision function, independent of how the Makefile calls it."""

    def test_ci_lint_environment_boundary_skips_agent_identity_on_a_runner(self) -> None:
        gate = _load_gate()
        should_run, reason = gate.runs_on_runner("agent-identity", github_actions=True)
        assert should_run is False
        assert reason, "a skipped guard must carry a printable reason, not a silent False"

    def test_ci_lint_environment_boundary_skips_skill_sync_check_on_a_runner(self) -> None:
        gate = _load_gate()
        should_run, reason = gate.runs_on_runner("skill-sync-check", github_actions=True)
        assert should_run is False
        assert reason, "a skipped guard must carry a printable reason, not a silent False"

    def test_ci_lint_environment_boundary_never_gates_the_commit_range_control(self) -> None:
        """agent-commit-range-check is the real merge-time authorship control
        (it reads the commits a branch actually carries, not resolved
        config) -- it must run unconditionally everywhere, including CI.
        A table that ever returns False for it is the actual coverage
        regression the task's constraints forbid, not a hardening."""
        gate = _load_gate()
        for github_actions in (True, False):
            should_run, reason = gate.runs_on_runner("agent-commit-range", github_actions=github_actions)
            assert should_run is True
            assert reason is None

    def test_ci_lint_environment_boundary_leaves_real_guards_unconditional(self) -> None:
        """A guard not in the documented exception table must run on CI
        exactly as it does locally -- this is what stops the mechanism from
        becoming a generic on/off switch instead of a narrow, reasoned
        allowlist."""
        gate = _load_gate()
        for slug in ALWAYS_ON_GUARDS:
            should_run, reason = gate.runs_on_runner(slug, github_actions=True)
            assert should_run is True, f"{slug!r} must stay unconditional on a CI runner"
            assert reason is None

    def test_ci_lint_environment_boundary_only_narrows_ci_never_local(self) -> None:
        """`github_actions=False` (local dev, `pr-preflight`, CI-local-parity
        runs) must be unaffected by the table -- including for the two
        guards it DOES skip on a runner. A fix that also skipped them
        locally would silently drop local pre-push coverage no one asked
        for."""
        gate = _load_gate()
        for slug in ("agent-identity", "skill-sync-check", *ALWAYS_ON_GUARDS):
            should_run, reason = gate.runs_on_runner(slug, github_actions=False)
            assert should_run is True, f"{slug!r} must run locally regardless of the CI exception table"
            assert reason is None


class TestGateCli:
    """The actual command line `ci-lint` invokes (`uv run -- python ... <slug>`)."""

    def test_ci_lint_environment_boundary_cli_skips_on_a_runner(self, monkeypatch, capsys) -> None:
        gate = _load_gate()
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert gate.main(["agent-identity"]) == 1
        out = capsys.readouterr().out
        assert "SKIP agent-identity" in out

    def test_ci_lint_environment_boundary_cli_runs_off_a_runner(self, monkeypatch, capsys) -> None:
        gate = _load_gate()
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        assert gate.main(["agent-identity"]) == 0
        assert capsys.readouterr().out == ""

    def test_ci_lint_environment_boundary_cli_ignores_non_true_values(self, monkeypatch) -> None:
        """GitHub Actions itself only ever sets the literal string `true`;
        a stray/falsy value (unset, empty, `false`) must never trip the
        skip path -- otherwise a locally-exported `GITHUB_ACTIONS=1` for
        some unrelated tool would silently start skipping real guards."""
        gate = _load_gate()
        for value in ("false", "", "1", "True"):
            monkeypatch.setenv("GITHUB_ACTIONS", value)
            assert gate.main(["agent-identity"]) == 0


class TestMakefileWiring:
    """Does `ci-lint` actually CALL the gate, not just define it?

    A module with correct classification logic that the Makefile never
    invokes changes nothing about what `make ci-lint` runs on a real
    runner -- these assertions parse the recipe text itself so that specific
    half-fix cannot pass.
    """

    def test_ci_lint_environment_boundary_gates_agent_identity_check_on_a_runner(self) -> None:
        body = _ci_lint_recipe_text()
        gate_call = f"{GATE_INVOCATION} agent-identity"
        assert gate_call in body, "ci-lint does not consult the environment gate before agent-identity-check"
        gate_index = body.index(gate_call)
        guard_index = body.index("$(MAKE) agent-identity-check")
        assert gate_index < guard_index, "the gate must run BEFORE agent-identity-check, not after or not at all"

    def test_ci_lint_environment_boundary_gates_skill_sync_check_on_a_runner(self) -> None:
        body = _ci_lint_recipe_text()
        gate_call = f"{GATE_INVOCATION} skill-sync-check"
        assert gate_call in body, "ci-lint does not consult the environment gate before skill-sync-check"
        gate_index = body.index(gate_call)
        guard_index = body.index("$(MAKE) skill-sync-check")
        assert gate_index < guard_index, "the gate must run BEFORE skill-sync-check, not after or not at all"

    def test_ci_lint_environment_boundary_never_gates_commit_range_in_the_makefile(self) -> None:
        body = _ci_lint_recipe_text()
        assert f"{GATE_INVOCATION} agent-commit-range" not in body, (
            "agent-commit-range-check must never be routed through the environment gate -- "
            "it is the merge-time authorship control and stays unconditional"
        )

    def test_ci_lint_environment_boundary_leaves_real_guard_commands_unconditional(self) -> None:
        """Spot-check that ordinary guard invocations are still bare
        recipe lines, not newly nested under a gate `if`/`fi` -- catches a
        fix that widened gating past the two documented exceptions by
        editing the wrong lines."""
        body = _ci_lint_recipe_text()
        for command in (
            "uv run ruff check .",
            "uv run ruff format --check .",
            "uv run ty check",
            "$(MAKE) artifact-hygiene",
            "$(MAKE) agent-instructions-check",
            "$(MAKE) agent-commit-range-check",
            "$(MAKE) audit-deps",
            "$(MAKE) spellcheck",
        ):
            assert command in body, f"expected guard command {command!r} missing from ci-lint recipe"

    def test_ci_lint_environment_boundary_uses_one_general_mechanism(self) -> None:
        """The fix this test pins replaced the old per-member
        `if [ "$GITHUB_ACTIONS" = "true" ]` special case with a single
        script consulted uniformly. Both gated guards must route through
        the SAME script (not two separate ad hoc mechanisms), which is
        what makes adding a third gated guard later a one-line table entry
        instead of another copy-pasted shell conditional."""
        body = _ci_lint_recipe_text()
        assert body.count(GATE_INVOCATION) == 2, (
            f"expected exactly 2 calls into {GATE_INVOCATION} (agent-identity, skill-sync-check); "
            "a differing count means the general mechanism was abandoned for a per-member one-off, "
            "or a guard was gated that should not be"
        )
