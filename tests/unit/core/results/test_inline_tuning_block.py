"""The bundle carries its own tuning truth: requested intent and applied ledger.

Before this, a reader had to stitch three files to answer "what tuning did this
run request, and what did it actually execute?" -- the bundle's
``platform.tuning`` summary for the hashes, ``.tuning.json`` for the requested
configuration, and ``.applied.json`` for the executed statements. Every consumer
(``validate_submission``, ``validate_corpus``, the explorer pipeline, the loader)
implemented that stitch separately, and a bundle separated from its companions
silently lost the answer.

``platform.tuning`` now holds both sub-blocks, and the loader reads them. The
companions are still written, so an inlined bundle and its companion must agree
exactly -- including the redaction applied to each, which is the part that
differs by export mode and must not regress.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for
details.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchbox.core.results.exporter import ResultExporter
from benchbox.core.results.loader import load_result_file
from benchbox.core.results.result_factory import build_enhanced_benchmark_result

pytestmark = [pytest.mark.unit, pytest.mark.fast]

_REQUESTED_TUNING = {
    "primary_keys": {"enabled": True, "enforce_uniqueness": True},
    "table_tunings": {
        "LINEITEM": {
            "table_name": "LINEITEM",
            "sorting": [{"name": "l_orderkey", "order": 1, "type": "INTEGER"}],
        }
    },
}

_APPLIED_LEDGER = {
    "status": "applied_unverified",
    "applied_ledger_hash": "f" * 64,
    "statements": [
        {
            "statement": "CREATE INDEX idx_l_orderkey ON LINEITEM (l_orderkey)",
            "phase": "ddl",
            "status": "executed",
            "mechanism": "sort_index",
        }
    ],
    "dropped": [{"intent": "partitioning:LINEITEM", "reason": "load-time only"}],
    "receipt": {
        "platform": "duckdb",
        "corroborated": False,
        "summary": {"mismatch": 1, "gate_relevant_total": 1},
        "entries": [
            {
                "kind": "index",
                "phase": "ddl",
                "verdict": "mismatch",
                "statement": "CREATE INDEX idx_l_orderkey ON LINEITEM (l_orderkey)",
                "table": "main.LINEITEM",
            }
        ],
    },
}


def _tuned_result() -> object:
    benchmark = SimpleNamespace(benchmark_name="tpch", scale_factor=0.01, compliance_class=None)
    return build_enhanced_benchmark_result(
        benchmark=benchmark,
        platform="duckdb",
        query_results=[],
        tunings_applied=dict(_REQUESTED_TUNING),
        tuning_config_hash="a" * 64,
        tuning_source="auto_discovered",
        tuning_source_file="examples/tunings/duckdb/tpch_tuned.yaml",
        tuning_validation_status="applied_unverified",
        applied_tuning_ledger=dict(_APPLIED_LEDGER),
        applied_ledger_hash=_APPLIED_LEDGER["applied_ledger_hash"],
    )


def _export(tmp_path: Path, *, anonymize: bool) -> tuple[dict, dict, dict]:
    """Export one tuned result and return (bundle, tuning companion, applied companion)."""
    exporter = ResultExporter(output_dir=tmp_path, anonymize=anonymize)
    result = _tuned_result()
    result.output_filename = "run.json"
    exporter.export_result(result, formats=["json"])

    bundle = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    tuning = json.loads((tmp_path / "run.tuning.json").read_text(encoding="utf-8"))
    applied = json.loads((tmp_path / "run.applied.json").read_text(encoding="utf-8"))
    return bundle, tuning, applied


@pytest.mark.parametrize("anonymize", [True, False])
class TestInlinedBlockMatchesCompanions:
    def test_requested_configuration_is_inlined(self, tmp_path: Path, anonymize: bool) -> None:
        bundle, tuning, _applied = _export(tmp_path, anonymize=anonymize)

        inlined = bundle["platform"]["tuning"]["requested"]
        # The companion nests the configuration one level down; the inlined copy
        # flattens it so the block is not `tuning.requested.requested`.
        assert inlined == tuning["requested"]
        assert bundle["platform"]["tuning"]["source_file"] == tuning["source_file"]

    def test_applied_ledger_is_inlined(self, tmp_path: Path, anonymize: bool) -> None:
        bundle, _tuning, applied = _export(tmp_path, anonymize=anonymize)

        inlined = bundle["platform"]["tuning"]["applied"]
        # The hash lives on the summary, which owns it; everything else matches
        # the companion byte for byte.
        assert inlined == {k: v for k, v in applied.items() if k != "applied_ledger_hash"}
        assert bundle["platform"]["tuning"]["applied_ledger_hash"] == applied["applied_ledger_hash"]

    def test_hashes_are_not_duplicated_inside_the_sub_blocks(self, tmp_path: Path, anonymize: bool) -> None:
        """One field, one home: a second copy is a chance for the two to diverge."""
        bundle, _tuning, _applied = _export(tmp_path, anonymize=anonymize)

        tuning_block = bundle["platform"]["tuning"]
        assert "applied_ledger_hash" not in tuning_block["applied"]
        assert "requested_config_hash" not in tuning_block["requested"]
        assert "validation_status" not in tuning_block["requested"]
        # The companion's own envelope describes the file, not the run.
        assert "version" not in tuning_block["requested"]
        assert "run_id" not in tuning_block["requested"]


class TestAnonymizedInliningKeepsRedaction:
    def test_public_bundle_never_inlines_raw_ddl_or_identifiers(self, tmp_path: Path) -> None:
        """The inlined ledger must get the applied-ledger redaction, not the
        general result anonymizer.

        ``.applied.json`` is scrubbed by a dedicated policy that drops free-text
        ``statement`` / ``error`` and the ``table`` identifier outright, because
        no structured scrubber can safely redact arbitrary per-platform SQL. That
        policy lives outside the main anonymization walk, so inlining the ledger
        without re-applying it would publish raw DDL in the bundle.
        """
        bundle, _tuning, applied = _export(tmp_path, anonymize=True)
        raw_bundle_text = (tmp_path / "run.json").read_text(encoding="utf-8")

        applied_block = bundle["platform"]["tuning"]["applied"]
        assert applied_block["statements"][0]["statement_redacted"] is True
        assert "statement" not in applied_block["statements"][0]
        assert applied_block["receipt"]["entries"][0]["statement_redacted"] is True
        assert "table" not in applied_block["receipt"]["entries"][0]
        # Dropped intents carry adapter-provided text and become count markers.
        assert applied_block["dropped"] == [{"redacted": True}]

        # The strongest form of the check: neither the statement text nor the
        # qualified table name appears anywhere in the published bundle.
        assert "CREATE INDEX" not in raw_bundle_text
        assert "main.LINEITEM" not in raw_bundle_text
        assert "load-time only" not in raw_bundle_text
        # And the companion agrees, because both come from one scrub.
        assert "statement" not in applied["statements"][0]

    def test_private_bundle_keeps_the_statements_like_the_companion(self, tmp_path: Path) -> None:
        """A private export has always kept raw statements in `.applied.json`;
        inlining must not silently change that either way."""
        bundle, _tuning, applied = _export(tmp_path, anonymize=False)

        applied_block = bundle["platform"]["tuning"]["applied"]
        assert applied_block["statements"][0]["statement"] == applied["statements"][0]["statement"]
        assert bundle["export"]["anonymized"] is False


class TestAppliedLedgerWithoutRequestedTuning:
    def test_ledger_hash_survives_when_there_is_no_tuning_summary(self, tmp_path: Path) -> None:
        """A run can apply tuning without a requested configuration.

        An adapter that executes layout operations off a platform option leaves
        ``tunings_applied`` empty, so ``_build_tuning_summary`` emits no block at
        all. The ledger hash then has nowhere to be promoted from, and dropping
        it would erase the only record of what the run physically applied.
        """
        benchmark = SimpleNamespace(benchmark_name="tpch", scale_factor=0.01, compliance_class=None)
        result = build_enhanced_benchmark_result(
            benchmark=benchmark,
            platform="duckdb",
            query_results=[],
            applied_tuning_ledger=dict(_APPLIED_LEDGER),
            applied_ledger_hash=_APPLIED_LEDGER["applied_ledger_hash"],
        )
        result.output_filename = "run.json"
        ResultExporter(output_dir=tmp_path, anonymize=False).export_result(result, formats=["json"])

        bundle = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
        tuning_block = bundle["platform"]["tuning"]
        assert tuning_block["applied_ledger_hash"] == _APPLIED_LEDGER["applied_ledger_hash"]
        assert tuning_block["applied"]["status"] == "applied_unverified"

        (tmp_path / "run.applied.json").unlink()
        loaded, _raw = load_result_file(tmp_path / "run.json")
        assert loaded.applied_ledger_hash == _APPLIED_LEDGER["applied_ledger_hash"]
        assert loaded.applied_tuning_ledger is not None


class TestLoaderReadsTheBundleAlone:
    def test_bundle_without_companions_reconstructs_its_tuning(self, tmp_path: Path) -> None:
        """The point of inlining: a bundle separated from its companions still
        answers what was requested and what was applied."""
        _export(tmp_path, anonymize=False)
        (tmp_path / "run.tuning.json").unlink()
        (tmp_path / "run.applied.json").unlink()

        result, _raw = load_result_file(tmp_path / "run.json")

        assert result.tuning_config_hash == "a" * 64
        assert result.tuning_source == "auto_discovered"
        assert result.tuning_source_file == "examples/tunings/duckdb/tpch_tuned.yaml"
        assert result.tuning_validation_status == "applied_unverified"
        assert result.applied_ledger_hash == _APPLIED_LEDGER["applied_ledger_hash"]
        assert result.applied_tuning_ledger is not None
        assert result.applied_tuning_ledger["status"] == "applied_unverified"
        assert result.applied_tuning_ledger["applied_ledger_hash"] == _APPLIED_LEDGER["applied_ledger_hash"]
        assert result.tunings_applied is not None
        assert result.tunings_applied["table_tunings"]["LINEITEM"]["sorting"][0]["name"] == "l_orderkey"

    def test_companion_still_wins_for_a_legacy_bundle(self, tmp_path: Path) -> None:
        """Bundles exported before inlining carry the companion only, and a
        republished corpus bundle may ship the companion alone."""
        _export(tmp_path, anonymize=False)
        bundle_path = tmp_path / "run.json"
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

        # Strip the inlined sub-blocks to simulate a pre-inlining bundle.
        del bundle["platform"]["tuning"]["requested"]
        del bundle["platform"]["tuning"]["applied"]
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

        result, _raw = load_result_file(bundle_path)

        assert result.applied_tuning_ledger is not None
        assert result.applied_tuning_ledger["statements"][0]["phase"] == "ddl"
        assert result.tunings_applied is not None
        assert "table_tunings" in result.tunings_applied

    def test_round_trip_export_preserves_the_inlined_tuning(self, tmp_path: Path) -> None:
        """Load a companion-less bundle and re-export it: the tuning survives."""
        _export(tmp_path, anonymize=False)
        (tmp_path / "run.tuning.json").unlink()
        (tmp_path / "run.applied.json").unlink()
        result, _raw = load_result_file(tmp_path / "run.json")

        second = tmp_path / "again"
        second.mkdir()
        result.output_filename = "run.json"
        ResultExporter(output_dir=second, anonymize=False).export_result(result, formats=["json"])

        reexported = json.loads((second / "run.json").read_text(encoding="utf-8"))
        tuning_block = reexported["platform"]["tuning"]
        assert tuning_block["requested_config_hash"] == "a" * 64
        assert tuning_block["applied_ledger_hash"] == _APPLIED_LEDGER["applied_ledger_hash"]
        assert tuning_block["requested"]["table_tunings"]["LINEITEM"]["sorting"][0]["name"] == "l_orderkey"
        assert tuning_block["applied"]["statements"][0]["phase"] == "ddl"


class TestCompanionWinsFieldByField:
    def test_a_minimal_companion_does_not_wipe_inlined_fields(self, tmp_path: Path) -> None:
        """A companion wins per field, not wholesale.

        A stale, hand-authored, or republished companion can carry only
        ``requested``. Overwriting unconditionally wiped the inlined
        ``source_file`` and ``validation_status`` with None, losing -- on a bundle
        that states them -- the template the run used and whether its tuning was
        verified.
        """
        _export(tmp_path, anonymize=False)
        (tmp_path / "run.applied.json").unlink()
        (tmp_path / "run.tuning.json").write_text(
            json.dumps({"requested": {"table_tunings": {"LINEITEM": {"table_name": "LINEITEM"}}}}),
            encoding="utf-8",
        )

        result, _raw = load_result_file(tmp_path / "run.json")

        assert result.tuning_source_file == "examples/tunings/duckdb/tpch_tuned.yaml"
        assert result.tuning_validation_status == "applied_unverified"
        assert result.tuning_config_hash == "a" * 64
        assert result.tuning_source == "auto_discovered"
        # The companion's own content still wins where it has any.
        assert result.tunings_applied is not None
        assert "LINEITEM" in result.tunings_applied["table_tunings"]


class TestBareStringIdentifiersAreHashed:
    def test_string_clause_values_do_not_reach_a_public_bundle(self, tmp_path: Path) -> None:
        """A first-party tuning config renders columns as ``{"name": ...}`` dicts,
        which the structural walk hashes. A hand-authored or republished
        companion may instead write a bare string or a list of strings under a
        clause key, and those identifiers reached the public artifact verbatim.

        Inlining put them in the primary bundle too, so the clause key -- not the
        value's shape -- now decides what counts as an identifier.
        """
        benchmark = SimpleNamespace(benchmark_name="tpch", scale_factor=0.01, compliance_class=None)
        result = build_enhanced_benchmark_result(
            benchmark=benchmark,
            platform="duckdb",
            query_results=[],
            tunings_applied={
                "table_tunings": {
                    "acme_orders": {
                        "table_name": "acme_orders",
                        "clustering": ["customer_ssn_column"],
                        "partitioning": "revenue_bucket_column",
                    }
                }
            },
            tuning_config_hash="c" * 64,
            tuning_source="explicit_file",
        )
        result.output_filename = "run.json"
        ResultExporter(output_dir=tmp_path, anonymize=True).export_result(result, formats=["json"])

        bundle_text = (tmp_path / "run.json").read_text(encoding="utf-8")
        companion_text = (tmp_path / "run.tuning.json").read_text(encoding="utf-8")

        for identifier in ("acme_orders", "customer_ssn_column", "revenue_bucket_column"):
            assert identifier not in bundle_text, f"{identifier} leaked into the public bundle"
            assert identifier not in companion_text, f"{identifier} leaked into the public companion"

        requested = json.loads(bundle_text)["platform"]["tuning"]["requested"]
        clause = next(iter(requested["table_tunings"].values()))
        assert clause["clustering"][0].startswith("column_")
        assert clause["partitioning"].startswith("column_")

    def test_non_identifier_clause_values_are_left_alone(self, tmp_path: Path) -> None:
        """Only clause keys that name columns are treated as identifiers; a
        column's ``type`` and ``order`` are data and must survive readable."""
        bundle, _tuning, _applied = _export(tmp_path, anonymize=True)

        sorting = next(iter(bundle["platform"]["tuning"]["requested"]["table_tunings"].values()))["sorting"][0]
        assert sorting["type"] == "INTEGER"
        assert sorting["order"] == 1
