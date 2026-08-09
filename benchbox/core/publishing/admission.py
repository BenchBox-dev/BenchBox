"""Core publish admission policy — the single source of truth for publish refusal.

Moved from ``benchbox.cli.commands.publish`` so any future MCP publish tool
inherits identical policy. The CLI translates the structured decision to its
console messages and exit codes; core stays side-effect free.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benchbox.core.results.status import result_non_clean_reason
from benchbox.validation.bundle import CLI_REFUSED_COMPLIANCE_CLASSES


@dataclass(frozen=True)
class PublishAdmissionDecision:
    """Structured publish admission verdict."""

    allowed: bool
    reason: str | None = None
    # Machine-readable code for the refusal, when not allowed.
    code: str | None = None


def publish_admission(result: Any, label: str) -> PublishAdmissionDecision:
    """Decide whether ``result`` may be published under ``label``.

    Mirrors the CLI guardrails in ``benchbox/cli/commands/publish.py``:

    - Unofficial TPC-DS compliance classes require
      ``label == "unofficial-research"``.
    - Non-clean results (failed queries, failed validation, translation
      fallback) are never publishable.

    Args:
        result: Loaded ``BenchmarkResults``-like object.
        label: Trust/provenance label supplied by the caller.

    Returns:
        Allowed decision or refused decision with a reason and code.
    """
    compliance_class = getattr(result, "compliance_class", None)
    if compliance_class in CLI_REFUSED_COMPLIANCE_CLASSES and label.lower() != "unofficial-research":
        return PublishAdmissionDecision(
            allowed=False,
            code="unofficial_compliance",
            reason=f"compliance_class={compliance_class}",
        )
    non_clean = result_non_clean_reason(result)
    if non_clean:
        return PublishAdmissionDecision(
            allowed=False,
            code="non_clean",
            reason=non_clean,
        )
    return PublishAdmissionDecision(allowed=True)
