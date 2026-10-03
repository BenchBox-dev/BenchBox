# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-H specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import pytest

from benchbox.core.tpch.benchmark import TPCH_SF1_REFERENCE_SEED
from benchbox.core.tpch.power_test import TPCHPowerTestConfig

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.unit
class TestReferenceSeedConstant:
    def test_reference_seed_matches_octal(self):
        assert TPCH_SF1_REFERENCE_SEED == 17039360
        assert TPCH_SF1_REFERENCE_SEED == 0o0101000000

    def test_reference_seed_is_not_16843008(self):
        assert TPCH_SF1_REFERENCE_SEED != 16843008


@pytest.mark.unit
class TestPowerTestConfigDefaults:
    def test_default_seed_is_none(self):
        config = TPCHPowerTestConfig()
        assert config.seed is None

    def test_explicit_seed_preserved(self):
        config = TPCHPowerTestConfig(seed=42)
        assert config.seed == 42

        config_ref = TPCHPowerTestConfig(seed=TPCH_SF1_REFERENCE_SEED)
        assert config_ref.seed == TPCH_SF1_REFERENCE_SEED


@pytest.mark.unit
@pytest.mark.tpch
class TestQgenDefaultsMode:
    @pytest.fixture
    def qgen(self):
        try:
            from benchbox.core.tpch.queries import QGenBinary

            return QGenBinary()
        except RuntimeError:
            pytest.skip("qgen binary not available")

    def test_defaults_mode_q3_contains_building(self, qgen):
        sql = qgen.generate(query_id=3, seed=None, scale_factor=1.0)
        assert "BUILDING" in sql.upper(), f"Expected BUILDING in Q3 defaults output, got: {sql[:200]}"

    def test_seed1_q3_contains_furniture(self, qgen):
        sql = qgen.generate(query_id=3, seed=1, scale_factor=1.0)
        assert "FURNITURE" in sql.upper(), f"Expected FURNITURE in Q3 seed=1 output, got: {sql[:200]}"

    def test_defaults_mode_differs_from_seed1(self, qgen):
        sql_defaults = qgen.generate(query_id=3, seed=None, scale_factor=1.0)
        sql_seed1 = qgen.generate(query_id=3, seed=1, scale_factor=1.0)
        assert sql_defaults != sql_seed1, "Defaults mode and seed=1 should produce different SQL"

    def test_defaults_mode_q6_discount(self, qgen):
        sql = qgen.generate(query_id=6, seed=None, scale_factor=1.0)
        assert ".06" in sql, f"Expected .06 discount in Q6 defaults output, got: {sql[:200]}"

    def test_defaults_mode_q5_asia(self, qgen):
        sql = qgen.generate(query_id=5, seed=None, scale_factor=1.0)
        assert "ASIA" in sql.upper(), f"Expected ASIA in Q5 defaults output, got: {sql[:200]}"
