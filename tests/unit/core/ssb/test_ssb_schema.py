"""Tests for benchbox.core.ssb.schema and SSBBenchmark's table load ordering.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.ssb.benchmark import SSBBenchmark
from benchbox.core.ssb.schema import TABLES, get_table_loading_order

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGetTableLoadingOrder:
    """Regression coverage for tuning-fk-load-ordering-fix-20260716.

    SSB's fact table (lineorder) has foreign keys into customer, part,
    supplier, and date (benchbox/core/ssb/schema_specs.yaml). Before this
    fix, SSBBenchmark had no get_table_loading_order, so
    benchbox/platforms/base/data_loading.py::DataLoader fell back to
    *alphabetical* order (customer, date, lineorder, part, supplier) --
    which loads lineorder before part/supplier and would violate FK
    references once examples/tunings/duckdb/ssb_tuned.yaml's
    foreign_keys.enabled/enforce_referential_integrity actually reaches the
    engine.
    """

    def test_includes_every_table_exactly_once(self):
        order = get_table_loading_order()
        assert sorted(order) == sorted(TABLES.keys())
        assert len(order) == len(set(order))

    def test_lineorder_loads_after_every_table_it_references(self):
        order = get_table_loading_order()
        position = {name: i for i, name in enumerate(order)}
        assert position["customer"] < position["lineorder"]
        assert position["part"] < position["lineorder"]
        assert position["supplier"] < position["lineorder"]
        assert position["date"] < position["lineorder"]

    def test_lineorder_sorts_last(self):
        # lineorder is the only table with FK dependencies, so it must be
        # the final entry regardless of tie-breaking among the other four.
        order = get_table_loading_order()
        assert order[-1] == "lineorder"

    def test_alphabetical_order_would_not_be_fk_safe(self):
        # Confirms this is a real fix, not a no-op re-derivation of the
        # previous (alphabetical) fallback behavior.
        order = get_table_loading_order()
        assert order != sorted(order)


class TestSSBBenchmarkTableLoadingOrder:
    def test_orders_a_shuffled_available_subset_fk_safely(self, tmp_path):
        bench = SSBBenchmark(scale_factor=0.001, output_dir=tmp_path)
        available = ["supplier", "lineorder", "date", "part", "customer"]

        order = bench.get_table_loading_order(available)

        assert set(order) == set(available)
        position = {name: i for i, name in enumerate(order)}
        assert position["customer"] < position["lineorder"]
        assert position["part"] < position["lineorder"]
        assert position["supplier"] < position["lineorder"]
        assert position["date"] < position["lineorder"]

    def test_unknown_table_is_preserved_not_dropped(self, tmp_path):
        bench = SSBBenchmark(scale_factor=0.001, output_dir=tmp_path)
        order = bench.get_table_loading_order(["date", "some_extra_table"])
        assert "some_extra_table" in order
