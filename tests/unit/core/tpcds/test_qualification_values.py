"""The committed TPC-DS qualification values agree with the specification and render real SQL.

The values are the "Qualification Substitution Parameters" of Appendix B of the TPC-DS 4.0.0
specification, keyed by the names ``dsqgen -LOG`` writes. The expected literals below were copied from
the specification text, so a change to the data file that disagrees with the specification fails here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium, pytest.mark.tpcds]

DATA_FILE = (
    Path(__file__).resolve().parents[4]
    / "benchbox"
    / "core"
    / "tpcds"
    / "dataframe_queries"
    / "qualification_values.json"
)

# (query, name, value) as printed in Appendix B.
SPEC_SAMPLE = [
    (1, "YEAR.01", "2000"),
    (1, "STATE.01", "TN"),
    (1, "AGG_FIELD.01", "SR_RETURN_AMT"),
    (3, "MONTH.01", "11"),
    (3, "MANUFACT.01", "128"),
    (3, "AGGC.01", "ss_ext_sales_price"),
    (5, "SALES_DATE.01", "2000-08-23"),
    (7, "ES.01", "College"),
    (8, "ZIP.01", "24128"),
    (8, "ZIP.81", "57834"),
    (9, "RC.05", "165306"),
    (14, "DAY.01", "11"),
    (39, "YEAR.01", "2001"),
    (39, "MONTH.01", "1"),
    (41, "MANUFACT.01", "738"),
    (41, "SIZE.02", "extra large"),
    (44, "STORE.01", "4"),
    (44, "NULLCOLSS.01", "ss_addr_sk"),
    (47, "ORDERBY.01", "s_store_name"),
    (72, "YEAR.01", "1999"),
    (88, "STORE.01", "Unknown"),
    (93, "REASON.01", "reason 28"),
]

EMPTY_AT_SF1 = (8, 24, 25, 29, 37, 41, 54, 58)


@pytest.fixture(scope="module")
def document():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def test_every_query_has_values(document):
    assert sorted(map(int, document["values"])) == list(range(1, 100))
    assert all(values for values in document["values"].values())


@pytest.mark.parametrize(("query_id", "name", "expected"), SPEC_SAMPLE)
def test_sampled_values_match_the_specification_text(document, query_id, name, expected):
    assert document["values"][str(query_id)][name] == expected


def test_no_value_swallowed_a_comment_that_follows_it_in_the_specification(document):
    """Appendix B puts prose comments after some parameter lists (Q72's note on the 5-day offset)."""
    offenders = {
        (query_id, name): value
        for query_id, values in document["values"].items()
        for name, value in values.items()
        if "Comment" in value or len(value) > 80
    }
    assert offenders == {}


def test_q8_carries_all_four_hundred_zip_codes(document):
    zips = {name for name in document["values"]["8"] if name.startswith("ZIP.")}
    assert zips == {f"ZIP.{index:02d}" for index in range(1, 401)}


def test_a_name_the_template_does_not_define_is_recorded_not_kept(document):
    """Appendix B lists MANAGER.01 for Q71, but the template hard-codes the manager."""
    assert document["not_in_template"] == {"71": ["MANAGER.01"]}
    assert "MANAGER.01" not in document["values"]["71"]


@pytest.fixture(scope="module")
def dsqgen():
    from benchbox.core.tpcds.c_tools import DSQGenBinary

    try:
        return DSQGenBinary()
    except Exception as exc:  # no bundled binary for this platform
        pytest.skip(f"dsqgen is not available: {exc}")


def test_every_query_renders_from_the_specification_values_independent_of_the_seed(document, dsqgen):
    for query_id in range(1, 100):
        values = document["values"][str(query_id)]
        first = dsqgen.generate_with_parameters(query_id, values, scale_factor=1.0, seed=1)
        second = dsqgen.generate_with_parameters(query_id, values, scale_factor=1.0, seed=99)
        assert first == second, f"Q{query_id} still depends on the seed"


def test_the_queries_empty_at_scale_factor_one_have_non_empty_official_answer_sets():
    """Those eight are parameter problems, not legitimately empty queries."""
    from benchbox.core.expected_results.loader import load_tpcds_expected_results

    try:
        expected = load_tpcds_expected_results(1.0)
    except FileNotFoundError as exc:
        pytest.skip(f"answer sets are not available: {exc}")

    assert {query_id: expected[str(query_id)] for query_id in EMPTY_AT_SF1} == {
        8: 5,
        24: 11,
        25: 1,
        29: 1,
        37: 1,
        41: 4,
        54: 1,
        58: 3,
    }
