"""Shared contract metadata for explorer-build integrations."""

from __future__ import annotations

EXPLORER_BUILD_CONTRACT_VERSION = "6"
# v2: added the results.funding column (result provenance funding disclosure).
# v3: projected funding into platform_index_rows and benchmark_rankings so the
#     card surfaces can render it. A v2 snapshot has the base column but not the
#     projections, and passes a version check that only compares base columns -
#     so the shape of every view the UI reads is what this number tracks, not
#     just the shape of `results`.
# v4: added results.physical_rendering_id (ADR-2 secondary facet). A v3
#     snapshot lacks the column, and duckdbQueries.ts's listResults()/detail
#     projections now select it unconditionally - a v3 snapshot passing this
#     check would hit a DuckDB binder error instead of the intended rebuild
#     message.
# v5: added results.tuning_validation_status (ADR-1 tuning verified-state,
#     surfaced in the RunReceipt). A v4 snapshot lacks the column and the detail
#     projection now selects it unconditionally, so a v4 snapshot would hit a
#     DuckDB binder error instead of the intended rebuild message.
# v6: added results.applied_receipt (ADR-1 per-statement introspection receipt,
#     stored verbatim from the {stem}.applied.json companion and drilled down
#     under the RunReceipt's tuning verified-state row). A v5 snapshot lacks the
#     column and the detail projection now selects it unconditionally, so a v5
#     snapshot would hit a DuckDB binder error instead of the intended rebuild
#     message.
# v7: cohort/ranking identity now derives the canonical benchmark alias
#     (`star_schema` -> `ssb`) and explicit `unknown` phase instead of guessing
#     missing test_type as `power`. Existing snapshots must be rebuilt so their
#     ranking and cohort tables cannot be queried under the new semantics.
EXPLORER_READ_MODEL_VERSION = 7

EXPLORER_BUILD_CONTRACT = {
    "version": EXPLORER_BUILD_CONTRACT_VERSION,
    "read_model_version": EXPLORER_READ_MODEL_VERSION,
    "command": "uv run -- python _project/scripts/explorer_publish.py build",
    "flags": [
        "--data-dir",
        "--output",
        "--trust-label",
        "--visibility",
    ],
    "outputs": {
        "required": [
            "results.duckdb",
            "bundles/{result_id}.json",
        ],
        "removed_legacy": [
            "manifest.json",
            "benchmarks/",
            "details/",
            "compare/",
            "meta_leaderboard.json",
            "short_ids.json",
            "results_schema.json",
        ],
    },
}

__all__ = [
    "EXPLORER_BUILD_CONTRACT",
    "EXPLORER_BUILD_CONTRACT_VERSION",
    "EXPLORER_READ_MODEL_VERSION",
]
