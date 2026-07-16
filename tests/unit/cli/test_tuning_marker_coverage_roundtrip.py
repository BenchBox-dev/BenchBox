"""Resolver-marker <-> coverage-parser round-trip.

From the 2026-07-12 tuning review, finding R7: `benchbox/core/tuning/
coverage.py`'s `status_from_log_text` classifies UAT logs by matching
hand-written marker substrings (`"Tuning: auto-discovered template"`,
`"Tuning: using basic constraints"`, `"Tuning disabled:"`) against whatever
`benchbox/cli/tuning_resolver.py`'s `resolve_tuning()` actually printed. Both
sides had zero coverage tying them together, so a resolver wording change
could silently break the UAT coverage matrix without either module's own
tests noticing.

This module calls the real `resolve_tuning()` (via its private `_resolve_*`
entry points, exercised through the public `resolve_tuning()` dispatcher) to
produce actual `TuningResolution.info_messages`, then feeds that real text
into `coverage.py`'s real `status_from_log_text()` -- no hand-written marker
strings appear on either side of the assertion.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from benchbox.cli.tuning_resolver import TuningMode, TuningSource, resolve_tuning
from benchbox.core.tuning.coverage import BASIC_CONSTRAINTS, TUNED_TEMPLATE, UNTUNED, status_from_log_text

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def mock_console():
    return MagicMock(spec=Console)


def _resolution_log_text(resolution) -> str:
    """Reconstruct the text coverage.py would see in a UAT log: the resolver's
    own info messages, exactly as `display_tuning_resolution` prints them.
    """
    return "\n".join(resolution.info_messages)


class TestResolverMarkerFeedsCoverageParser:
    def test_notuning_marker_classifies_as_untuned(self, mock_console) -> None:
        resolution = resolve_tuning(
            tuning_arg="notuning",
            platform=None,
            benchmark=None,
            config_manager=MagicMock(get=lambda *_a, **_kw: None),
            console=mock_console,
        )
        assert resolution.mode == TuningMode.NOTUNING

        status = status_from_log_text(_resolution_log_text(resolution))
        assert status == UNTUNED

    def test_fallback_no_template_found_classifies_as_basic_constraints(self, mock_console) -> None:
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with patch.object(Path, "exists", return_value=False):
            resolution = resolve_tuning(
                tuning_arg="tuned",
                platform="nonexistent-platform",
                benchmark="nonexistent-benchmark",
                config_manager=mock_config,
                console=mock_console,
            )
        assert resolution.source == TuningSource.FALLBACK

        status = status_from_log_text(_resolution_log_text(resolution))
        assert status == BASIC_CONSTRAINTS

    def test_fallback_missing_platform_and_benchmark_classifies_as_basic_constraints(self, mock_console) -> None:
        mock_config = MagicMock()
        mock_config.get.return_value = None

        resolution = resolve_tuning(
            tuning_arg="tuned",
            platform=None,
            benchmark=None,
            config_manager=mock_config,
            console=mock_console,
        )
        assert resolution.source == TuningSource.FALLBACK

        status = status_from_log_text(_resolution_log_text(resolution))
        assert status == BASIC_CONSTRAINTS

    def test_auto_discovered_template_classifies_as_tuned_template(self, mock_console, tmp_path) -> None:
        platform_dir = tmp_path / "duckdb"
        platform_dir.mkdir()
        (platform_dir / "tpch_tuned.yaml").write_text("primary_keys:\n  enabled: true\n", encoding="utf-8")

        mock_config = MagicMock()
        mock_config.get.return_value = None

        with patch.dict(os.environ, {"BENCHBOX_TUNING_PATH": str(tmp_path)}):
            resolution = resolve_tuning(
                tuning_arg="tuned",
                platform="duckdb",
                benchmark="tpch",
                config_manager=mock_config,
                console=mock_console,
            )
        assert resolution.source == TuningSource.AUTO_DISCOVERED

        status = status_from_log_text(_resolution_log_text(resolution))
        assert status == TUNED_TEMPLATE

    def test_auto_mode_is_not_misclassified_as_any_coverage_status(self, mock_console) -> None:
        # `--tuning auto`'s info message ("Tuning mode: auto (using smart
        # defaults...)") doesn't correspond to any of coverage.py's three
        # UAT-log statuses -- it's a distinct resolution mode entirely. Pin
        # that the parser correctly reports "no opinion" (None) rather than
        # accidentally substring-matching one of the three markers.
        resolution = resolve_tuning(
            tuning_arg="auto",
            platform="duckdb",
            benchmark="tpch",
            config_manager=MagicMock(get=lambda *_a, **_kw: None),
            console=mock_console,
        )
        assert resolution.mode == TuningMode.AUTO

        status = status_from_log_text(_resolution_log_text(resolution))
        assert status is None

    def test_explicit_file_mode_is_not_misclassified_as_any_coverage_status(self, mock_console, tmp_path) -> None:
        custom_file = tmp_path / "custom_tuning.yaml"
        custom_file.write_text("primary_keys:\n  enabled: true\n", encoding="utf-8")

        resolution = resolve_tuning(
            tuning_arg=str(custom_file),
            platform="duckdb",
            benchmark="tpch",
            config_manager=MagicMock(get=lambda *_a, **_kw: None),
            console=mock_console,
        )
        assert resolution.mode == TuningMode.CUSTOM_FILE

        status = status_from_log_text(_resolution_log_text(resolution))
        assert status is None
