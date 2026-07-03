"""Tests for version management utilities."""

import pytest

from benchbox.utils import version as version_utils

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.unit
class TestVersionConsistency:
    """Validate version consistency helpers."""

    def test_check_version_consistency_matches_pyproject(self):
        """The recorded versions should match between package and pyproject."""
        result = version_utils.check_version_consistency()

        assert result.consistent, result.message
        assert result.sources["benchbox.__init__"] == result.sources["pyproject.toml"]

    def test_check_version_consistency_detects_mismatch(self, monkeypatch):
        """A mismatch between sources must be reported."""

        monkeypatch.setattr(version_utils, "get_pyproject_version", lambda: "9.9.9")

        result = version_utils.check_version_consistency()

        assert not result.consistent
        assert "mismatch" in result.message.lower()
        assert result.sources["pyproject.toml"] == "9.9.9"

    def test_init_source_reads_the_literal_statically(self):
        """The "benchbox.__init__" source must be the __version__ literal
        read from the benchbox/__init__.py source file (the value
        scripts/update_version.py bumps at release cut and benchbox.__version__
        exposes at runtime), read without importing the package root.
        """
        import benchbox

        literal = version_utils.get_init_version()

        assert literal is not None
        assert literal == benchbox.__version__

        result = version_utils.check_version_consistency()
        assert result.sources["benchbox.__init__"] == literal

    def test_check_version_consistency_detects_init_literal_drift(self, monkeypatch):
        """A stale __version__ literal in benchbox/__init__.py (the exact
        drift class that shipped the 0.3.0 wheel with __version__ = "0.2.1")
        must flip the check to inconsistent.

        Documentation sources are stubbed out so this stays a hermetic unit
        test of the init-literal drift path, independent of the working
        tree's README/doc release-marker state.
        """

        monkeypatch.setattr(version_utils, "_collect_documentation_versions", dict)
        monkeypatch.setattr(version_utils, "get_init_version", lambda: "0.0.0")

        result = version_utils.check_version_consistency()

        assert not result.consistent
        assert "mismatch" in result.message.lower()
        assert result.sources["benchbox.__init__"] == "0.0.0"

    def test_installed_dist_is_a_distinct_checked_source(self, monkeypatch):
        """Installed dist metadata participates in consistency checking as
        its own source, so dist-metadata drift (e.g. stale editable install)
        is caught too."""

        result = version_utils.check_version_consistency()
        assert "installed-dist" in result.sources

        monkeypatch.setattr(version_utils, "get_installed_dist_version", lambda: "8.8.8")
        drifted = version_utils.check_version_consistency()

        assert not drifted.consistent
        assert "installed-dist" in drifted.mismatched_sources

    def test_missing_installed_dist_is_not_an_inconsistency(self, monkeypatch):
        """A bare source checkout without any installed benchbox dist is a
        legitimate state: "installed-dist" being None must not flip the
        check to inconsistent or appear in missing_sources.

        Documentation sources are stubbed out so this stays a hermetic unit
        test of the installed-dist exemption, independent of the working
        tree's README/doc release-marker state.
        """

        monkeypatch.setattr(version_utils, "_collect_documentation_versions", dict)
        monkeypatch.setattr(version_utils, "get_installed_dist_version", lambda: None)

        result = version_utils.check_version_consistency()

        assert result.consistent, result.message
        assert "installed-dist" not in result.missing_sources


@pytest.mark.unit
class TestVersionCompatibility:
    """Check semantic version compatibility helpers."""

    def test_is_version_compatible_within_bounds(self):
        """Current version should always be compatible with its own bounds."""
        current = version_utils.get_package_version()

        assert version_utils.is_version_compatible(min_version=current)
        assert version_utils.is_version_compatible(max_version=current)

    def test_is_version_compatible_out_of_bounds(self):
        """Compatibility check should fail when outside the supported range."""
        assert not version_utils.is_version_compatible(max_version="0.0.1")

    def test_is_version_compatible_invalid_version_string(self):
        """Invalid spec strings should raise ValueError for quick feedback."""
        with pytest.raises(ValueError):
            version_utils.is_version_compatible(min_version="not-a-version")

    def test_ensure_version_compatible_raises_with_clear_message(self):
        """ensure_version_compatible should raise when the range is violated."""
        with pytest.raises(RuntimeError) as excinfo:
            version_utils.ensure_version_compatible(max_version="0.0.1")

        assert "compatibility" in str(excinfo.value).lower()


@pytest.mark.unit
class TestEnhancedImportErrors:
    """Validate helpful messaging when optional dependencies are missing."""

    def test_create_import_error_includes_dependency_guidance(self):
        """Import errors must include actionable installation guidance."""
        error = version_utils.create_import_error(
            benchmark_name="TPCDI",
            missing_dependencies=["tpcdi", "extras"],
            original_error=ImportError("No module named benchbox.tpcdi"),
        )

        message = str(error)

        assert "uv add" in message
        assert "Version Information" in message
        assert "Original error" in message
