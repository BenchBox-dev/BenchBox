from __future__ import annotations

from datetime import date

import pytest

from benchbox.core.tpch import parameter_extractor as pe

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.parametrize(
    ("query_id", "sql", "expected"),
    [
        (1, "... interval '68' day ...", {"delta": 68, "cutoff_date": date(1998, 9, 24)}),
        (2, "where p_size = 38 and p_type like '%STEEL' and r_name = 'ASIA'", {"size": 38}),
        (
            6,
            "l_shipdate >= date '1993-01-01' and l_discount between 0.07 - 0.01 and 0.07 + 0.01 and l_quantity < 25",
            {"discount": 0.07, "quantity_limit": 25, "start_date": date(1993, 1, 1), "end_date": date(1994, 1, 1)},
        ),
        (
            16,
            "p_brand <> 'Brand#41' and p_type not like 'MEDIUM BURNISHED%' and p_size in (4, 22, 31)",
            {"brand": "Brand#41", "type_prefix": "MEDIUM BURNISHED", "sizes": [4, 22, 31]},
        ),
        (22, "substring(c_phone from 1 for 2) in ('24', '33', '31')", {"country_codes": ["24", "33", "31"]}),
    ],
)
def test_extractors_parse_expected_values(query_id: int, sql: str, expected: dict[str, object]) -> None:
    params = pe._extract_query_params(query_id, sql)

    assert params is not None
    for key, value in expected.items():
        assert params[key] == value


def test_extract_query_params_unknown_query_returns_none() -> None:
    assert pe._extract_query_params(999, "select 1") is None


def test_extract_query_params_handles_extractor_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_extractor(_: str) -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setitem(pe._EXTRACTORS, 99, failing_extractor)

    assert pe._extract_query_params(99, "select 1") is None


def test_extractors_use_defaults_when_patterns_missing() -> None:
    q7 = pe._extract_query_params(7, "no nation filters")
    q18 = pe._extract_query_params(18, "no threshold")
    q20 = pe._extract_query_params(20, "no match")

    assert q7 == {"nation1": "FRANCE", "nation2": "GERMANY"}
    assert q18 == {"quantity_threshold": 300}
    assert q20 == {
        "color_prefix": "forest",
        "nation_name": "CANADA",
        "start_date": date(1994, 1, 1),
        "end_date": date(1995, 1, 1),
    }


def test_date_helpers() -> None:
    assert pe._parse_date("1995-03-17") == date(1995, 3, 17)
    assert pe._add_months(date(1995, 11, 1), 3) == date(1996, 2, 1)
    assert pe._add_years(date(1995, 3, 17), 1) == date(1996, 3, 17)


def test_extract_tpch_parameters_collects_successes(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeQGen:
        def generate(self, query_id: int, seed: int, scale_factor: float) -> str:
            assert seed == 11
            assert scale_factor == 0.01
            if query_id == 1:
                return "interval '7' day"
            raise RuntimeError("missing")

    import benchbox.core.tpch.queries as queries

    monkeypatch.setattr(queries, "QGenBinary", FakeQGen)

    params = pe.extract_tpch_parameters(seed=11, scale_factor=0.01)

    assert params == {1: {"delta": 7, "cutoff_date": date(1998, 11, 24)}}


def test_get_tpch_extracted_parameters_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, float]] = []

    def fake_extract(seed: int, scale_factor: float) -> dict[int, dict[str, object]]:
        calls.append((seed, scale_factor))
        return {1: {"seed": seed, "sf": scale_factor}}

    monkeypatch.setattr(pe, "extract_tpch_parameters", fake_extract)
    pe.clear_cache()

    first = pe.get_tpch_extracted_parameters(123, 0.1, use_cache=True)
    second = pe.get_tpch_extracted_parameters(123, 0.1, use_cache=True)
    third = pe.get_tpch_extracted_parameters(123, 0.1, use_cache=False)

    assert first == second == third
    assert calls == [(123, 0.1), (123, 0.1)]
