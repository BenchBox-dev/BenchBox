"""Separator-neutral path assertions for managed-Docker tests."""

from __future__ import annotations

from pathlib import PurePath, PureWindowsPath


def compose_path_ends_with(path: str | PurePath, *expected_parts: str) -> bool:
    """Return whether a compose path ends with the expected path components."""
    actual_parts = PureWindowsPath(path).parts
    if len(actual_parts) < len(expected_parts):
        return False
    return actual_parts[-len(expected_parts) :] == expected_parts
