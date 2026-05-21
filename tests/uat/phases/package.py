"""Package phase: read submit_terminal_state from YAML and dispatch.

Four-word vocabulary (from
`uat-template-success-metric-terminal-state-and-gating`):

  - local-stage:                 invoke `benchbox submit --output ...`
  - cloud-uploaded:              invoke `benchbox submit --service ...`
  - draft-pr:                    open PR vs published-results, NO auto-merge
  - merged-to-published-results: open PR vs published-results, auto-merge

This module dispatches; it does not implement submission. The
`benchbox submit` CLI surface is unchanged (parent TODO must_preserve).
PR-opening modes are stubbed at this work unit (the published-results
flow is owned by `results-explorer-uat-corpus-integrate-validated-bundles`,
which is in DONE) — the dispatcher invokes the CLI and surfaces the
result; it does not duplicate gh-pr machinery.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tests.uat.config import VALID_TERMINAL_STATES, UATConfig
from tests.uat.runner import SubmitTerminalState, classify_for_submit

# Terminal states whose PR-opening flow is not yet implemented; the
# dispatcher emits the same argv as `local-stage` and warns the operator
# so a sweep does not silently produce a local stage when a PR was asked
# for. See module docstring for the four-word vocabulary.
PR_STUB_TERMINAL_STATES: frozenset[str] = frozenset({"draft-pr", "merged-to-published-results"})


@dataclass(frozen=True)
class PackageResult:
    terminal_state: str
    submissions_dir: Path
    invocations: tuple[tuple[str, ...], ...]
    success_count: int
    failure_count: int

    def exit_code(self) -> int:
        return 0 if self.failure_count == 0 else 1


class PackagePhaseError(RuntimeError):
    """Raised when YAML config cannot drive the package phase."""


def _resolve_state(config: UATConfig) -> str:
    state = config.package.submit_terminal_state
    if state is None:
        raise PackagePhaseError("package.submit_terminal_state is required when the package phase is enabled")
    if state not in VALID_TERMINAL_STATES:
        raise PackagePhaseError(f"submit_terminal_state {state!r} not in {sorted(VALID_TERMINAL_STATES)}")
    return state


def _resolve_service(config: UATConfig, state: str) -> str | None:
    service = config.package.service
    if state == "cloud-uploaded" and not service:
        raise PackagePhaseError("submit_terminal_state=cloud-uploaded requires package.service")
    return service


def _build_submit_argv(
    state: str,
    *,
    result_path: Path,
    submissions_dir: Path,
    service: str | None,
) -> list[str]:
    """Build the `benchbox submit ...` argv for a single result file."""
    base = [
        "benchbox",
        "submit",
        str(result_path),
    ]
    if state in ("local-stage", "draft-pr", "merged-to-published-results"):
        return base + ["--output", str(submissions_dir)]
    if state == "cloud-uploaded":
        assert service is not None  # validated above
        return base + ["--service", service]
    raise PackagePhaseError(f"Unhandled terminal state {state!r}")


def run_package(
    config: UATConfig,
    *,
    result_paths: list[Path],
    submissions_dir: Path,
    runner=subprocess.run,
    warn=None,
    classify_results: bool = True,
) -> PackageResult:
    """Dispatch submission per `submit_terminal_state`.

    `runner` is injectable so the fast tests can drive without
    spawning real `benchbox submit` invocations. `warn` defaults to
    printing to stderr; tests inject a callable to capture warnings.
    """
    if warn is None:

        def warn(msg: str) -> None:
            print(msg, file=sys.stderr)

    state = _resolve_state(config)
    service = _resolve_service(config, state)
    if state in PR_STUB_TERMINAL_STATES:
        warn(
            f"[package] WARNING: submit_terminal_state={state!r} is a stub — "
            "this run will produce a local stage at "
            f"{submissions_dir}; PR-opening to published-results is not yet "
            "implemented. See _project/specs/uat-framework.md."
        )
    submissions_dir.mkdir(parents=True, exist_ok=True)

    invocations: list[tuple[str, ...]] = []
    success = 0
    failure = 0
    for result_path in result_paths:
        if classify_results and result_path.exists():
            submit_state = classify_for_submit(result_path)
            if submit_state is SubmitTerminalState.unofficial:
                warn(f"[package] skipping unofficial result {result_path}: submit_terminal_state=unofficial")
                continue
            if submit_state is not SubmitTerminalState.submittable:
                warn(
                    f"[package] refusing unsubmittable result {result_path}: submit_terminal_state={submit_state.value}"
                )
                failure += 1
                continue
        argv = _build_submit_argv(
            state,
            result_path=result_path,
            submissions_dir=submissions_dir,
            service=service,
        )
        invocations.append(tuple(argv))
        completed = runner(argv, check=False)
        if getattr(completed, "returncode", 0) == 0:
            success += 1
        else:
            failure += 1

    return PackageResult(
        terminal_state=state,
        submissions_dir=submissions_dir,
        invocations=tuple(invocations),
        success_count=success,
        failure_count=failure,
    )
