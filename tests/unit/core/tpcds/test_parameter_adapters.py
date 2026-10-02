"""Tests for the TPC-DS parameter adapters and their wiring into the cross-surface gate builder."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from benchbox.core.tpcds.dataframe_queries.parameter_adapters import (
    ADAPTERS,
    adapter_query_ids,
    bind_parameters,
)

pytestmark = [pytest.mark.unit, pytest.mark.medium, pytest.mark.tpcds]


class _StubDSQGen:
    """Stands in for DSQGenBinary: returns fixed logged values and records how it was called."""

    def __init__(self, substitutions, binary_path):
        self.substitutions = substitutions
        self.dsqgen_path = binary_path
        self.calls = []

    def generate_parameter_log(self, query_id, **kwargs):
        self.calls.append((query_id, kwargs))
        return SimpleNamespace(substitutions=self.substitutions)


class TestAdapters:
    def test_q39_reproduces_the_templates_month_arithmetic(self):
        # The SQL compares MONTH with MONTH+1; -LOG records only MONTH.01.
        assert ADAPTERS[39]({"YEAR.01": "1998", "MONTH.01": "4"}) == {"year": 1998, "months": [4, 5]}

    def test_q44_takes_the_store_and_the_null_column(self):
        assert ADAPTERS[44]({"STORE.01": "1", "NULLCOLSS.01": "ss_hdemo_sk"}) == {
            "store_sk": 1,
            "null_col": "ss_hdemo_sk",
        }

    def test_q49_supplies_the_month_the_defaults_file_lacks(self):
        assert ADAPTERS[49]({"YEAR.01": "2000", "MONTH.01": "12"}) == {"year": 2000, "month": 12}

    def test_q93_takes_the_reason_text(self):
        assert ADAPTERS[93]({"REASON.01": "Did not like the warranty"}) == {"reason": "Did not like the warranty"}

    def test_q41_the_negative_control_has_no_adapter(self):
        assert 41 not in ADAPTERS
        assert adapter_query_ids() == (39, 44, 49, 93)


class TestBinding:
    def test_binding_records_where_the_values_came_from(self, tmp_path):
        binary = tmp_path / "dsqgen"
        binary.write_bytes(b"binary bytes")
        dsqgen = _StubDSQGen({"STORE.01": "3", "NULLCOLSS.01": "ss_addr_sk"}, binary)

        binding = bind_parameters(44, scale_factor=0.1, seed=11, stream_id=2, dsqgen=dsqgen)

        assert binding.parameters == {"store_sk": 3, "null_col": "ss_addr_sk"}
        assert (binding.query_id, binding.scale_factor, binding.seed, binding.stream_id) == (44, 0.1, 11, 2)
        assert dict(binding.logged) == {"STORE.01": "3", "NULLCOLSS.01": "ss_addr_sk"}
        assert len(binding.dsqgen_sha256) == 64
        assert dsqgen.calls == [(44, {"seed": 11, "scale_factor": 0.1, "stream_id": 2})]

    def test_a_query_without_an_adapter_does_not_fall_back_to_the_defaults(self, tmp_path):
        with pytest.raises(KeyError, match="Q41 has no parameter adapter"):
            bind_parameters(41, scale_factor=1.0, dsqgen=_StubDSQGen({}, tmp_path / "dsqgen"))

    def test_a_value_dsqgen_did_not_log_is_reported(self, tmp_path):
        binary = tmp_path / "dsqgen"
        binary.write_bytes(b"x")

        with pytest.raises(ValueError, match="did not log 'MONTH.01' for Q39"):
            bind_parameters(39, scale_factor=1.0, dsqgen=_StubDSQGen({"YEAR.01": "2000"}, binary))


@pytest.fixture(scope="module")
def dsqgen():
    from benchbox.core.tpcds.c_tools import DSQGenBinary, TPCDSError

    try:
        return DSQGenBinary()
    except (TPCDSError, FileNotFoundError, RuntimeError) as exc:
        pytest.skip(f"dsqgen binary or templates unavailable: {exc}")


@pytest.mark.parametrize("scale_factor", [0.01, 1.0])
def test_adapted_values_are_the_values_in_the_sql_for_the_same_seed_and_scale(dsqgen, scale_factor):
    """The point of an adapter: the DataFrame side runs on exactly what the SQL contains."""

    def squashed(query_id):
        return "".join(dsqgen.generate(query_id, seed=7, scale_factor=scale_factor).split())

    def bound(query_id):
        return bind_parameters(query_id, scale_factor=scale_factor, seed=7, dsqgen=dsqgen).parameters

    q39, q44, q49, q93 = bound(39), bound(44), bound(49), bound(93)
    assert f"d_year={q39['year']}" in squashed(39)
    assert f"inv1.d_moy={q39['months'][0]}" in squashed(39)
    assert f"inv2.d_moy={q39['months'][0]}+1" in squashed(39)
    assert f"ss_store_sk={q44['store_sk']}" in squashed(44)
    assert f"{q44['null_col']}isnull" in squashed(44)
    assert f"d_year={q49['year']}" in squashed(49)
    assert f"d_moy={q49['month']}" in squashed(49)
    assert "r_reason_desc='" + "".join(q93["reason"].split()) + "'" in squashed(93)


def test_binding_follows_the_seed_and_the_scale(dsqgen):
    seeds = {bind_parameters(39, scale_factor=1.0, seed=seed, dsqgen=dsqgen).parameters["year"] for seed in range(1, 9)}
    assert len(seeds) > 1
    # Q44's store is drawn from the store table's row count, so it follows the scale.
    stores = {
        bind_parameters(44, scale_factor=scale, seed=7, dsqgen=dsqgen).parameters["store_sk"] for scale in (0.01, 1, 10)
    }
    assert len(stores) == 3


class TestGateBuilderWiring:
    @pytest.fixture
    def builder(self, monkeypatch, tmp_path):
        import benchbox.core.equivalence.builders.base as base
        import benchbox.tpcds as tpcds_module
        from benchbox.core.equivalence.builders.tpcds import build_tpcds_duckdb
        from benchbox.core.tpcds.dataframe_queries import parameters

        class FakeBenchmark:
            def __init__(self, scale_factor, output_dir, **_):
                self.scale_factor = scale_factor

            def generate_data(self):
                return []

            def get_queries(self, dialect=None, **_):
                return {str(query_id): "select 1" for query_id in (39, 41, 44)}

        monkeypatch.setattr(tpcds_module, "TPCDS", FakeBenchmark)
        monkeypatch.setattr(base, "_load_duckdb_cell", lambda *args, **kwargs: object())
        yield build_tpcds_duckdb(0.01, tmp_path)
        parameters.set_parameter_overrides(None)

    def test_an_adapted_query_runs_on_the_values_dsqgen_put_in_the_sql(self, builder, dsqgen):
        from benchbox.core.tpcds.dataframe_queries.parameters import get_parameters

        builder.dataframe_query("39")

        binding = builder.dataframe_query.bindings[39]
        assert get_parameters(39).get("months") == binding.parameters["months"]
        assert get_parameters(39).get("year") == binding.parameters["year"]
        assert (binding.scale_factor, binding.seed, binding.stream_id) == (0.01, None, 0)
        assert re.fullmatch(r"[0-9a-f]{64}", binding.dsqgen_sha256)

    def test_overrides_do_not_leak_from_one_query_to_the_next(self, builder, dsqgen):
        from benchbox.core.tpcds.dataframe_queries.parameters import TPCDS_DEFAULT_PARAMS, get_parameters

        builder.dataframe_query("44")
        builder.dataframe_query("41")  # no adapter: the defaults apply again

        assert get_parameters(44).get("store_sk") == TPCDS_DEFAULT_PARAMS[44]["store_sk"]
        assert 41 not in builder.dataframe_query.bindings
