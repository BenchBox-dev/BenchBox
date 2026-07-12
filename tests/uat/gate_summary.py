"""Gate summary artifact: `uat_gate_summary.json`.

Versioned, machine-readable per-sweep summary written beside `cells.jsonl` at
the end of every sweep run through `tests.uat.orchestrator.run_sweep`
(including dry-run sweeps, whose `verdict` is `"dry_run"` rather than
`"green"`/`"red"` so a dry-run e2e check has something concrete to assert
against without being misread as a real release-gate result).

This is one summary per *stage* (one `make uat-sweep` invocation). The
release-gate contract runs three stages; `make uat-gate-check`
(`_cli.py`'s `gate-check` subcommand) aggregates all three stage summaries
into the combined, committed release-evidence file that
`scripts/release_readiness_check.py` reads -- see
`build_combined_evidence` below.

Schema is additive-versioned (`version: 1`): existing field names never
change meaning, and `read_gate_summary`/`read_combined_evidence` ignore
unknown keys, so a later summary with new fields never breaks an older
checker -- see the "keystone" TODO's `approach` note. Downstream consumers
(notably `scripts/release_readiness_check.py`) rely on that additive
contract rather than validating `version` explicitly; bump the version
constant only alongside a consumer that branches on it.

Per-stage verdict derivation is deliberately narrow: it reduces to "did any
phase this sweep ran end non-zero" (`derive_verdict`). Every phase already
folds its own floor/accounting checks into its own `exit_code()` (the
validate and report phases' floor breaches, in particular), so re-deriving
those checks here would duplicate logic that can drift. The two checklist
items that do NOT show up in any phase's exit code -- an accounting sidecar
missing (`unreachable_is_estimated`) and explorer_smoke silently skipping
(non-fatal by design) -- are captured as raw fields on the summary instead,
and are enforced by `build_combined_evidence` at aggregation time, not by
this module's verdict.
"""

from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from tests.uat.phases.report import atomic_write_text

GATE_SUMMARY_SCHEMA_VERSION = 1
COMBINED_EVIDENCE_SCHEMA_VERSION = 1

GATE_SUMMARY_FILENAME = "uat_gate_summary.json"

VERDICT_GREEN = "green"
VERDICT_RED = "red"
VERDICT_DRY_RUN = "dry_run"

EXPLORER_SMOKE_NOT_RUN = "not_run"
EXPLORER_SMOKE_RAN = "ran"

# The exact stage set (config `name:` fields) release evidence must be built
# from -- tests/uat/configs/release-gate-0{1,2,3}-*.yaml. Aggregation reasons
# on any mismatch, which kills both the pass-the-same-run-dir-three-times
# footgun and substituting a hollow ad-hoc config for a real stage.
EXPECTED_RELEASE_GATE_STAGES = (
    "release-gate-01-native-dataframe",
    "release-gate-02-docker-nonoltp",
    "release-gate-03-docker-oltp",
)


def gate_summary_path(log_dir: Path) -> Path:
    """The one filename convention writer and reader share -- mirrors `cells_accounting_path`."""
    return log_dir / GATE_SUMMARY_FILENAME


@dataclass(frozen=True)
class PhaseAccounting:
    """Per-sweep cell counts, disjoint components mirroring the report-phase footer."""

    attempted: int = 0
    passed: int = 0
    failed: int = 0
    timed_out: int = 0
    unreachable: int = 0
    startup_failed: int = 0
    skipped: int = 0
    compatibility_pruned: int = 0
    early_stop_pruned: int = 0
    registry_pruned: int = 0
    total_defined: int = 0


@dataclass(frozen=True)
class GateSummary:
    """One stage's machine-readable release-gate evidence."""

    config_name: str
    source_commit_sha: str
    source_dirty: bool
    container_engine: str | None
    completed_at: str  # ISO 8601, tests.uat.orchestrator._dt.datetime.now().isoformat()
    dry_run: bool
    aborted: bool
    abort_phase: str | None
    abort_reason: str | None
    phase_exit_codes: dict[str, int]
    accounting: PhaseAccounting
    unreachable_is_estimated: bool
    validator_clean_rate: float | None
    validator_clean_rate_floor: float | None
    validator_floor_breached: bool | None
    cross_scale_clean_pairs: int | None
    cross_scale_floor: int | None
    cross_scale_floor_breached: bool | None
    explorer_smoke_status: str
    verdict: str
    version: int = GATE_SUMMARY_SCHEMA_VERSION

    def to_json_dict(self) -> dict:
        return asdict(self)


def derive_verdict(*, dry_run: bool, aborted: bool, phase_exit_codes: dict[str, int]) -> str:
    """Derive the single green|red|dry_run verdict for one stage's sweep.

    Deliberately does not re-check floor breaches or per-status counts
    directly: the validate and report phases already fold those into their
    own `exit_code()` (see `tests.uat.phases.report.ReportSummary.exit_code`
    and `tests.uat.phases.validate.ValidateResult.exit_code`), so a nonzero
    entry anywhere in `phase_exit_codes` already means "this phase was not
    clean," whatever the reason.
    """
    if dry_run:
        return VERDICT_DRY_RUN
    if aborted:
        return VERDICT_RED
    if any(code != 0 for code in phase_exit_codes.values()):
        return VERDICT_RED
    return VERDICT_GREEN


def write_gate_summary(log_dir: Path, summary: GateSummary) -> Path:
    path = gate_summary_path(log_dir)
    atomic_write_text(path, json.dumps(summary.to_json_dict(), indent=2, sort_keys=True) + "\n")
    return path


