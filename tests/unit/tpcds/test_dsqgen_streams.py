"""Tests for the official dsqgen -STREAMS batch generation path.

Pins the per-stream query ORDERING and per-stream substitution PARAMETERS
produced by the bundled dsqgen binary's ``-STREAMS N`` mode for a fixed
(num_streams, seed) pair -- this is the ground truth the TPC-DS throughput
test now uses instead of a home-grown Python permutation (see
_project/DONE/main/planning/tpcds-throughput-permutation-compliance.yaml).

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.tpcds.streams import (
    DSQGenStreamsError,
    _parse_dsqgen_stream_log,
    _split_dsqgen_stream_sql,
    generate_dsqgen_streams,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.tpcds,
]

# Pinned against the bundled darwin-arm64 dsqgen (qgen2 Version 4.0.0) via
# `dsqgen -STREAMS 2 -INPUT q/templates.lst -DIRECTORY q -SCALE 1
#  -DIALECT netezza -LOG stream_params.log -RNGSEED 19620718`.
# Evidence captured 2026-07-09; see commit message for the full w0 diff.
PINNED_SEED = 19620718
PINNED_NUM_STREAMS = 2
PINNED_STREAM0_ORDER_HEAD = [
    (96, None),
    (7, None),
    (75, None),
    (44, None),
    (39, "a"),
    (39, "b"),
]
PINNED_STREAM1_ORDER_HEAD = [
    (83, None),
    (32, None),
    (30, None),
    (92, None),
    (66, None),
    (84, None),
]

# Query IDs whose dsqgen substitution parameters are NOT reproducible even for a
# fixed -RNGSEED, and are therefore excluded from byte-identity determinism
# checks. Currently only query46, whose 5-city IN-list comes from a
# `ulist(random(1, rowcount("active_cities", "store"), uniform), 5)` substitution
# with a dsqgen-internal non-seeded draw (a property of the bundled reference
# binary, not of BenchBox). Ordering is unaffected -- query46 keeps a stable slot.
DSQGEN_NONREPRODUCIBLE_QUERY_IDS = {46}


class TestGenerateDsqgenStreamsRealBinary:
    """Exercises the bundled dsqgen binary end-to-end (fast: ~60ms for N=2)."""

    def test_official_ordering_pinned_for_fixed_seed(self):
        streams = generate_dsqgen_streams(num_streams=PINNED_NUM_STREAMS, scale_factor=1.0, seed=PINNED_SEED)

        assert set(streams.keys()) == {0, 1}

        stream0_order = [(q.query_id, q.variant) for q in streams[0]]
        stream1_order = [(q.query_id, q.variant) for q in streams[1]]

        assert stream0_order[:6] == PINNED_STREAM0_ORDER_HEAD
        assert stream1_order[:6] == PINNED_STREAM1_ORDER_HEAD

        # Streams 0 and 1 must NOT share the same ordering (each stream gets
        # its own official permutation from dsqgen's sequential RNG state).
        assert stream0_order[:6] != stream1_order[:6]

    def test_official_ordering_includes_multi_part_expansion(self):
        streams = generate_dsqgen_streams(num_streams=PINNED_NUM_STREAMS, scale_factor=1.0, seed=PINNED_SEED)

        # 99 templates, 4 of which (14/23/24/39) expand to 2 SQL statements
        # each -> 103 StreamQuery entries per stream.
        assert len(streams[0]) == 103
        assert len(streams[1]) == 103

        query_ids = {q.query_id for q in streams[0]}
        assert query_ids == set(range(1, 100))

        variants_for_39 = [q.variant for q in streams[0] if q.query_id == 39]
        assert variants_for_39 == ["a", "b"]

    def test_official_substitution_parameters_baked_into_sql(self):
        """The first query of stream 0 (query96) must carry dsqgen's own
        substitution parameters, not the home-grown Python RNG jitter."""
        streams = generate_dsqgen_streams(num_streams=PINNED_NUM_STREAMS, scale_factor=1.0, seed=PINNED_SEED)
        first_sql = streams[0][0].sql

        assert first_sql is not None
        assert "time_dim.t_hour = 8" in first_sql
        assert "household_demographics.hd_dep_count = 5" in first_sql
        assert "store.s_store_name = 'ese'" in first_sql

    def test_deterministic_for_fixed_num_streams_and_seed(self):
        first = generate_dsqgen_streams(num_streams=2, scale_factor=1.0, seed=PINNED_SEED)
        second = generate_dsqgen_streams(num_streams=2, scale_factor=1.0, seed=PINNED_SEED)

        # ORDERING is fully deterministic for a fixed (num_streams, seed) -- this
        # is the soundness-critical property (per-stream query sequencing feeds
        # QphDS compliance).
        first_order = [(q.query_id, q.variant) for q in first[0]]
        second_order = [(q.query_id, q.variant) for q in second[0]]
        assert first_order == second_order

        # Per-query substitution PARAMETERS are deterministic for 98/99 queries.
        # The sole exception is query46, whose IN-list of 5 cities is built by a
        # dsqgen-internal `ulist(random(1, rowcount("active_cities", "store"),
        # uniform), 5)` substitution that is NOT reproducible even with a fixed
        # -RNGSEED (verified against the bundled dsqgen binary directly, both
        # serially and concurrently -- it is a property of the reference binary,
        # not of BenchBox's integration). We therefore pin every query EXCEPT
        # query46 to byte-identity, while its ordering slot stays stable (above).
        for pos, (q1, q2) in enumerate(zip(first[0], second[0])):
            if q1.query_id in DSQGEN_NONREPRODUCIBLE_QUERY_IDS:
                continue
            assert q1.sql == q2.sql, f"non-deterministic SQL at position {pos} for query {q1.query_id}"

    def test_num_streams_must_be_positive(self):
        with pytest.raises(ValueError, match="num_streams must be >= 1"):
            generate_dsqgen_streams(num_streams=0, seed=PINNED_SEED)


class TestParseDsqgenStreamLog:
    """White-box tests for the -LOG parser, no subprocess required."""

    def test_parses_begin_stream_and_template_markers(self):
        log_text = (
            "BEGIN STREAM 0\n"
            "Template: query96.tpl\n"
            "\tHOUR.01 = 8\n"
            "\n"
            "Template: query39.tpl\n"
            "\tSOME.01 = value\n"
            "\n"
            "BEGIN STREAM 1\n"
            "Template: query83.tpl\n"
        )

        parsed = _parse_dsqgen_stream_log(log_text)

        assert parsed[0] == [(96, None), (39, "a"), (39, "b")]
        assert parsed[1] == [(83, None)]

    def test_non_multi_part_template_not_expanded(self):
        log_text = "BEGIN STREAM 0\nTemplate: query1.tpl\n"
        parsed = _parse_dsqgen_stream_log(log_text)
        assert parsed[0] == [(1, None)]

    def test_lines_before_begin_stream_are_ignored(self):
        log_text = "Template: query1.tpl\nBEGIN STREAM 0\nTemplate: query2.tpl\n"
        parsed = _parse_dsqgen_stream_log(log_text)
        assert parsed[0] == [(2, None)]


class TestSplitDsqgenStreamSql:
    """White-box tests for splitting a per-stream .sql file into statements."""

    def test_splits_on_semicolon_newline_boundary(self):
        sql_text = "select 1;\nselect 2;\nselect 3;\n"
        statements = _split_dsqgen_stream_sql(sql_text)
        assert statements == ["select 1;", "select 2;", "select 3;"]

    def test_multiline_statement_preserved_as_one_entry(self):
        sql_text = "select 1\nfrom t\nwhere x = 1;\nselect 2;\n"
        statements = _split_dsqgen_stream_sql(sql_text)
        assert len(statements) == 2
        assert statements[0].startswith("select 1")
        assert statements[0].endswith(";")

    def test_empty_input_returns_empty_list(self):
        assert _split_dsqgen_stream_sql("") == []
        assert _split_dsqgen_stream_sql("   \n  ") == []


class TestGenerateDsqgenStreamsErrors:
    def test_missing_binary_raises_dsqgen_streams_error(self, monkeypatch):
        import benchbox.core.tpcds.streams as streams_mod

        def _fake_resolve():
            from pathlib import Path

            return Path("/nonexistent/tools"), Path("/nonexistent/templates")

        monkeypatch.setattr(streams_mod, "_resolve_dsqgen_binary_and_templates", _fake_resolve)

        with pytest.raises(DSQGenStreamsError, match="dsqgen binary not found"):
            generate_dsqgen_streams(num_streams=1, seed=PINNED_SEED)
