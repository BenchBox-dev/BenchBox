"""LakeSail execution-filter rules for unsupported TPC-DI validation queries."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

LAKESAIL_TPCDI_SKIPS: dict[str, str] = {
    "V1": "Sail cannot infer a common comparison argument type for this TPC-DI validation query.",
    "V2": "Sail cannot infer a common comparison argument type for this TPC-DI validation query.",
    "A1": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "A2": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "A3": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "A5": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "VQ3": "Sail cannot infer a common comparison argument type for this TPC-DI validation query.",
    "VQ4": "Sail cannot infer a common comparison argument type for this TPC-DI validation query.",
    "VQ6": "Sail cannot infer a common comparison argument type for this TPC-DI validation query.",
    "VQ7": "Sail cannot infer a common comparison argument type for this TPC-DI validation query.",
    "VQ8": "Sail cannot infer a common comparison argument type for this TPC-DI validation query.",
    "VQ10": "Sail cannot infer a common comparison argument type for this TPC-DI validation query.",
    "VQ12": "Sail cannot infer a common comparison argument type for this TPC-DI validation query.",
    "AQ1": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "AQ2": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "AQ3": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "AQ4": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "AQ5": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "AQ6": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "AQ7": "Sail lacks the `JULIANDAY` function used by this TPC-DI analytical query.",
    "AQ8": "Sail lacks the `JULIANDAY` function used by this TPC-DI analytical query.",
    "AQ9": "Sail cannot infer a common comparison argument type for this TPC-DI analytical query.",
    "AQ10": "Sail lacks the `JULIANDAY` function used by this TPC-DI analytical query.",
    "EQ4": "Sail cannot infer a common comparison argument type for this TPC-DI ETL query.",
    "EQ5": "Sail cannot infer a common comparison argument type for this TPC-DI ETL query.",
    "EQ7": "Sail cannot resolve sibling derived-table score aliases in this TPC-DI ETL query.",
}

for _query_id, _reason in LAKESAIL_TPCDI_SKIPS.items():
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"execution_filter.lakesail.tpcdi.{_query_id.lower()}",
            action=CompatAction.SKIP_QUERY,
            support_level=SupportLevel.SKIPPED_QUERY,
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=SkipQueryPayload(
                reason=(
                    f"{_reason} Evidence: focused LakeSail UAT sweep "
                    "`uat_lakesail_failing_benchmarks_20260513` loaded TPC-DI and reported this query in the "
                    "stable 26-query failure set while 12 sibling queries passed."
                ),
                query_id=_query_id,
            ),
            reason=_reason,
        ),
        Phase.EXECUTION_FILTER,
        "lakesail",
        benchmark="tpcdi",
        query_id=_query_id,
    )