def _dataclass_from_payload(cls: type, payload: dict) -> object:
    """Build `cls` from `payload`, silently dropping unknown keys (forward compat)."""
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in payload.items() if k in known})


def read_gate_summary(path: Path) -> GateSummary:
    payload = json.loads(path.read_text(encoding="utf-8"))
    accounting_payload = payload.get("accounting") or {}
    accounting = _dataclass_from_payload(PhaseAccounting, accounting_payload)
    payload = dict(payload)
    payload["accounting"] = accounting
    known = {f.name for f in fields(GateSummary)}
    return GateSummary(**{k: v for k, v in payload.items() if k in known})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Combined release-gate evidence: aggregates the 3 release-gate stage
# summaries into the one file the operator commits to
# `_project/release-evidence/uat-gate-summary.json` -- see `make
# uat-gate-check` / `_cli.py`'s `gate-check` subcommand, which owns the file
# I/O (reading each stage's uat_lifecycle.log for the ordering check); this
# module stays pure/testable.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CombinedGateEvidence:
    verdict: str
    source_commit_sha: str
    source_dirty: bool
    completed_at: str | None
    generated_at: str
    stage_names: tuple[str, ...]
    stage_verdicts: dict[str, str]
    ordering_violations: tuple[str, ...]
    reasons: tuple[str, ...]
    version: int = COMBINED_EVIDENCE_SCHEMA_VERSION

    def to_json_dict(self) -> dict:
        return asdict(self)


def build_combined_evidence(
    stage_summaries: Sequence[GateSummary],
    *,
    ordering_violations: Sequence[str],
    generated_at: _dt.datetime,
) -> CombinedGateEvidence:
    """Aggregate 3 stage `GateSummary` records into one release-evidence verdict.

    Mechanized APPROVE checklist (docs/operations/uat-framework.md
    "APPROVE / HOLD gate"): every stage's own verdict is green, every
    stage's accounting sidecar was present (not estimated), and
    explorer_smoke actually ran for every stage whose `phases:` list
    included it (`"explorer_smoke" in phase_exit_codes` is the same
    membership test the orchestrator's own phase loop uses -- a phase not
    reached because of an earlier abort never gets a `phase_exit_codes`
    entry, so it correctly does not trigger this check).
    """
    reasons: list[str] = []
    if len(stage_summaries) != 3:
        reasons.append(f"expected 3 release-gate stage summaries, got {len(stage_summaries)}")

    # Defense-in-depth against honest operator error: the three summaries
    # must be the three distinct release-gate stage configs, in order --
    # not the same run dir passed thrice, and not an ad-hoc config standing
    # in for a real stage.
    actual_stage_names = tuple(s.config_name for s in stage_summaries)
    if actual_stage_names != EXPECTED_RELEASE_GATE_STAGES:
        reasons.append(
            f"stage config names {list(actual_stage_names)} do not match the expected "
            f"release-gate stage set {list(EXPECTED_RELEASE_GATE_STAGES)}"
        )

    shas = {s.source_commit_sha for s in stage_summaries}
    source_commit_sha = next(iter(shas)) if len(shas) == 1 else ""
    if len(shas) > 1:
        reasons.append(f"source_commit_sha differs across stages: {sorted(shas)}")

    source_dirty = any(s.source_dirty for s in stage_summaries)
    if source_dirty:
        reasons.append("one or more stages captured a dirty source tree (source_dirty=true)")

    for stage in stage_summaries:
        if stage.dry_run:
            reasons.append(f"stage {stage.config_name!r} is a dry-run summary, not real evidence")
        if stage.verdict != VERDICT_GREEN:
            reasons.append(f"stage {stage.config_name!r} verdict is {stage.verdict!r}, not green")
        if stage.unreachable_is_estimated:
            reasons.append(f"stage {stage.config_name!r} accounting sidecar missing (unreachable_is_estimated=true)")
        if "explorer_smoke" in stage.phase_exit_codes and stage.explorer_smoke_status != EXPLORER_SMOKE_RAN:
            reasons.append(
                f"stage {stage.config_name!r} configured explorer_smoke but it did not run "
                f"(explorer_smoke_status={stage.explorer_smoke_status!r})"
            )
        if stage.validator_clean_rate_floor is None or stage.cross_scale_floor is None:
            reasons.append(f"stage {stage.config_name!r} floor gates were not configured")

    if ordering_violations:
        reasons.extend(ordering_violations)

    completed_at_values = sorted(s.completed_at for s in stage_summaries if s.completed_at)
    completed_at = completed_at_values[0] if completed_at_values else None

    verdict = VERDICT_GREEN if not reasons else VERDICT_RED

    return CombinedGateEvidence(
        verdict=verdict,
        source_commit_sha=source_commit_sha,
        source_dirty=source_dirty,
        completed_at=completed_at,
        generated_at=generated_at.isoformat(),
        stage_names=tuple(s.config_name for s in stage_summaries),
        stage_verdicts={s.config_name: s.verdict for s in stage_summaries},
        ordering_violations=tuple(ordering_violations),
        reasons=tuple(reasons),
    )


def write_combined_evidence(path: Path, evidence: CombinedGateEvidence) -> Path:
    atomic_write_text(path, json.dumps(evidence.to_json_dict(), indent=2, sort_keys=True) + "\n")
    return path


def read_combined_evidence(path: Path) -> CombinedGateEvidence:
    payload = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(CombinedGateEvidence)}
    return CombinedGateEvidence(**{k: v for k, v in payload.items() if k in known})
