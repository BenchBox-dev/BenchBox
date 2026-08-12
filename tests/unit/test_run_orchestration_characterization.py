"""Characterization of run orchestration, ahead of the core run service.

`one-engine-core-run-service` extracts run orchestration into `benchbox.core`
below both surfaces. This module pins the shared execution-type behavior so
both surfaces remain reviewable and cannot silently diverge again.

The CLI wrapper and MCP execution both derive a benchmark's execution type from
`benchbox/core/run_service.py::_map_phases_to_execution_type`. Mixed
query-phase requests use `combined`, ensuring the runner executes every
requested query phase.
"""

from __future__ import annotations

import itertools

import pytest

from benchbox.core.constants import QUERY_PHASES, VALID_PHASES

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _cli_derive(phases: list[str]) -> str:
    from benchbox.cli.commands.run import _derive_execution_type

    return _derive_execution_type(phases)


def _mcp_derive(phases: list[str]) -> str:
    from benchbox.core.run_service import _map_phases_to_execution_type

    return _map_phases_to_execution_type(phases)


def _all_phase_subsets() -> list[list[str]]:
    subsets = []
    for size in range(1, len(VALID_PHASES) + 1):
        subsets.extend(list(combo) for combo in itertools.combinations(VALID_PHASES, size))
    return subsets


ALL_SUBSETS = _all_phase_subsets()


class TestExecutionTypeAgreement:
    """The cases both surfaces already get right. Extraction must keep these."""

    @pytest.mark.parametrize(
        ("phases", "expected"),
        [
            (["generate"], "data_only"),
            (["load"], "load_only"),
            (["generate", "load"], "load_only"),
            (["power"], "power"),
            (["throughput"], "throughput"),
            (["maintenance"], "maintenance"),
            (["load", "power"], "power"),
            (["generate", "load", "power"], "power"),
            (["power", "throughput", "maintenance"], "combined"),
            (["statistics"], "standard"),
            (["warmup"], "standard"),
        ],
    )
    def test_both_surfaces_derive_the_documented_type(self, phases: list[str], expected: str):
        assert _cli_derive(phases) == expected
        assert _mcp_derive(phases) == expected

    def test_the_default_phase_selection_agrees(self):
        """`load,power` is the documented MCP default and the common CLI case."""
        assert _cli_derive(["load", "power"]) == _mcp_derive(["load", "power"]) == "power"

    @pytest.mark.parametrize("query_phase", QUERY_PHASES)
    def test_every_single_query_phase_agrees(self, query_phase: str):
        assert _cli_derive([query_phase]) == _mcp_derive([query_phase]) == query_phase

    def test_all_three_query_phases_agree(self):
        phases = list(QUERY_PHASES)

        assert _cli_derive(phases) == _mcp_derive(phases) == "combined"


class TestExecutionTypeParity:
    """Mixed query-phase requests remain combined on both surfaces."""

    TWO_QUERY_PHASE_SUBSETS = [list(combo) for combo in itertools.combinations(QUERY_PHASES, 2)]

    @pytest.mark.parametrize("phases", TWO_QUERY_PHASE_SUBSETS)
    def test_cli_treats_two_query_phases_as_combined(self, phases: list[str]):
        assert _cli_derive(phases) == "combined"

    @pytest.mark.parametrize("phases", TWO_QUERY_PHASE_SUBSETS)
    def test_mcp_treats_two_query_phases_as_combined(self, phases: list[str]):
        assert _mcp_derive(phases) == "combined"

    def test_no_phase_subset_diverges(self):
        """All phase subsets agree across CLI and MCP."""
        diverging = [phases for phases in ALL_SUBSETS if _cli_derive(phases) != _mcp_derive(phases)]

        assert len(ALL_SUBSETS) == 127
        assert diverging == []

    def test_every_subset_including_two_query_phases_agrees(self):
        agreeing = [phases for phases in ALL_SUBSETS if _cli_derive(phases) == _mcp_derive(phases)]

        assert len(agreeing) == len(ALL_SUBSETS)


class TestPhaseParsingCharacterization:
    """Phase admission, which the run service will own for both surfaces."""

    @pytest.mark.parametrize("phase", VALID_PHASES)
    def test_mcp_admits_every_valid_phase(self, phase: str):
        from benchbox.mcp.schemas import validate_phases

        assert validate_phases(phase) == phase

    def test_derivation_is_order_independent(self):
        """A run service must not depend on the order phases were typed in."""
        for phases in (["power", "load"], ["maintenance", "generate", "throughput"]):
            assert _cli_derive(phases) == _cli_derive(sorted(phases))
            assert _mcp_derive(phases) == _mcp_derive(sorted(phases))

    def test_an_empty_phase_list_is_standard_on_both_surfaces(self):
        assert _cli_derive([]) == _mcp_derive([]) == "standard"
