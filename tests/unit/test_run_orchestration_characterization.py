"""Characterization of run orchestration, ahead of the core run service.

`one-engine-core-run-service` extracts run orchestration into
`benchbox.core` below both surfaces. Its first work unit is characterization,
and its anti-patterns require that extractions move code verbatim and that any
behavior delta be listed explicitly rather than discovered later.

This module pins what the two surfaces do TODAY, so the extraction can be proven
behavior-preserving -- or its deltas named. It deliberately does not fix
anything: the divergence recorded in TestExecutionTypeDivergence is a defect the
run service is expected to resolve, and pinning it first is what makes that
resolution reviewable instead of invisible.

Two independent implementations derive a benchmark's execution type from its
requested phases:

- `benchbox/cli/commands/run.py::_derive_execution_type`
- `benchbox/mcp/tools/benchmark.py::_map_phases_to_test_execution_type`

They agree on every single-query-phase request and every three-query-phase
request. They disagree on all 48 combinations that select exactly TWO of the
three query phases.
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
    from benchbox.mcp.tools.benchmark import _map_phases_to_test_execution_type

    return _map_phases_to_test_execution_type(phases)


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


class TestExecutionTypeDivergence:
    """KNOWN DEFECT, pinned so the run service must resolve it deliberately.

    Selecting exactly two of the three query phases gives different execution
    types on the two surfaces. The CLI returns `combined`, which its own comment
    explains is required so the adapter runs exactly the requested subset. MCP
    returns whichever single phase its if-chain tests first, so the other
    requested phase is silently dropped: `phases="power,throughput"` over MCP
    runs the power phase only.

    These tests assert the CURRENT behavior of both surfaces. When the core run
    service unifies them, these expectations must be updated in the same change,
    which is the point -- the delta becomes a reviewed edit rather than a silent
    one.
    """

    TWO_QUERY_PHASE_SUBSETS = [list(combo) for combo in itertools.combinations(QUERY_PHASES, 2)]

    @pytest.mark.parametrize("phases", TWO_QUERY_PHASE_SUBSETS)
    def test_cli_treats_two_query_phases_as_combined(self, phases: list[str]):
        assert _cli_derive(phases) == "combined"

    @pytest.mark.parametrize(
        ("phases", "mcp_result", "dropped"),
        [
            (["power", "throughput"], "power", "throughput"),
            (["power", "maintenance"], "power", "maintenance"),
            (["throughput", "maintenance"], "throughput", "maintenance"),
        ],
    )
    def test_mcp_silently_drops_the_second_query_phase(self, phases: list[str], mcp_result: str, dropped: str):
        derived = _mcp_derive(phases)

        assert derived == mcp_result
        assert dropped in phases
        assert derived != "combined", "MCP would have to return combined to honour both phases"

    def test_the_divergence_is_exactly_the_two_query_phase_case(self):
        """Bounds the defect: 48 of 127 subsets, all of them two-query-phase."""
        diverging = [phases for phases in ALL_SUBSETS if _cli_derive(phases) != _mcp_derive(phases)]

        assert len(ALL_SUBSETS) == 127
        assert len(diverging) == 48
        for phases in diverging:
            assert len(set(phases) & set(QUERY_PHASES)) == 2, phases

    def test_no_agreeing_subset_involves_two_query_phases(self):
        """The converse, so the bound cannot rot in one direction only."""
        agreeing = [phases for phases in ALL_SUBSETS if _cli_derive(phases) == _mcp_derive(phases)]

        assert len(agreeing) == 79
        for phases in agreeing:
            assert len(set(phases) & set(QUERY_PHASES)) != 2, phases


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
