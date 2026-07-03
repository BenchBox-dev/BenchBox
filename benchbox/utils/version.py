"""Version management utilities for BenchBox.

This module provides functionality for:
- Version consistency checking across files
- Version reporting and debugging
- Import error handling with version information

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Optional

# Python 3.11+ has tomllib in stdlib, older versions need tomli package
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

# NOTE: This module intentionally does NOT `import benchbox`. Doing so used
# to create a root-package import edge (this module is imported by
# benchbox/utils/verbosity.py, which is imported by ~every subsystem),
# pulling a large strongly-connected component into a cycle rooted at
# benchbox/__init__.py. See _project/TODO/main/planning/break-root-import-cycle.yaml.
# `get_package_version()` reads installed package metadata, and
# `get_init_version()` reads the `__version__` literal STATICALLY from the
# benchbox/__init__.py source file (no import) so the consistency checker
# still covers the literal that scripts/update_version.py bumps at release
# cut, without recreating the cycle.

# Cache for parsed pyproject.toml to avoid repeated file reads
_PYPROJECT_CACHE: Optional[dict] = None

# benchbox/__init__.py, resolved relative to this file (benchbox/utils/version.py).
# Ships inside wheels too, so the static read below works for installed packages.
_PACKAGE_INIT_PATH = Path(__file__).parent.parent / "__init__.py"

# Same pattern scripts/update_version.py uses to bump the literal at release cut.
_INIT_VERSION_PATTERN = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')

# Version sources beyond package metadata that we validate for consistency
_ADDITIONAL_VERSION_PATHS = (
    Path("README.md"),
    Path("docs") / "README.md",
    Path("benchbox") / "utils" / "VERSION_MANAGEMENT.md",
)

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Resolve documentation paths relative to the project root to avoid surprises
DOCUMENTATION_VERSION_PATHS = tuple(PROJECT_ROOT / path for path in _ADDITIONAL_VERSION_PATHS)

_DOC_VERSION_PATTERN = re.compile(
    r"Current\s+release\s*:?\s*`?v?(?P<version>\d+\.\d+\.\d+(?:-[\w\.]+)?)`?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VersionConsistencyResult:
    """Detailed outcome of version consistency validation."""

    consistent: bool
    message: str
    expected_version: Optional[str]
    sources: dict[str, Optional[str]]
    normalized_sources: dict[str, Optional[str]]
    missing_sources: tuple[str, ...]
    mismatched_sources: tuple[str, ...]


@dataclass(frozen=True)
class _SemVer:
    """Simple semantic version representation (supports pre-release tags)."""

    major: int
    minor: int
    patch: int
    pre_label: Optional[str] = None
    pre_number: int = 0


_SEMVER_PATTERN = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<label>alpha|beta|rc|dev)(?:\.(?P<number>\d+))?)?$"
)

_PRE_RELEASE_ORDER = {
    None: 5,  # Release versions rank highest
    "rc": 4,
    "beta": 3,
    "alpha": 2,
    "dev": 1,
}


def _parse_semver(version: str) -> _SemVer:
    """Parse a semantic version string.

    Args:
        version: String following the BenchBox semver format.

    Raises:
        ValueError: If the version string is not a valid semantic version.
    """

    match = _SEMVER_PATTERN.match(version)
    if not match:
        raise ValueError(f"Invalid BenchBox semantic version: '{version}'")

    label = match.group("label")
    number_str = match.group("number")

    return _SemVer(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        pre_label=label,
        pre_number=int(number_str) if number_str is not None else 0,
    )


def _compare_semver(first: _SemVer, second: _SemVer) -> int:
    """Compare two semantic version structures.

    Returns:
        -1 if first < second, 0 if equal, 1 if first > second.
    """

    if first.major != second.major:
        return 1 if first.major > second.major else -1
    if first.minor != second.minor:
        return 1 if first.minor > second.minor else -1
    if first.patch != second.patch:
        return 1 if first.patch > second.patch else -1

    # Handle pre-release ordering (release > pre-release)
    order_first = _PRE_RELEASE_ORDER.get(first.pre_label, 0)
    order_second = _PRE_RELEASE_ORDER.get(second.pre_label, 0)

    if order_first != order_second:
        return 1 if order_first > order_second else -1

    if first.pre_number != second.pre_number:
        return 1 if first.pre_number > second.pre_number else -1

    return 0


def _read_text_safe(path: Path) -> Optional[str]:
    """Read text from a file, returning None if unavailable."""

    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _document_source_key(path: Path) -> str:
    """Convert an absolute documentation path into a readable source label."""

    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _collect_documentation_versions() -> dict[str, Optional[str]]:
    """Collect version markers from documentation files."""

    versions: dict[str, Optional[str]] = {}

    for doc_path in DOCUMENTATION_VERSION_PATHS:
        text = _read_text_safe(doc_path)
        version = None
        if text:
            match = _DOC_VERSION_PATTERN.search(text)
            if match:
                version = match.group("version")
        versions[_document_source_key(doc_path)] = version

    return versions


def _normalize_version(value: Optional[str]) -> Optional[str]:
    """Normalize version markers by stripping prefixes/punctuation."""

    if value is None:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    if candidate.startswith("v") and len(candidate) > 1 and candidate[1].isdigit():
        candidate = candidate[1:]

    candidate = candidate.rstrip("`'\". ")
    return candidate or None


def get_pyproject_version() -> Optional[str]:
    """Get version from pyproject.toml file.

    Returns:
        Version string from pyproject.toml, or None if not found.
    """
    global _PYPROJECT_CACHE

    if _PYPROJECT_CACHE is None:
        try:
            # Find pyproject.toml in project root
            pyproject_path = PROJECT_ROOT / "pyproject.toml"

            if pyproject_path.exists():
                with open(pyproject_path, "rb") as f:
                    _PYPROJECT_CACHE = tomllib.load(f)
            else:
                _PYPROJECT_CACHE = {}
        except Exception:
            # Graceful fallback if file cannot be read
            _PYPROJECT_CACHE = {}

    return _PYPROJECT_CACHE.get("project", {}).get("version")


def get_init_version() -> Optional[str]:
    """Statically read the ``__version__`` literal from benchbox/__init__.py.

    This is the value ``scripts/update_version.py`` bumps at release cut and
    that ``benchbox --version`` ultimately reports via ``benchbox.__version__``.
    It is read from the source file with a regex (same pattern
    scripts/update_version.py uses) rather than by importing the package
    root, so the root-import cycle removed by break-root-import-cycle stays
    broken. The file ships inside built wheels, so this also works for
    installed (non-dev) packages.

    Returns:
        The version literal, or None if the file or literal is unavailable.
    """
    text = _read_text_safe(_PACKAGE_INIT_PATH)
    if not text:
        return None
    match = _INIT_VERSION_PATTERN.search(text)
    return match.group(1) if match else None


def get_installed_dist_version() -> Optional[str]:
    """Get the installed distribution's version from importlib.metadata.

    Returns:
        The installed dist version, or None when benchbox is not installed
        as a distribution at all (e.g. running from a bare source checkout
        without an editable install) - a legitimate state, not an error.
    """
    try:
        return importlib_metadata.version("benchbox")
    except importlib_metadata.PackageNotFoundError:
        return None


def get_package_version() -> str:
    """Get the installed BenchBox package version.

    Reads installed package metadata (``importlib.metadata``) instead of
    importing the ``benchbox`` package root, which would recreate the
    root-import cycle removed by break-root-import-cycle (this module is
    imported by ``benchbox.utils.verbosity``, which is imported by nearly
    every subsystem). Falls back to the static ``__version__`` literal in
    benchbox/__init__.py, then the source-tree ``pyproject.toml`` version,
    only when no installed package metadata is available at all (e.g.
    running from a bare checkout without an editable install).

    Note: this is intentionally NOT unified with ``get_init_version()`` /
    ``get_pyproject_version()`` even though all three usually agree -
    keeping them independently sourced lets ``check_version_consistency()``
    actually detect drift between the installed dist metadata, the
    __init__.py literal, and the working-tree pyproject.toml, rather than
    the check becoming a tautology.

    Returns:
        Version string, or "unknown" if no source is available.
    """
    installed = get_installed_dist_version()
    if installed is not None:
        return installed
    return get_init_version() or get_pyproject_version() or "unknown"


def is_version_compatible(
    min_version: Optional[str] = None,
    max_version: Optional[str] = None,
    current_version: Optional[str] = None,
) -> bool:
    """Check if the current BenchBox version falls within the provided bounds.

    Args:
        min_version: Minimum supported version (inclusive).
        max_version: Maximum supported version (inclusive).
        current_version: Override version to check (defaults to package version).

    Returns:
        True if the current version is compatible with the provided range.

    Raises:
        ValueError: If any provided version does not match the expected format.
    """

    version_str = current_version or get_package_version()
    if not version_str:
        return False

    current_semver = _parse_semver(version_str)

    if min_version:
        minimum = _parse_semver(min_version)
        if _compare_semver(current_semver, minimum) < 0:
            return False

    if max_version:
        maximum = _parse_semver(max_version)
        if _compare_semver(current_semver, maximum) > 0:
            return False

    return True


# Non-documentation source keys tracked by _gather_version_sources().
_CORE_VERSION_SOURCE_KEYS = frozenset({"benchbox.__init__", "installed-dist", "pyproject.toml"})


def _gather_version_sources() -> dict[str, Optional[str]]:
    """Collect raw version strings from all tracked sources.

    Sources:
    - "benchbox.__init__": the ``__version__ = "..."`` literal read
      STATICALLY from benchbox/__init__.py (the value release tooling bumps
      and ``benchbox --version`` reports). This is the drift class that
      shipped the 0.3.0 wheel with ``__version__ = "0.2.1"``.
    - "installed-dist": the installed distribution's version from
      importlib.metadata (None when not installed as a dist - legitimate for
      bare source checkouts, see check_version_consistency()).
    - "pyproject.toml": the working-tree project version.
    - documentation release markers (README.md etc.).
    """

    versions: dict[str, Optional[str]] = {
        "benchbox.__init__": get_init_version(),
        "installed-dist": get_installed_dist_version(),
        "pyproject.toml": get_pyproject_version(),
    }
    versions.update(_collect_documentation_versions())
    return versions


def check_version_consistency() -> VersionConsistencyResult:
    """Check if versions are consistent across all sources.

    In installed mode (wheel), missing external files (pyproject.toml, README.md, etc.)
    are expected and not treated as inconsistencies. Only actual version mismatches
    between available sources trigger warnings.
    """
    from benchbox.utils.dependencies import is_development_install

    versions = _gather_version_sources()
    normalized = {source: _normalize_version(value) for source, value in versions.items()}

    # In installed mode, missing files are expected - only count them if in dev mode
    is_dev = is_development_install()
    if is_dev:
        # "installed-dist" is exempt from missing-source accounting even in
        # dev mode: absence just means benchbox isn't installed as a
        # distribution (e.g. a bare source checkout), which is legitimate.
        # When present, it still participates in mismatch detection below.
        missing_sources = tuple(
            source for source, value in normalized.items() if value is None and source != "installed-dist"
        )
    else:
        # In installed mode, only require benchbox.__init__ to have a version
        # (the static __init__.py read works inside wheels too).
        missing_sources = () if normalized.get("benchbox.__init__") else ("benchbox.__init__",)

    # Determine the expected version from the first non-missing entry
    expected_version = next((value for value in normalized.values() if value is not None), None)

    mismatched_sources: tuple[str, ...]
    if expected_version is None:
        mismatched_sources = ()
    else:
        mismatched_sources = tuple(
            source for source, value in normalized.items() if value and value != expected_version
        )

    if expected_version is None:
        message = "No version information found"
        consistent = False
    elif missing_sources:
        missing_list = ", ".join(missing_sources)
        message = f"Missing version markers in: {missing_list}"
        consistent = False
    elif mismatched_sources:
        mismatched_details = {source: versions[source] for source in mismatched_sources}
        message = f"Version mismatch detected: {mismatched_details}"
        consistent = False
    else:
        message = f"All version markers aligned at {expected_version}"
        consistent = True

    return VersionConsistencyResult(
        consistent=consistent,
        message=message,
        expected_version=expected_version,
        sources=versions,
        normalized_sources=normalized,
        missing_sources=missing_sources,
        mismatched_sources=mismatched_sources,
    )


@lru_cache(maxsize=1)
def get_version_info() -> dict[str, object]:
    """Get comprehensive version information for debugging."""

    benchbox_version = get_package_version()
    pyproject_version = get_pyproject_version()
    consistency = check_version_consistency()

    documentation_versions = {
        source: consistency.sources[source] for source in consistency.sources if source not in _CORE_VERSION_SOURCE_KEYS
    }

    release_tag = f"v{benchbox_version}" if benchbox_version else "unknown"

    return {
        "benchbox_version": benchbox_version or "unknown",
        "release_tag": release_tag,
        "pyproject_version": pyproject_version or "unknown",
        "documentation_versions": documentation_versions,
        "version_sources": consistency.sources,
        "normalized_version_sources": consistency.normalized_sources,
        "version_consistent": consistency.consistent,
        "version_message": consistency.message,
        "expected_version": consistency.expected_version,
        "missing_sources": consistency.missing_sources,
        "mismatched_sources": consistency.mismatched_sources,
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": sys.platform,
    }


def format_version_report(as_json: bool = False, include_system: bool = True) -> str:
    """Format a version report for CLI / diagnostics."""

    info = get_version_info()

    if as_json:
        payload = {
            "benchbox_version": info["benchbox_version"],
            "release_tag": info["release_tag"],
            "pyproject_version": info["pyproject_version"],
            "documentation_versions": info["documentation_versions"],
            "version_consistent": info["version_consistent"],
            "version_message": info["version_message"],
            "expected_version": info["expected_version"],
            "missing_sources": info["missing_sources"],
            "mismatched_sources": info["mismatched_sources"],
        }

        if include_system:
            payload.update(
                {
                    "python_version": info["python_version"],
                    "python_executable": info["python_executable"],
                    "platform": info["platform"],
                }
            )

        return json.dumps(payload, indent=2, sort_keys=True)

    documentation_versions = info.get("documentation_versions", {})
    consistency = "Yes" if info.get("version_consistent") else "No"

    lines = [
        f"BenchBox Version: {info['benchbox_version']}",
        f"Release Tag: {info['release_tag']}",
        f"pyproject.toml Version: {info['pyproject_version']}",
    ]

    for source, version in documentation_versions.items():
        lines.append(f"{source} Version: {version}")

    lines.extend(
        [
            f"Version Consistency: {consistency}",
            f"Status: {info['version_message']}",
        ]
    )

    if include_system:
        lines.extend(
            [
                "",
                f"Python Version: {info['python_version']}",
                f"Python Executable: {info['python_executable']}",
                f"Platform: {info['platform']}",
            ]
        )

    return "\n".join(lines)


def ensure_version_compatible(
    min_version: Optional[str] = None,
    max_version: Optional[str] = None,
    current_version: Optional[str] = None,
) -> None:
    """Validate that the BenchBox version is within expected bounds.

    Args:
        min_version: Minimum supported version (inclusive).
        max_version: Maximum supported version (inclusive).
        current_version: Override version to check (defaults to package version).

    Raises:
        RuntimeError: If the current version is outside of the supported range.
        ValueError: If a provided version string is invalid.
    """

    if is_version_compatible(min_version=min_version, max_version=max_version, current_version=current_version):
        return

    info = get_version_info()
    version_range_parts = []
    if min_version:
        version_range_parts.append(f">= {min_version}")
    if max_version:
        version_range_parts.append(f"<= {max_version}")
    version_range = " and ".join(version_range_parts) if version_range_parts else "the supported range"

    raise RuntimeError(
        "BenchBox version compatibility check failed. "
        f"Current version {info['benchbox_version']} is outside of {version_range}."
    )


def reset_version_cache() -> None:
    """Clear cached version metadata (useful for tests and tooling)."""

    global _PYPROJECT_CACHE
    _PYPROJECT_CACHE = None
    get_version_info.cache_clear()


def validate_version_consistency() -> None:
    """Validate version consistency and raise error if inconsistent.

    Raises:
        RuntimeError: If versions are inconsistent across files.
    """
    consistency = check_version_consistency()

    if consistency.consistent:
        return

    details = {
        "sources": consistency.sources,
        "expected": consistency.expected_version,
        "missing": consistency.missing_sources,
        "mismatched": consistency.mismatched_sources,
    }

    raise RuntimeError(
        "Version inconsistency detected. "
        f"{consistency.message}. "
        f"Details: {details}. "
        "Please ensure benchbox/__init__.py, pyproject.toml, and documentation release markers are aligned."
    )


class ImportErrorWithVersion(ImportError):
    """Enhanced ImportError that includes version information for debugging."""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        """Initialize enhanced import error.

        Args:
            message: Error message describing the import failure.
            original_error: Original exception that caused the import failure.
        """
        version_info = get_version_info()
        enhanced_message = (
            f"{message}\n\n"
            f"Version Information:\n"
            f"  BenchBox: {version_info['benchbox_version']}\n"
            f"  Release: {version_info['release_tag']}\n"
            f"  Python: {version_info['python_version']}\n"
            f"  Platform: {version_info['platform']}\n"
        )

        if original_error:
            enhanced_message += f"\nOriginal error: {original_error}"

        super().__init__(enhanced_message)
        self.original_error = original_error
        self.version_info = version_info


def create_import_error(
    benchmark_name: str, missing_dependencies: Optional[list] = None, original_error: Optional[Exception] = None
) -> ImportErrorWithVersion:
    """Create an enhanced import error with helpful information.

    Args:
        benchmark_name: Name of the benchmark that failed to import.
        missing_dependencies: List of missing dependencies that might fix the issue.
        original_error: Original exception that caused the import failure.

    Returns:
        Enhanced ImportError with version and dependency information.
    """
    message = f"Could not import benchmark '{benchmark_name}'"

    if missing_dependencies:
        deps_str = ", ".join(sorted(missing_dependencies))
        message += f". Optional dependency extras required: {deps_str}"
        suggestions = [f"uv add benchbox --extra {extra}" for extra in missing_dependencies]
        combined_extras = " ".join(f"--extra {extra}" for extra in sorted(missing_dependencies))
        combined = f"uv add benchbox {combined_extras}"
        if len(missing_dependencies) > 1:
            suggestions.append(combined)
        message += "\n\nSuggested installs:\n  " + "\n  ".join(sorted(set(suggestions)))

    return ImportErrorWithVersion(message, original_error)
