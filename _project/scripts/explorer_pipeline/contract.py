"""Shared contract metadata for explorer-build integrations."""

from __future__ import annotations

EXPLORER_BUILD_CONTRACT_VERSION = "4"
EXPLORER_READ_MODEL_VERSION = 1

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
