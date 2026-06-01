"""Shared submit-classification policy consumed by the CLI and UAT.

Single source of truth for mapping a result (or result-file path) to its
terminal submit state. Both `benchbox submit`
(`benchbox/cli/commands/submit.py`) and the UAT runner (`tests/uat/runner.py`)
consume this module so the two surfaces cannot drift: a divergence here would
let UAT report a different submittability verdict than the CLI enforces.

The policy imports the canonical refused-compliance set from
`benchbox.validation.bundle` rather than re-listing literals, and reuses the
canonical result-status predicates from `benchbox.core.results.status`. It is
side-effect free (no `ctx.exit`, no printing): callers map the returned state to
their own surface (CLI exit code + message vs UAT terminal-state enum).
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from benchbox.core.results.loader import (
    ResultLoadError,
    UnsupportedSchemaError,
    load_result_file,
)
from benchbox.core.results.status import result_failed_query_count, result_non_clean_reason
from benchbox.validation.bundle import CLI_REFUSED_COMPLIANCE_CLASSES


class SubmitTerminalState(str, Enum):
    """Terminal submit verdict shared by the CLI and UAT surfaces."""

    submittable = "submittable"
    unofficial = "unofficial"
    query_failure = "query_failure"
    schema_violation = "schema_violation"
    missing_manifest = "missing_manifest"


def classify_loaded_result(result: Any) -> SubmitTerminalState:
    """Classify an already-loaded result object (no I/O).

    Unofficial TPC-DS compliance classes remain successful but non-submittable;
    non-clean results are refused, splitting query-level failures from other
    schema/integrity problems. Compliance is checked before clean-ness so a
    result that is both unofficial and non-clean classifies as ``unofficial``,
    matching the CLI's branch order.
    """
    if getattr(result, "compliance_class", None) in CLI_REFUSED_COMPLIANCE_CLASSES:
        return SubmitTerminalState.unofficial

    non_clean_reason = result_non_clean_reason(result)
    if non_clean_reason:
        if result_failed_query_count(result):
            return SubmitTerminalState.query_failure
        return SubmitTerminalState.schema_violation
    return SubmitTerminalState.submittable


def classify_result_path(result_json: Path | str | None) -> SubmitTerminalState:
    """Classify a result-file path, including missing-file and load failures.

    A missing path/file is ``missing_manifest``; an unreadable or
    schema-invalid file is ``schema_violation``. A loadable result is then
    routed through :func:`classify_loaded_result`.
    """
    if result_json is None:
        return SubmitTerminalState.missing_manifest
    path = Path(result_json).expanduser()
    if not path.exists():
        return SubmitTerminalState.missing_manifest
    try:
        result, _raw = load_result_file(path)
    except FileNotFoundError:
        return SubmitTerminalState.missing_manifest
    except (json.JSONDecodeError, OSError, ResultLoadError, UnsupportedSchemaError):
        return SubmitTerminalState.schema_violation
    return classify_loaded_result(result)
