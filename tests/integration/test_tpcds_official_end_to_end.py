"""End-to-end guard: a ``--official`` TPC-DS run stays submittable.

The defect this pins (TODO ``tpcds-can-never-be-published-official-flag-not-wired``)
was that ``official`` never reached
:func:`benchbox.core.tpcds.compliance.classify_tpcds_run`, so every TPC-DS run
classified as ``unofficial_nonstandard`` and ``benchbox submit`` refused it. The
existing unit tests could not catch it because they construct the benchmark
themselves and so bypass the caller that dropped the flag.

These tests therefore use the production construction path
(:func:`benchbox.core.benchmark_loader.get_benchmark_instance`) and follow the
value all the way to the publish admission decision, with no stub standing in
for a seam. They deliberately stop short of generating TPC-DS data: the defect
lives in configuration threading and serialization, not in query execution, and
an SF1 data generation does not belong in the integration lane.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchbox.core.benchmark_loader import get_benchmark_instance
from benchbox.core.config import BenchmarkConfig
from benchbox.core.publishing.admission import publish_admission
from benchbox.core.results.loader import load_result_file, reconstruct_benchmark_results
from benchbox.core.results.query_normalizer import normalize_query_result
from benchbox.core.results.result_factory import build_enhanced_benchmark_result
from benchbox.core.results.schema import build_result_payload

pytestmark = [pytest.mark.integration, pytest.mark.fast]

# The lowest official TPC-DS scale point; below it every run is subscale.
OFFICIAL_SCALE = 1.0
PUBLISH_LABEL = "maintainer-run"


def _clean_query_results() -> list[dict[str, Any]]:
    """One passing query — enough to keep the result a clean pass."""
    return [{"query_id": "1", "execution_time": 0.01, "success": True, "row_count": 1}]


def _bundle_payload(*, official: bool, scale_factor: float = OFFICIAL_SCALE) -> dict[str, Any]:
    """Build a result bundle the way a real run does, from config to payload."""
    config = BenchmarkConfig(
        name="tpcds",
        display_name="TPC-DS",
        scale_factor=scale_factor,
        official=official,
    )
    # The production construction path. Substituting a hand-built benchmark
    # here would reintroduce exactly the blind spot this test exists to close.
    benchmark = get_benchmark_instance(config, None)
    result = build_enhanced_benchmark_result(
        benchmark=benchmark,
        platform="duckdb",
        query_results=_clean_query_results(),
        validation_status="PASSED",
    )
    return build_result_payload(result)


def test_official_run_emits_official_compliance_class() -> None:
    payload = _bundle_payload(official=True)

    assert payload["benchmark"]["compliance_class"] == "official"


def test_official_bundle_survives_a_json_round_trip_and_passes_submit(tmp_path: Path) -> None:
    payload = _bundle_payload(official=True)
    bundle = tmp_path / "tpcds_sf1_duckdb_official.json"
    bundle.write_text(json.dumps(payload, default=str), encoding="utf-8")

    loaded, _raw = load_result_file(bundle)

    assert loaded.compliance_class == "official"
    decision = publish_admission(loaded, PUBLISH_LABEL)
    assert decision.allowed, f"official TPC-DS refused: {decision.code} ({decision.reason})"


@pytest.mark.parametrize(
    ("official", "scale_factor", "expected_class"),
    [
        # The regression itself: the flag dropped on the way to the classifier.
        (False, OFFICIAL_SCALE, "unofficial_nonstandard"),
        # --official cannot launder a non-official scale point.
        (True, 0.5, "unofficial_subscale"),
        (True, 2.0, "unofficial_nonstandard"),
    ],
)
def test_unofficial_runs_are_refused_for_compliance(official: bool, scale_factor: float, expected_class: str) -> None:
    payload = _bundle_payload(official=official, scale_factor=scale_factor)
    loaded = reconstruct_benchmark_results(payload)

    assert loaded.compliance_class == expected_class
    decision = publish_admission(loaded, PUBLISH_LABEL)
    assert not decision.allowed
    # Refused for the compliance class, not incidentally for something else.
    assert decision.code == "unofficial_compliance"


def _dataframe_platform_input():
    """The same platform block the DataFrame builders construct."""
    from benchbox.core.results.result_factory import _build_platform_input

    return _build_platform_input("polars", {"execution_mode": "dataframe"}, {})


def _dataframe_compliance(*, official: bool, scale_factor: float = OFFICIAL_SCALE) -> str | None:
    """What the DataFrame builders will stamp on the bundle, same inputs.

    Both DataFrame result builders construct `BenchmarkInfoInput` themselves
    rather than going through `build_enhanced_benchmark_result`, so the SQL
    assertions above say nothing about them. They also build from the CONFIG,
    not the benchmark instance, which is why threading `official` through the
    config in PR #1770 could never reach them.
    """
    from benchbox.core.runner.dataframe_runner import dataframe_compliance_class

    config = BenchmarkConfig(
        name="tpcds",
        display_name="TPC-DS",
        scale_factor=scale_factor,
        official=official,
    )
    return dataframe_compliance_class(get_benchmark_instance(config, None), config)


@pytest.mark.parametrize(
    ("official", "scale_factor", "expected_class"),
    [
        (True, OFFICIAL_SCALE, "official"),
        (False, OFFICIAL_SCALE, "unofficial_nonstandard"),
        (True, 0.5, "unofficial_subscale"),
        (True, 2.0, "unofficial_nonstandard"),
    ],
)
def test_the_dataframe_path_classifies_identically_to_the_sql_path(
    official: bool, scale_factor: float, expected_class: str
) -> None:
    """The two paths must agree. Before this, DataFrame emitted nothing at all.

    An absent `compliance_class` is refused by `benchbox submit` for TPC-DS, so
    no DataFrame result could ever be published however the user invoked it --
    roughly half the public corpus is DataFrame mode.
    """
    assert _dataframe_compliance(official=official, scale_factor=scale_factor) == expected_class


def test_the_dataframe_value_is_the_plain_wire_string_not_an_enum_repr() -> None:
    """`str(TpcdsComplianceClass.OFFICIAL)` is the repr, not `official`.

    The submit and admission gates compare against the plain value, so an enum
    repr would be refused just as surely as an absent field -- and would look
    correct in a diff.
    """
    value = _dataframe_compliance(official=True)

    assert value == "official"
    assert "TpcdsComplianceClass" not in str(value)


def test_a_dataframe_official_bundle_is_not_refused_for_compliance(tmp_path: Path) -> None:
    """Classification is official while absent validation remains non-clean."""
    from benchbox.core.results.builder import BenchmarkInfoInput, ResultBuilder

    builder = ResultBuilder(
        benchmark=BenchmarkInfoInput(
            name="TPC-DS",
            scale_factor=OFFICIAL_SCALE,
            test_type="power",
            benchmark_id="tpcds",
            display_name="TPC-DS",
            compliance_class=_dataframe_compliance(official=True),
        ),
        platform=_dataframe_platform_input(),
    )
    builder.mark_started()
    builder.set_validation_status("NOT_RUN")
    for query_result in _clean_query_results():
        builder.add_query_result(normalize_query_result(query_result))
    builder.mark_completed()

    bundle = tmp_path / "tpcds_sf1_polars_df_official.json"
    bundle.write_text(json.dumps(build_result_payload(builder.build()), default=str), encoding="utf-8")
    loaded, _raw = load_result_file(bundle)

    assert loaded.compliance_class == "official"
    decision = publish_admission(loaded, PUBLISH_LABEL)
    assert not decision.allowed
    assert decision.code == "non_clean"
    assert decision.reason == "validation_status=not_run"
