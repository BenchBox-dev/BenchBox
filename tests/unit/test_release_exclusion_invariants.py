"""Tests that release exclusion configs stay in sync with the actual codebase.

Catches drift between the four layers that control what enters a public release:
  A. workflow.py HOLD_BACK_PATHS         (public tree copy)
  B. pyproject.toml package excludes     (wheel)
  C. MANIFEST.in prune directives        (sdist)
  D. workflow.py GITIGNORE_PRIVATE_*     (.gitignore transformation)

Every exclusion pattern must target something that actually exists. Package
metadata exclusions (layers B/C) must remain a subset of the public-tree
hold-backs (layer A), but layer A may be broader because it also removes
tests, workflows, and individual files that are not modeled in pyproject.toml.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

# Resolve repo root relative to this test file
REPO_ROOT = Path(__file__).parent.parent.parent
BENCHBOX_DIR = REPO_ROOT / "benchbox"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def _load_manifest_prunes() -> list[str]:
    """Extract all 'prune <path>' directives from MANIFEST.in."""
    manifest = REPO_ROOT / "MANIFEST.in"
    prunes: list[str] = []
    for line in manifest.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("prune "):
            prunes.append(stripped.split(None, 1)[1])
    return prunes


def _load_gitignore_lines() -> list[str]:
    """Load .gitignore as stripped lines."""
    return [line.strip() for line in (REPO_ROOT / ".gitignore").read_text().splitlines()]


def _pyproject_benchbox_excludes() -> list[str]:
    """Return pyproject.toml exclude patterns that target benchbox.* packages."""
    config = _load_pyproject()
    excludes = config.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {}).get("exclude", [])
    return [p for p in excludes if p.startswith("benchbox.")]


def _manifest_benchbox_prunes() -> list[str]:
    """Return MANIFEST.in prune paths that target benchbox/ subdirectories."""
    return [p for p in _load_manifest_prunes() if p.startswith("benchbox/")]


def _pattern_to_path(pattern: str) -> str:
    """Convert a dotted setuptools package pattern to a relative path.

    'benchbox.platforms.clickhouse*' -> 'benchbox/platforms/clickhouse'
    """
    # Strip trailing glob characters
    clean = pattern.rstrip("*").rstrip(".")
    return clean.replace(".", "/")


# ---------------------------------------------------------------------------
# Layer A: HOLD_BACK_PATHS
# ---------------------------------------------------------------------------
class TestHoldBackPaths:
    """Validate HOLD_BACK_PATHS entries in workflow.py."""

    @pytest.mark.skip(
        reason=(
            "Obsolete under the two-branch single-repo migration: HOLD_BACK_PATHS now "
            "lists per-user agent configs that are tracked on private but absent on "
            "develop. The path-existence invariant no longer holds across branches. "
            "Removed entirely in Phase 6."
        )
    )
    def test_hold_back_paths_target_existing_paths(self):
        """Every HOLD_BACK_PATHS entry must resolve to a real file or directory."""
        from benchbox.release.workflow import HOLD_BACK_PATHS

        for rel_path in HOLD_BACK_PATHS:
            candidates = [REPO_ROOT / rel_path]
            if "/" not in rel_path:
                candidates.append(BENCHBOX_DIR / rel_path)
            assert any(path.exists() for path in candidates), (
                f"HOLD_BACK_PATHS entry '{rel_path}' does not exist. Remove or update it."
            )


# ---------------------------------------------------------------------------
# Layer B: pyproject.toml [tool.setuptools.packages.find] exclude
# ---------------------------------------------------------------------------
class TestPyprojectExcludes:
    """Validate pyproject.toml package exclusion patterns."""

    def test_benchbox_exclude_patterns_match_existing_packages(self):
        """Every benchbox.* exclude pattern must match at least one real package."""
        for pattern in _pyproject_benchbox_excludes():
            rel_path = _pattern_to_path(pattern)
            full_path = REPO_ROOT / rel_path
            assert full_path.exists(), (
                f"pyproject.toml exclude pattern '{pattern}' targets '{rel_path}' "
                f"which does not exist. Remove or update the pattern."
            )

    def test_benchbox_exclude_patterns_target_packages_not_files(self):
        """Exclude patterns should target packages (dirs with __init__.py), not bare .py files."""
        for pattern in _pyproject_benchbox_excludes():
            rel_path = _pattern_to_path(pattern)
            full_path = REPO_ROOT / rel_path
            if not full_path.exists():
                continue  # Caught by the existence test above
            if full_path.is_file():
                pytest.fail(
                    f"pyproject.toml exclude '{pattern}' targets a file, not a package. "
                    f"Setuptools package excludes only work on packages (directories). "
                    f"Use MANIFEST.in 'exclude' for individual files."
                )


# ---------------------------------------------------------------------------
# Layer C: MANIFEST.in prune directives
# ---------------------------------------------------------------------------
class TestManifestPrunes:
    """Validate MANIFEST.in prune directives."""

    @pytest.mark.skip(
        reason=(
            "Obsolete under the two-branch single-repo migration: MANIFEST.in carries "
            "defence-in-depth prunes for paths that exist on private (e.g. .claude/, "
            "_project/) but are curated out of develop or main. The 'must exist' "
            "invariant no longer holds. Removed entirely in Phase 6."
        )
    )
    def test_prune_targets_are_existing_directories(self):
        """Every MANIFEST.in 'prune' target must be a real directory."""
        for prune_path in _load_manifest_prunes():
            full_path = REPO_ROOT / prune_path
            assert full_path.is_dir(), (
                f"MANIFEST.in 'prune {prune_path}' targets a path that is not a "
                f"directory (or doesn't exist). Remove or update it."
            )


# ---------------------------------------------------------------------------
# Cross-layer: A/B/C agreement on benchbox/ exclusions
# ---------------------------------------------------------------------------
class TestCrossLayerAgreement:
    """Ensure package metadata exclusions stay inside the public-tree hold-backs."""

    @staticmethod
    def _normalize_benchbox_paths(paths: list[str]) -> set[str]:
        """Normalize paths to be relative to benchbox/ without trailing slashes."""
        result = set()
        for p in paths:
            # Strip 'benchbox/' prefix if present
            clean = p.removeprefix("benchbox/").removeprefix("benchbox\\").rstrip("/")
            result.add(clean)
        return result

    def test_package_layers_agree(self):
        """pyproject.toml and MANIFEST.in must agree on benchbox/ package exclusions.

        Under the two-branch model (see _project/decisions/single-repo-migration.md),
        wheel/sdist exclusions and HOLD_BACK_PATHS are no longer the same concern:
        - pyproject + MANIFEST.in control what ships in the published artefacts
          (the wheel and sdist users get from PyPI).
        - HOLD_BACK_PATHS controls what is allowed to appear on the public repo
          (any branch). Per the new model HOLD_BACK_PATHS is just per-user agent
          configs and secrets — paths like benchbox/release/ live on develop and
          on main, but are excluded from the published wheel/sdist by the
          package-layer excludes here.

        The cross-layer check is therefore narrowed to the still-meaningful
        invariant: pyproject and MANIFEST.in agree about which benchbox/ paths
        get curated out of the artefact.
        """
        pyproject_excludes = self._normalize_benchbox_paths(
            [_pattern_to_path(p).removeprefix("benchbox/") for p in _pyproject_benchbox_excludes()]
        )

        manifest_prunes = self._normalize_benchbox_paths(_manifest_benchbox_prunes())

        assert pyproject_excludes == manifest_prunes, (
            "pyproject.toml and MANIFEST.in disagree on benchbox/ package exclusions. "
            f"pyproject={pyproject_excludes} manifest={manifest_prunes}"
        )


# ---------------------------------------------------------------------------
# Layer D: Gitignore transformation constants
# ---------------------------------------------------------------------------


def _gitignore_has_private_sections() -> bool:
    """Return True only when .gitignore contains the private-repo section marker."""
    gitignore = Path(__file__).parent.parent.parent / ".gitignore"
    if not gitignore.exists():
        return False
    return "# Exclude everything in _project/" in gitignore.read_text()


@pytest.mark.skipif(
    not _gitignore_has_private_sections(),
    reason="Private gitignore sections only exist in the source repository",
)
class TestGitignoreConstants:
    """Validate GITIGNORE_PRIVATE_SECTIONS and GITIGNORE_PRIVATE_LINES against .gitignore."""

    def test_private_section_headers_exist_in_gitignore(self):
        """Every GITIGNORE_PRIVATE_SECTIONS entry must appear verbatim as a comment in .gitignore."""
        from benchbox.release.workflow import GITIGNORE_PRIVATE_SECTIONS

        gitignore_lines = _load_gitignore_lines()

        for header in GITIGNORE_PRIVATE_SECTIONS:
            found = any(line.startswith(header) for line in gitignore_lines)
            assert found, (
                f"GITIGNORE_PRIVATE_SECTIONS entry '{header}' not found in .gitignore. "
                f"The section header may have changed. Update the constant to match."
            )

    def test_private_lines_exist_in_gitignore(self):
        """Every GITIGNORE_PRIVATE_LINES entry must appear in .gitignore."""
        from benchbox.release.workflow import GITIGNORE_PRIVATE_LINES

        gitignore_lines = _load_gitignore_lines()

        for line in GITIGNORE_PRIVATE_LINES:
            assert line in gitignore_lines, (
                f"GITIGNORE_PRIVATE_LINES entry '{line}' not found in .gitignore. "
                f"The line may have been removed or changed. Update the constant."
            )
