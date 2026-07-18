"""Shared Python<->TypeScript `tuning_mode` vocabulary pin (ADR-2).

From the 2026-07-12 tuning review, finding R7 / ADR-002
(docs/development/tuning-adr-002-mode-vocabulary-fallback-facets.md): there
was no single shared source for the pinned `tuning_mode` vocabulary, so
`benchbox/cli/tuning.py` (`tuned`/`notuning`/`auto`/`balanced`) and
`results-explorer/src/components/TuningBadge.tsx` (`tuned`/`notuning`/`auto`)
independently hardcoded different, non-agreeing sets.

ADR-2 §2 pins the vocabulary as *exactly* `{tuned, tuned-fallback, notuning,
auto, custom}` plus a distinct "not recorded" state for absent/legacy data,
and requires "a single shared artifact consumed by both the Python and
TypeScript test suites, so the two sides cannot drift independently again".

This module is the Python half of that pin:
`tests/unit/core/tuning/fixtures/tuning_mode_vocabulary.yaml` is the shared
artifact (note: not under a `data/` directory -- the repo's `.gitignore`
blanket-ignores any directory literally named `data/`, which would silently
drop this checked-in fixture); `results-explorer/src/lib/__tests__/tuningModeVocabulary.test.ts`
is the TypeScript half (it loads the *same* YAML file via a `uv run --
python -c` subprocess -- the same shell-out pattern already established by
`db-remediation-pin.test.ts` -- rather than hardcoding its own mirror, so
there is exactly one place the vocabulary is declared).

This pins the ADR-2 TARGET vocabulary as a test contract. `benchbox.core.tuning.modes`
is the production constants module that migrates emitters/consumers onto this
vocabulary (`tuning-mode-vocabulary-and-facet-implementation-20260712`); the
tests below assert it -- and `TuningResolution.canonical_mode` -- agree with
this fixture, so the two cannot drift apart again.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
import yaml
from click.testing import CliRunner

from benchbox.cli.main import cli
from benchbox.cli.tuning_resolver import TuningMode, TuningResolution, TuningSource
from benchbox.core.tuning import modes as tuning_modes

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# See tests/unit/cli/test_cli_data_load_modes.py for why this module-lookup
# dance (rather than string-based mock.patch targets) is needed on Python
# 3.10: benchbox.cli.commands re-exports `run` as a Click Command under the
# same name as the submodule.
__import__("benchbox.cli.commands.run")
_run_module = sys.modules["benchbox.cli.commands.run"]

VOCAB_PATH = Path(__file__).resolve().parent / "fixtures" / "tuning_mode_vocabulary.yaml"

# ADR-2 §2's decided vocabulary, in the order the ADR lists it.
EXPECTED_MODES = ["tuned", "tuned-fallback", "notuning", "auto", "custom"]
EXPECTED_NOT_RECORDED_SENTINEL = "not-recorded"


def _load_vocabulary_artifact() -> dict[str, Any]:
    return yaml.safe_load(VOCAB_PATH.read_text(encoding="utf-8"))


class TestSharedVocabularyArtifactMatchesADR2:
    def test_artifact_exists(self) -> None:
        assert VOCAB_PATH.exists(), (
            f"Shared vocabulary artifact missing at {VOCAB_PATH}; "
            "results-explorer/src/lib/__tests__/tuningModeVocabulary.test.ts loads this same "
            "file and will also fail if it moves. Keep it out of any 'data/' directory -- "
            "the repo .gitignore blanket-ignores those."
        )

    def test_modes_match_adr2_decided_set(self) -> None:
        spec = _load_vocabulary_artifact()
        assert spec["modes"] == EXPECTED_MODES

    def test_not_recorded_sentinel_matches_adr2(self) -> None:
        spec = _load_vocabulary_artifact()
        assert spec["not_recorded_sentinel"] == EXPECTED_NOT_RECORDED_SENTINEL

    def test_raw_file_paths_are_not_part_of_the_vocabulary(self) -> None:
        # ADR-2 §2: "Raw file paths are not a legal tuning_mode value under
        # any circumstance." Pin that no artifact entry looks like a path.
        spec = _load_vocabulary_artifact()
        for mode in spec["modes"]:
            assert "/" not in mode
            assert "\\" not in mode
            assert not mode.endswith(".yaml")

    def test_balanced_is_not_part_of_the_vocabulary(self) -> None:
        # ADR-2 §2: the wizard's "balanced" string is a template flavor
        # selector, not a tuning_mode value, and must not appear verbatim.
        spec = _load_vocabulary_artifact()
        assert "balanced" not in spec["modes"]


class TestProductionConstantsMatchTheSharedFixture:
    """`benchbox.core.tuning.modes` is production code, not just a test pin --
    assert it agrees with the shared fixture rather than only with the ADR
    text, so a future edit to one is caught by the other."""

    def test_modes_tuple_matches_fixture_order(self) -> None:
        spec = _load_vocabulary_artifact()
        assert list(tuning_modes.MODES) == spec["modes"] == EXPECTED_MODES

    def test_not_recorded_constant_matches_fixture(self) -> None:
        spec = _load_vocabulary_artifact()
        assert tuning_modes.NOT_RECORDED == spec["not_recorded_sentinel"] == EXPECTED_NOT_RECORDED_SENTINEL

    def test_named_constants_match_their_vocabulary_position(self) -> None:
        assert tuning_modes.TUNED == "tuned"
        assert tuning_modes.TUNED_FALLBACK == "tuned-fallback"
        assert tuning_modes.NOTUNING == "notuning"
        assert tuning_modes.AUTO == "auto"
        assert tuning_modes.CUSTOM == "custom"

    def test_is_canonical_mode_accepts_only_the_pinned_set(self) -> None:
        for mode in EXPECTED_MODES:
            assert tuning_modes.is_canonical_mode(mode)
        assert not tuning_modes.is_canonical_mode("balanced")
        assert not tuning_modes.is_canonical_mode("examples/tunings/duckdb/tpch_tuned.yaml")
        assert not tuning_modes.is_canonical_mode(tuning_modes.NOT_RECORDED)
        assert not tuning_modes.is_canonical_mode(None)


class TestCanonicalModeMapsResolutionsOntoTheSharedVocabulary:
    """`TuningResolution.canonical_mode` (ADR-2 §1) is the resolver-side
    production mapping onto this same pinned vocabulary."""

    def test_tuned_via_auto_discovered_template_is_tuned(self) -> None:
        resolution = TuningResolution(mode=TuningMode.TUNED, source=TuningSource.AUTO_DISCOVERED, enabled=True)
        assert resolution.canonical_mode == tuning_modes.TUNED

    def test_tuned_via_fallback_is_tuned_fallback(self) -> None:
        resolution = TuningResolution(mode=TuningMode.TUNED, source=TuningSource.FALLBACK, enabled=True)
        assert resolution.canonical_mode == tuning_modes.TUNED_FALLBACK

    def test_tuned_via_wizard_is_tuned_not_tuned_fallback(self) -> None:
        # ADR-2 §1: wizard-produced configs get `wizard` source provenance,
        # not the `tuned-fallback` mode -- the wizard actually configured a
        # real tuning setup, unlike a declined/no-template fallback.
        resolution = TuningResolution(mode=TuningMode.TUNED, source=TuningSource.INTERACTIVE_WIZARD, enabled=True)
        assert resolution.canonical_mode == tuning_modes.TUNED

    def test_tuned_via_explicit_config_file_default_is_tuned(self) -> None:
        resolution = TuningResolution(mode=TuningMode.TUNED, source=TuningSource.EXPLICIT_FILE, enabled=True)
        assert resolution.canonical_mode == tuning_modes.TUNED

    def test_tuned_via_packaged_resource_is_tuned_not_tuned_fallback(self) -> None:
        # #1188 added the packaged-template discovery tier (TuningSource.
        # PACKAGED_RESOURCE) as a last-resort template source when benchbox
        # runs outside a repo checkout. A packaged template is a genuine
        # curated template (just bundled with the package instead of found
        # under examples/tunings/), so this must map to plain `tuned`, not
        # `tuned-fallback` -- pinning the composition of that tier with
        # canonical_mode (only TUNED+FALLBACK is tuned-fallback).
        resolution = TuningResolution(mode=TuningMode.TUNED, source=TuningSource.PACKAGED_RESOURCE, enabled=True)
        assert resolution.canonical_mode == tuning_modes.TUNED

    def test_custom_file_is_custom_never_the_raw_path(self) -> None:
        resolution = TuningResolution(
            mode=TuningMode.CUSTOM_FILE,
            source=TuningSource.EXPLICIT_FILE,
            enabled=True,
            config_file=Path("/home/user/my-tuning.yaml"),
        )
        assert resolution.canonical_mode == tuning_modes.CUSTOM
        assert "/" not in resolution.canonical_mode

    def test_notuning_is_notuning(self) -> None:
        resolution = TuningResolution(mode=TuningMode.NOTUNING, source=TuningSource.BASELINE, enabled=False)
        assert resolution.canonical_mode == tuning_modes.NOTUNING

    def test_auto_is_auto(self) -> None:
        resolution = TuningResolution(mode=TuningMode.AUTO, source=TuningSource.SMART_DEFAULTS, enabled=True)
        assert resolution.canonical_mode == tuning_modes.AUTO

    def test_canonical_mode_is_always_a_pinned_vocabulary_value(self) -> None:
        for mode in TuningMode:
            for source in TuningSource:
                resolution = TuningResolution(mode=mode, source=source, enabled=True)
                assert tuning_modes.is_canonical_mode(resolution.canonical_mode)


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Click command mock.patch requires Python 3.11+ for attribute access",
)
class TestFallbackLabelingEndToEnd:
    """ADR-2 §1 end-to-end: a `--tuning tuned` run that finds no template is
    recorded with the distinct `tuned-fallback` mode, and `--official` refuses
    it outright rather than silently submitting an unoptimized config as if
    it were a genuine tuned run."""

    def _invoke(self, tmp_path, monkeypatch, *, official: bool = False, scale: str = "0.01"):
        # Force template discovery to miss across every tier in
        # get_tuning_template_paths(): BENCHBOX_TUNING_PATH pointed at a
        # nonexistent directory, an empty cwd (so the project-relative and
        # cwd-relative candidates miss too), and `coffeeshop` as the
        # benchmark -- unlike tpch, it has no template under
        # examples/tunings/duckdb/ *and* no packaged template under
        # benchbox/core/tuning/templates/duckdb/ (the #1188 last-resort
        # tier, which ships templates for tpch/tpcds/ssb/etc. and would
        # otherwise resolve this to TuningSource.PACKAGED_RESOURCE instead
        # of FALLBACK).
        monkeypatch.setenv("BENCHBOX_TUNING_PATH", str(tmp_path / "no-such-tuning-dir"))
        monkeypatch.chdir(tmp_path)

        with ExitStack() as stack:
            bench_mgr = stack.enter_context(patch.object(_run_module, "BenchmarkManager"))
            profiler = stack.enter_context(patch.object(_run_module, "SystemProfiler"))
            orchestrator = stack.enter_context(patch.object(_run_module, "BenchmarkOrchestrator"))
            exporter = stack.enter_context(patch.object(_run_module, "ResultExporter"))
            db_mgr = stack.enter_context(patch.object(_run_module, "DatabaseManager"))

            bench_mgr.return_value.benchmarks = {
                "coffeeshop": {"display_name": "CoffeeShop", "estimated_time_range": (2, 10)}
            }
            profiler.return_value.get_system_profile.return_value = Mock()

            mock_db_cfg = Mock()
            mock_db_cfg.type = "duckdb"
            mock_db_cfg.options = {}
            mock_db_cfg.driver_version_actual = "1.4.3"
            mock_db_cfg.driver_version_resolved = "1.4.3"
            db_mgr.return_value.create_config.return_value = mock_db_cfg

            mock_result = Mock()
            mock_result.validation_status = "PASSED"
            mock_result.validation_details = {"stages": []}
            orchestrator.return_value.execute_benchmark.return_value = mock_result
            exporter.return_value.export_result.return_value = {"json": str(tmp_path / "result.json")}

            args = [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "coffeeshop",
                "--scale",
                scale,
                "--tuning",
                "tuned",
                "--non-interactive",
                "--output",
                str(tmp_path / "out"),
            ]
            if official:
                args.append("--official")
            result = CliRunner().invoke(cli, args)
            return result, orchestrator

    def test_duckdb_coffeeshop_has_no_template_anywhere(self) -> None:
        """Guard the premise of these e2e tests: if a duckdb/coffeeshop
        template is ever added (examples/tunings/ or the packaged tier),
        these tests would silently stop exercising the fallback path and
        must switch to a different platform/benchmark pair instead."""
        from benchbox.core.tuning.packaged_templates import packaged_template_path

        assert not Path("examples/tunings/duckdb/coffeeshop_tuned.yaml").exists()
        assert not packaged_template_path("duckdb", "coffeeshop").exists()

    def test_tuned_with_no_template_records_tuned_fallback(self, tmp_path, monkeypatch) -> None:
        result, orchestrator = self._invoke(tmp_path, monkeypatch, official=False)

        assert result.exit_code == 0, result.output
        orchestrator.return_value.execute_benchmark.assert_called_once()
        execution_context = orchestrator.return_value.execute_benchmark.call_args.kwargs["execution_context"]
        # ADR-2 §1/§2: the recorded mode is the canonical `tuned-fallback`
        # value, not `tuned` (which would silently facet-match a genuinely
        # curated-template run) and never the raw `--tuning` argument.
        assert execution_context.tuning_mode == tuning_modes.TUNED_FALLBACK

    def test_official_refuses_tuned_fallback(self, tmp_path, monkeypatch) -> None:
        # scale=1 is TPC-compliant, so the run reaches tuning resolution
        # instead of being rejected earlier by the official-mode scale gate.
        result, orchestrator = self._invoke(tmp_path, monkeypatch, official=True, scale="1")

        assert result.exit_code != 0
        assert "tuned-fallback" in result.output
        orchestrator.return_value.execute_benchmark.assert_not_called()
