"""Bundle platform allowlist coverage for newly admitted platforms.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.validation.bundle import KNOWN_PLATFORMS, ValidationResult, _validate_platform_section

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _validate_platform_name(name: str) -> ValidationResult:
    vr = ValidationResult(path="<test>")
    _validate_platform_section({"name": name}, vr)
    return vr


class TestBundlePlatformAllowlist:
    """Corpus-admitted platforms must validate without unknown-name warnings."""

    def test_ducklake_is_known(self):
        assert "ducklake" in KNOWN_PLATFORMS

    def test_ducklake_bundle_section_validates_clean(self):
        vr = _validate_platform_name("DuckLake")
        assert vr.errors == []
        assert vr.warnings == []

    def test_genuinely_unknown_platform_still_warns(self):
        vr = _validate_platform_name("Not A Real Platform")
        assert vr.errors == []
        assert any("Unknown platform name" in warning for warning in vr.warnings)
