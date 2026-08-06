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
# platform's server resolves client-sent file paths server-side), so any
# compose file's reference to it must stay the bare/flat ${BENCHBOX_DATA_DIR}
# form -- no default and no required-variable modifier of ANY POSIX form: a
# nested default is the mocker-misparsed form find_nested_variable_defaults()
# already catches; ${VAR:?...} is silently left unsubstituted by mocker
# 0.7.2 even when the variable IS set; and a flat *default* value (colon or
# no colon: ${VAR:-x}, ${VAR-x}, ${VAR:?msg}, ${VAR?msg}, ${VAR:+alt},
# ${VAR+alt}) can only ever be a relative path here, breaking the
# path-mirroring contract. Not scoped to lakesail/velox by an allowlist --
# any compose file anywhere under docker/ that references BENCHBOX_DATA_DIR
# non-flatly is flagged, so a third path-mirroring platform gets the same
# coverage automatically. See lakesail-compose-nested-variable-default.
_BENCHBOX_DATA_DIR_NON_FLAT_RE = re.compile(r"\$\{BENCHBOX_DATA_DIR(?![}\w])")

# A checked-in docker/<stack>/.env supplying a directory-RELATIVE (or empty)
# BENCHBOX_DATA_DIR fallback was tried and reverted
# (lakesail-compose-nested-variable-default): docker/lakesail/docker-compose.yml
# and docker/velox/docker-compose.yml mount BENCHBOX_DATA_DIR at the SAME
# absolute path on host and in container, so a relative -- or empty, which
# resolves to the same silent-empty-mount defect an unset variable produces
# -- value can never work. This does not forbid a .env that sets
# BENCHBOX_DATA_DIR to an absolute value.
_BENCHBOX_DATA_DIR_ENV_RE = re.compile(r"^[ \t]*(?:export[ \t]+)?BENCHBOX_DATA_DIR[ \t]*=[ \t]*(\S*)", re.MULTILINE)

# Any dotenv-style file wirable via `docker compose --env-file`, not just the
# literal name `.env`: `.env.local`, `.env.lakesail`, `compose.env` are all
# real dotenv filenames and none of them is named exactly `.env`.
_ENV_FILE_GLOBS = ("*.env", ".env.*")


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
    """Return every compose file under ``compose_root`` whose BENCHBOX_DATA_DIR
    reference is not the bare/flat ``${BENCHBOX_DATA_DIR}`` form.

    Any platform mounting BENCHBOX_DATA_DIR at the SAME absolute path on host
    and in container must keep the reference bare: no default and no
    required-variable modifier, in ANY POSIX form (colon or colon-less). See
    lakesail-compose-nested-variable-default.
    """
    root = Path(compose_root)
    matches = {
        p
        for pattern in _COMPOSE_FILE_GLOBS
        for p in root.rglob(pattern)
        if _BENCHBOX_DATA_DIR_NON_FLAT_RE.search(p.read_text(encoding="utf-8"))
    }
    return sorted(matches)


def find_env_files_with_non_absolute_data_dir(compose_root: str | Path) -> list[Path]:
    """Return dotenv-style files under ``compose_root`` that set
    BENCHBOX_DATA_DIR to a relative or empty value.

    docker/lakesail/docker-compose.yml and docker/velox/docker-compose.yml
    mount BENCHBOX_DATA_DIR at the SAME absolute path on host and in
    container; a relative .env value can never satisfy that (the specific
    defect in the reverted per-stack .env fallback), and an empty value
    resolves to the same silent-empty-mount defect an unset variable
    produces (see lakesail-compose-nested-variable-default). Checks every
    ``*.env`` / ``.env.*`` file, not just one literally named ``.env`` --
    ``.env.local``, ``.env.lakesail``, and ``compose.env`` are all wirable
    via ``docker compose --env-file``. An absolute BENCHBOX_DATA_DIR value
    is not flagged by this check.
    """
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
