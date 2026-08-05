"""Separator-neutral path assertions for managed-Docker tests."""

from __future__ import annotations

import re
from pathlib import Path, PurePath, PureWindowsPath

# mocker 0.7.2 does not resolve a default value that itself contains another
# substitution, whether braced (${VAR:-${PWD}/x}) or bare (${VAR:-$PWD/x}):
# it leaves the expression unresolved instead of interpolating it, and a
# volume/path field built from that gets colon-split into garbage. mocker
# also has NO ${VAR:?message} "required variable" support -- it leaves that
# form unresolved too (silently, even when the variable IS set), so it is
# not a safe substitute either. Only a flat ${VAR} or ${VAR:-default} (no
# further ${...}/$VAR inside the default) resolves correctly; see
# lakesail-compose-nested-variable-default and docker/lakesail/docker-compose.yml.
_NESTED_VARIABLE_DEFAULT_RE = re.compile(r"\$\{[^}]*\$(?:\{|[A-Za-z_])")

# docker/postgres-extensions declares per-extension stacks as
# docker-compose.<extension>.yaml (note: .yaml, not .yml).
_COMPOSE_FILE_GLOBS = ("docker-compose*.yml", "docker-compose*.yaml")


def compose_path_ends_with(path: str | PurePath, *expected_parts: str) -> bool:
    """Return whether a compose path ends with the expected path components."""
    actual_parts = PureWindowsPath(path).parts
    if len(actual_parts) < len(expected_parts):
        return False
    return actual_parts[-len(expected_parts) :] == expected_parts


def find_nested_variable_defaults(compose_root: str | Path) -> list[Path]:
    """Return every compose file under ``compose_root`` (``docker-compose*.yml``
    or ``docker-compose*.yaml``) that nests a substitution -- braced
    (``${OTHER}``) or bare (``$OTHER``) -- inside another variable's default
    value.

    mocker misparses the nested form, so it must never reappear in a
    committed compose file: see lakesail-compose-nested-variable-default.
    """
    root = Path(compose_root)
    matches = {
        p
        for pattern in _COMPOSE_FILE_GLOBS
        for p in root.rglob(pattern)
        if _NESTED_VARIABLE_DEFAULT_RE.search(p.read_text(encoding="utf-8"))
    }
    return sorted(matches)
