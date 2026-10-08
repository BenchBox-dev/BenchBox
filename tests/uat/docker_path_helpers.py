from __future__ import annotations

import re
from pathlib import Path, PurePath, PureWindowsPath

_NESTED_VARIABLE_DEFAULT_RE = re.compile(r"\$\{[^}]*\$(?:\{|[A-Za-z_])")

_COMPOSE_FILE_GLOBS = ("docker-compose*.yml", "docker-compose*.yaml")

_BENCHBOX_DATA_DIR_NON_FLAT_RE = re.compile(r"\$\{BENCHBOX_DATA_DIR(?![}\w])")

_BENCHBOX_DATA_DIR_ENV_RE = re.compile(r"^[ \t]*(?:export[ \t]+)?BENCHBOX_DATA_DIR[ \t]*=[ \t]*(\S*)", re.MULTILINE)

_ENV_FILE_GLOBS = ("*.env", ".env.*")


def compose_path_ends_with(path: str | PurePath, *expected_parts: str) -> bool:
    actual_parts = PureWindowsPath(path).parts
    if len(actual_parts) < len(expected_parts):
        return False
    return actual_parts[-len(expected_parts) :] == expected_parts


def find_nested_variable_defaults(compose_root: str | Path) -> list[Path]:
    root = Path(compose_root)
    matches = {
        p
        for pattern in _COMPOSE_FILE_GLOBS
        for p in root.rglob(pattern)
        if _NESTED_VARIABLE_DEFAULT_RE.search(p.read_text(encoding="utf-8"))
    }
    return sorted(matches)


def find_non_flat_benchbox_data_dir_mounts(compose_root: str | Path) -> list[Path]:
    root = Path(compose_root)
    matches = {
        p
        for pattern in _COMPOSE_FILE_GLOBS
        for p in root.rglob(pattern)
        if _BENCHBOX_DATA_DIR_NON_FLAT_RE.search(p.read_text(encoding="utf-8"))
    }
    return sorted(matches)


def find_env_files_with_non_absolute_data_dir(compose_root: str | Path) -> list[Path]:
    root = Path(compose_root)
    env_paths = {p for pattern in _ENV_FILE_GLOBS for p in root.rglob(pattern)}
    matches = []
    for env_path in sorted(env_paths):
        text = env_path.read_text(encoding="utf-8")
        for match in _BENCHBOX_DATA_DIR_ENV_RE.finditer(text):
            value = match.group(1).strip("'\"")
            if not value.startswith("/"):
                matches.append(env_path)
                break
    return sorted(matches)
