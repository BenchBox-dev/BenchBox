"""Tests for the synthetic JoinOrder query manager's merged 113-query surface.

Covers the embedded/canonical merge, custom-directory replacement semantics,
and classification of the full exposed query set.
"""

from __future__ import annotations

import pytest

from benchbox.core.joinorder.queries import CANONICAL_JOINORDER_QUERIES
from benchbox.core.joinorder_synthetic.queries import JoinOrderQueryManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDefaultMergedSurface:
    def test_default_count_covers_full_canonical_set(self):
        manager = JoinOrderQueryManager()
        assert manager.get_query_count() == len(CANONICAL_JOINORDER_QUERIES) == 113

    def test_canonical_extension_id_resolves(self):
        manager = JoinOrderQueryManager()
        assert "SELECT" in manager.get_query("1c").upper()
        assert "FROM" in manager.get_query("1c").upper()

    def test_unknown_id_still_rejected(self):
        manager = JoinOrderQueryManager()
        with pytest.raises(ValueError, match="Invalid query ID"):
            manager.get_query("does-not-exist")

    def test_distributions_account_for_every_exposed_query(self):
        manager = JoinOrderQueryManager()
        exposed = set(manager.get_all_queries())
        assert len(exposed) == 113

        complexity = manager.get_queries_by_complexity()
        classified_complexity = {qid for ids in complexity.values() for qid in ids}
        assert classified_complexity == exposed

        patterns = manager.get_queries_by_pattern()
        classified_patterns = {qid for ids in patterns.values() for qid in ids}
        assert classified_patterns == exposed

    def test_benchmark_info_distributions_cover_total_queries(self):
        from benchbox.core.joinorder_synthetic.benchmark import JoinOrderSyntheticBenchmark

        benchmark = JoinOrderSyntheticBenchmark(scale_factor=0.001)
        info = benchmark.get_benchmark_info()
        complexity_total = sum(len(ids) for ids in info["query_complexity_distribution"].values())
        pattern_total = sum(len(ids) for ids in info["join_pattern_distribution"].values())
        assert info["total_queries"] == 113
        assert complexity_total == info["total_queries"]
        assert pattern_total == info["total_queries"]


class TestCustomDirectoryReplacement:
    @pytest.fixture()
    def query_dir(self, tmp_path):
        query_dir = tmp_path / "queries"
        query_dir.mkdir()
        (query_dir / "custom.sql").write_text("SELECT 1;")
        return query_dir

    def test_custom_directory_reports_only_its_files(self, query_dir):
        manager = JoinOrderQueryManager(str(query_dir))
        assert manager.get_all_queries() == {"custom": "SELECT 1;"}
        assert manager.get_query_count() == 1
        assert manager.get_query_ids() == ["custom"]

    def test_custom_directory_has_no_canonical_fallback(self, query_dir):
        manager = JoinOrderQueryManager(str(query_dir))
        with pytest.raises(ValueError, match="Invalid query ID: 1a"):
            manager.get_query("1a")

    def test_custom_directory_distributions_cover_only_custom_queries(self, query_dir):
        manager = JoinOrderQueryManager(str(query_dir))
        complexity = manager.get_queries_by_complexity()
        assert {qid for ids in complexity.values() for qid in ids} == {"custom"}
        patterns = manager.get_queries_by_pattern()
        assert {qid for ids in patterns.values() for qid in ids} == {"custom"}
