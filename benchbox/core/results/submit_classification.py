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
from benchbox.core.results.status import (
    result_failed_query_count,
    result_non_clean_reason,
    result_unvalidated_reason,
)
from benchbox.validation.bundle import CLI_REFUSED_COMPLIANCE_CLASSES


class SubmitTerminalState(str, Enum):
    """Terminal submit verdict shared by the CLI and UAT surfaces.

    ``schema_violation`` is reserved for a *successfully loaded* result that
    fails clean-pass integrity (failed validation claim, translation fallback,
    …). Unreadable or unparseable files use ``bundle_load_error`` so operators
    can distinguish "could not load the artifact" from "loaded but not clean".
    """

    submittable = "submittable"
    unofficial = "unofficial"
    query_failure = "query_failure"
    schema_violation = "schema_violation"
    bundle_load_error = "bundle_load_error"
    unvalidated = "unvalidated"
    missing_manifest = "missing_manifest"


def classify_loaded_result(result: Any) -> SubmitTerminalState:
    """Classify an already-loaded result object (no I/O).

    Unofficial TPC-DS compliance classes remain successful but non-submittable;
    non-clean results are refused, splitting query-level failures, never-
    validated runs, and other schema/integrity problems. Compliance is checked
    before clean-ness so a result that is both unofficial and non-clean
    classifies as ``unofficial``, matching the CLI's branch order.
    """
    if getattr(result, "compliance_class", None) in CLI_REFUSED_COMPLIANCE_CLASSES:
        return SubmitTerminalState.unofficial

    non_clean_reason = result_non_clean_reason(result)
    if non_clean_reason:
        if result_failed_query_count(result):
            return SubmitTerminalState.query_failure
        if result_unvalidated_reason(result):
            return SubmitTerminalState.unvalidated
        return SubmitTerminalState.schema_violation
    return SubmitTerminalState.submittable


def classify_result_path(result_json: Path | str | None) -> SubmitTerminalState:
    """Classify a result-file path, including missing-file and load failures.

    A missing path/file is ``missing_manifest``; an unreadable or unparseable
    file is ``bundle_load_error``. A loadable result is then routed through
    :func:`classify_loaded_result` (which may still return ``schema_violation``
    for integrity problems on a successfully loaded payload).
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
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, ResultLoadError, UnsupportedSchemaError):
        return SubmitTerminalState.bundle_load_error
    return classify_loaded_result(result)
