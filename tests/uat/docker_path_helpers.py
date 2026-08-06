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

# docker/lakesail/docker-compose.yml and docker/velox/docker-compose.yml mount
# BENCHBOX_DATA_DIR at the SAME absolute path on host and in container (the
# platform's server resolves client-sent file paths server-side). That mount
# must stay the bare/flat ${BENCHBOX_DATA_DIR} form with no default and no
# required-variable modifier: a nested default is the mocker-misparsed form
# find_nested_variable_defaults() already catches, a required-variable
# default (${VAR:?...}) is silently left unsubstituted by mocker 0.7.2 even
# when the variable IS set, and a flat *default* value can only ever be a
# relative path here -- which breaks the path-mirroring contract. See
# lakesail-compose-nested-variable-default.
_COMPOSE_FILES_REQUIRING_FLAT_DATA_DIR = ("lakesail/docker-compose.yml", "velox/docker-compose.yml")
_BENCHBOX_DATA_DIR_NON_FLAT_RE = re.compile(r"\$\{BENCHBOX_DATA_DIR:[-?]")

# A checked-in docker/<stack>/.env supplying a directory-RELATIVE
# BENCHBOX_DATA_DIR fallback was tried and reverted
# (lakesail-compose-nested-variable-default): docker/lakesail/docker-compose.yml
# and docker/velox/docker-compose.yml mount BENCHBOX_DATA_DIR at the SAME
# absolute path on host and in container, so a relative default can never
# work. This does not forbid a .env that sets BENCHBOX_DATA_DIR to an
# absolute value -- only a relative one, which is the specific defect that
# shipped.
_BENCHBOX_DATA_DIR_ENV_RE = re.compile(r"^[ \t]*(?:export[ \t]+)?BENCHBOX_DATA_DIR[ \t]*=[ \t]*(\S*)", re.MULTILINE)


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


def find_non_flat_benchbox_data_dir_mounts(compose_root: str | Path) -> list[Path]:
    """Return lakesail/velox compose files whose BENCHBOX_DATA_DIR reference is
    not the bare/flat ``${BENCHBOX_DATA_DIR}`` form.

    Both compose files must mount BENCHBOX_DATA_DIR at the SAME absolute path
    on host and in container, so the reference must stay bare: no default
    (``:-``) and no required-variable modifier (``:?``). See
    lakesail-compose-nested-variable-default.
    """
    root = Path(compose_root)
    matches = []
    for rel in _COMPOSE_FILES_REQUIRING_FLAT_DATA_DIR:
        path = root / rel
        if path.exists() and _BENCHBOX_DATA_DIR_NON_FLAT_RE.search(path.read_text(encoding="utf-8")):
            matches.append(path)
    return sorted(matches)


def find_env_files_with_relative_data_dir(compose_root: str | Path) -> list[Path]:
    """Return ``.env`` files under ``compose_root`` that set BENCHBOX_DATA_DIR
    to a relative value.

    docker/lakesail/docker-compose.yml and docker/velox/docker-compose.yml
    mount BENCHBOX_DATA_DIR at the SAME absolute path on host and in
    container; a relative .env default can never satisfy that -- this is the
    specific defect in the reverted per-stack .env fallback (see
    lakesail-compose-nested-variable-default). An absolute BENCHBOX_DATA_DIR
    value in a .env file is not flagged by this check.
    """
    root = Path(compose_root)
    matches = []
    for env_path in root.rglob(".env"):
        text = env_path.read_text(encoding="utf-8")
        for match in _BENCHBOX_DATA_DIR_ENV_RE.finditer(text):
            value = match.group(1).strip("'\"")
            if value and not value.startswith("/"):
                matches.append(env_path)
                break
    return sorted(matches)
