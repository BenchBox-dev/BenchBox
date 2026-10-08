#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchbox.core.equivalence import cross_surface
from benchbox.core.equivalence.cross_surface import CrossSurfaceGate

_RESOLVED_RE = re.compile(r"GATE FAILURE - previously-known divergences now equivalent: (\[[^\]]*\])")
_REMOVED_RE = re.compile(r": removed resolved known-divergence baseline entries: (\[[^\]]*\])")
_CODE_ONLY_RE = re.compile(r": resolved entries (\[[^\]]*\]) are code-only \(ClassifiedDivergence\)")
_REFUSED_MARKER = ": refusing to update baseline - gate reported other failure(s) above; nothing written."


CLI_DESCRIPTION = (
    "Detect + prune RESOLVED cross-surface known-divergence baseline entries.\n"
    "\n"
    "Supporting glue for the scheduled workflow\n"
    "``.github/workflows/cross-surface-baseline-autodetect.yml``. #903 made every\n"
    "enforced cross-surface gate (``benchbox/core/equivalence/cross_surface.py``\n"
    "``GATES``) FAIL a normal (blocking) run when a ``known_divergences`` baseline\n"
    'entry stops reproducing -- printing "GATE FAILURE - previously-known\n'
    'divergences now equivalent: [...]" and telling the operator to prune it in a\n'
    "reviewed change. #935 built the ``--update-baseline`` writer\n"
    "(``make cross-surface-update-baseline BENCHMARK=<gate>``) that does the actual\n"
    "prune, but running it has stayed a fully manual step.\n"
    "\n"
    "This module automates NOTICING that condition across every enforced gate and\n"
    "invoking the existing writer, but reimplements neither:\n"
    "\n"
    "* Detection (:func:`detect_and_prune`, phase 1) runs the EXACT SAME call the\n"
    "  blocking CI gate makes -- ``run_gate(gate, update_baseline=False)`` -- and\n"
    "  READS the resolved-key list out of its own printed report (the very message\n"
    "  quoted above). It never recomputes resolved-ness itself, and since\n"
    "  ``update_baseline`` is False this call is byte-for-byte the blocking gate's\n"
    "  own code path, so by construction it cannot write anything.\n"
    "* Pruning (phase 2) runs ONLY when phase 1's report names at least one\n"
    "  resolved key, and invokes ``run_gate(gate, update_baseline=True)`` -- the\n"
    "  EXACT call ``--update-baseline``/``make cross-surface-update-baseline``\n"
    "  makes. That call already refuses to write anything unless the run is\n"
    "  otherwise completely clean (see ``_apply_baseline_update``'s docstring), so\n"
    "  a still-reproducing divergence elsewhere on the same gate blocks the prune\n"
    "  entirely; this module adds no separate safety logic of its own here either.\n"
    "\n"
    "The upshot: the blocking gate run (``ci.yml``'s ``correctness-gate`` job,\n"
    "``make <gate>-cross-surface-equivalence-report``) is completely unmodified and\n"
    "never prunes. Only THIS script, run by the scheduled workflow, ever calls\n"
    "``run_gate(..., update_baseline=True)``.\n"
)


def _extract_list(pattern: re.Pattern[str], text: str) -> list[str]:
    match = pattern.search(text)
    if match is None:
        return []
    parsed = ast.literal_eval(match.group(1))
    return [str(item) for item in parsed]


@dataclass(frozen=True)
class GatePruneOutcome:
    gate: str
    detect_exit_code: int
    resolved_detected: list[str]
    prune_ran: bool
    prune_exit_code: int | None
    pruned: list[str]
    code_only: list[str]
    refused: bool
    report: str

    @property
    def needs_attention(self) -> bool:
        return self.refused or bool(self.code_only)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "detect_exit_code": self.detect_exit_code,
            "resolved_detected": self.resolved_detected,
            "prune_ran": self.prune_ran,
            "prune_exit_code": self.prune_exit_code,
            "pruned": self.pruned,
            "code_only": self.code_only,
            "refused": self.refused,
            "needs_attention": self.needs_attention,
        }


def detect_and_prune(gate: CrossSurfaceGate) -> GatePruneOutcome:
    detect_buf = io.StringIO()
    with contextlib.redirect_stdout(detect_buf):
        detect_exit_code = cross_surface.run_gate(gate, update_baseline=False)
    detect_report = detect_buf.getvalue()
    resolved_detected = _extract_list(_RESOLVED_RE, detect_report)

    if not resolved_detected:
        return GatePruneOutcome(
            gate=gate.name,
            detect_exit_code=detect_exit_code,
            resolved_detected=[],
            prune_ran=False,
            prune_exit_code=None,
            pruned=[],
            code_only=[],
            refused=False,
            report=detect_report,
        )

    prune_buf = io.StringIO()
    with contextlib.redirect_stdout(prune_buf):
        prune_exit_code = cross_surface.run_gate(gate, update_baseline=True)
    prune_report = prune_buf.getvalue()

    return GatePruneOutcome(
        gate=gate.name,
        detect_exit_code=detect_exit_code,
        resolved_detected=resolved_detected,
        prune_ran=True,
        prune_exit_code=prune_exit_code,
        pruned=_extract_list(_REMOVED_RE, prune_report),
        code_only=_extract_list(_CODE_ONLY_RE, prune_report),
        refused=_REFUSED_MARKER in prune_report,
        report=detect_report + prune_report,
    )


def detect_and_prune_gate(gate_name: str) -> GatePruneOutcome:
    return detect_and_prune(cross_surface.get_gate(gate_name))


def run_autodetect(gate_names: Iterable[str] | None = None) -> list[GatePruneOutcome]:
    names = sorted(gate_names) if gate_names is not None else sorted(cross_surface.GATES)
    return [detect_and_prune_gate(name) for name in names]


def summarize(outcomes: Sequence[GatePruneOutcome]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gates": {outcome.gate: outcome.as_dict() for outcome in outcomes},
        "any_pruned": any(outcome.pruned for outcome in outcomes),
        "needs_attention": sorted(outcome.gate for outcome in outcomes if outcome.needs_attention),
    }


def _print_report(outcomes: Sequence[GatePruneOutcome]) -> None:
    for outcome in outcomes:
        if outcome.pruned:
            print(f"{outcome.gate}: pruned resolved baseline entries {outcome.pruned}")
        elif outcome.resolved_detected:
            print(
                f"{outcome.gate}: detected resolved entries {outcome.resolved_detected} but the writer "
                "did not fully prune them - see NEEDS ATTENTION below"
            )
        else:
            print(f"{outcome.gate}: no resolved baseline entries (no-op)")
        if outcome.needs_attention:
            print(f"  NEEDS ATTENTION: code_only={outcome.code_only} refused={outcome.refused}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    parser.add_argument(
        "--gates",
        help="Comma-separated enforced gate names to check (default: every gate in GATES).",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Write a machine-readable summary JSON to this path.",
    )
    args = parser.parse_args(argv)

    gate_names = [name.strip() for name in args.gates.split(",") if name.strip()] if args.gates else None
    outcomes = run_autodetect(gate_names)
    _print_report(outcomes)

    summary = summarize(outcomes)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    if summary["needs_attention"]:
        print(f"::warning::cross-surface baseline autodetect needs manual attention for: {summary['needs_attention']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
