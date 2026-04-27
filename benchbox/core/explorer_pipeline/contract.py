"""Shared contract metadata for explorer-build integrations."""

from __future__ import annotations

EXPLORER_BUILD_CONTRACT_VERSION = "1"

EXPLORER_BUILD_CONTRACT = {
    "version": EXPLORER_BUILD_CONTRACT_VERSION,
    "command": "benchbox explorer build",
    "flags": [
        "--data-dir",
        "--output",
        "--trust-label",
        "--visibility",
    ],
}

__all__ = [
    "EXPLORER_BUILD_CONTRACT",
    "EXPLORER_BUILD_CONTRACT_VERSION",
]
