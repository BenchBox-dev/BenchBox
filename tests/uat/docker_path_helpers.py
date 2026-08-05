"""Separator-neutral path assertions for managed-Docker tests."""

from __future__ import annotations

import re
from pathlib import Path, PurePath, PureWindowsPath

# mocker's compose parser does not resolve a default value that itself
# contains another ${...} substitution (e.g. ${VAR:-${PWD}/x}): it leaves a
# stray brace and a doubled path instead of the intended default. Compose
# files must use a flat default or the required form (${VAR:?message}).
_NESTED_VARIABLE_DEFAULT_RE = re.compile(r"\$\{[^}]*\$\{")


def compose_path_ends_with(path: str | PurePath, *expected_parts: str) -> bool:
    """Return whether a compose path ends with the expected path components."""
    actual_parts = PureWindowsPath(path).parts
    if len(actual_parts) < len(expected_parts):
        return False
    return actual_parts[-len(expected_parts) :] == expected_parts


def find_nested_variable_defaults(compose_root: str | Path) -> list[Path]:
    """Return every ``docker-compose*.yml`` under ``compose_root`` that nests
    a ``${...}`` substitution inside another variable's default value.

    mocker misparses the nested form, so it must never reappear in a
    committed compose file: see lakesail-compose-nested-variable-default.
    """
    root = Path(compose_root)
    return sorted(p for p in root.rglob("docker-compose*.yml") if _NESTED_VARIABLE_DEFAULT_RE.search(p.read_text()))
