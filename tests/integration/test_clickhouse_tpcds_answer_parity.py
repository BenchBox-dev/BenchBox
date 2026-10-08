"""ClickHouse TPC-DS tuned-vs-untuned answer parity on a real engine.

No unit test can prove that tuned DDL returns the same answers as untuned
DDL: the NULLs-as-0 hazard (a tuned key rendered non-Nullable while the data
holds NULLs) only materializes when real CSVs load into a real engine. This
test generates TPC-DS once at a small scale factor, loads the identical files
into an untuned and then a tuned ClickHouse local database (curated
``tpcds_tuned`` template), runs the full 99-query ClickHouse-dialect set
against both, and requires identical answers.

Comparison is exact on values and row multiplicity (sorted by repr), but
order-insensitive: tuned and untuned plans legitimately emit rows in
different physical orders, and row order across plans is not part of the
answer. There is no tolerance and no per-query exemption list; a mismatch
fails with the query id.

Runs in the nightly slow lane (``integration`` + ``slow`` + ``tpcds``): even
at scale factor 0.01, datagen plus two full loads plus 198 query executions
do not fit the fast/medium lane budgets. Skips cleanly where chDB cannot
load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from benchbox.core.tpcds.benchmark.runner import TPCDSBenchmark
from benchbox.core.tuning.interface import UnifiedTuningConfiguration
from benchbox.core.tuning.packaged_templates import packaged_template_path
from benchbox.platforms.clickhouse import ClickHouseAdapter, ClickHouseLocalClient
from benchbox.platforms.clickhouse.query_transformer import ClickHouseQueryTransformer
from tests.utilities.optional_engines import require_chdb

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.tpcds,
]

# Skip the whole module where chDB cannot load (e.g. macOS hosts whose
# loader rejects the published wheels); the skip reason names the cause.
chdb = require_chdb()

SCALE_FACTOR = 0.01
EXPECTED_QUERY_COUNT = 99


def _load_curated_tuning_config() -> UnifiedTuningConfiguration:
    """Load the packaged ClickHouse TPC-DS template the way runs do."""
    template_path = packaged_template_path("clickhouse", "tpcds")
    assert template_path.exists(), f"missing curated template: {template_path}"
    payload = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
    config = UnifiedTuningConfiguration.from_dict(payload)
    assert config.table_tunings, f"curated template carries no table tunings: {template_path}"
    return config


def _drop_all_tables(client: Any) -> None:
    for (table_name,) in client.execute("SHOW TABLES"):
        client.execute(f"DROP TABLE IF EXISTS {table_name}")


def _parity_sql(sql: str) -> str:
    transformer = ClickHouseQueryTransformer()
    return transformer.add_query_settings(transformer.transform(sql))


def _query_answers(client: Any, queries: dict[str, str]) -> dict[str, list[tuple[str, ...]]]:
    """Run every query and return rows as sorted repr tuples (multiset)."""
    answers: dict[str, list[tuple[str, ...]]] = {}
    for query_id in sorted(queries, key=int):
        rows = client.execute(_parity_sql(queries[query_id]))
        answers[query_id] = sorted(tuple(repr(value) for value in row) for row in rows)
    return answers


class _RecordingClient:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> list[tuple[str, ...]]:
        self.statements.append(sql)
        return [("ok",)]


def test_query_answers_execute_production_transformed_sql() -> None:
    queries = {"1": "SELECT SUM(SR_FEE) AS s FROM store_returns"}
    untuned = _RecordingClient()
    tuned = _RecordingClient()
    assert _query_answers(untuned, queries) == {"1": [("'ok'",)]}
    assert _query_answers(tuned, queries) == {"1": [("'ok'",)]}
    assert untuned.statements == tuned.statements
    (statement,) = untuned.statements
    assert "SR_FEE" not in statement
    assert "sr_fee" in statement
    assert statement.rstrip().endswith("SETTINGS joined_subquery_requires_alias = 0")


def test_tuned_tpcds_answers_match_untuned(tmp_path: Path) -> None:
    data_dir = tmp_path / "tpcds-data"
    benchmark = TPCDSBenchmark(scale_factor=SCALE_FACTOR, output_dir=data_dir)
    benchmark.generate_data()
    assert benchmark.tables, "TPC-DS datagen produced no tables"

    queries = benchmark.get_queries(dialect="clickhouse")
    assert len(queries) == EXPECTED_QUERY_COUNT, f"expected 99 TPC-DS queries, got {len(queries)}"

    # chDB pins one EmbeddedServer path per worker process, so both phases
    # share the default in-memory client sequentially: run untuned, drop
    # every table, then run tuned on the same client.
    client = ClickHouseLocalClient()
    try:
        untuned = ClickHouseAdapter(deployment_mode="local")
        untuned.create_schema(benchmark, client)
        untuned.load_data(benchmark, client, data_dir)
        untuned_answers = _query_answers(client, queries)

        _drop_all_tables(client)

        tuned = ClickHouseAdapter(deployment_mode="local")
        tuned.tuning_enabled = True
        tuned.unified_tuning_configuration = _load_curated_tuning_config()
        tuned.create_schema(benchmark, client)
        tuned.load_data(benchmark, client, data_dir)
        tuned_answers = _query_answers(client, queries)
    finally:
        client.close()

    assert set(tuned_answers) == set(untuned_answers) == set(queries)
    mismatched = sorted(
        (query_id for query_id in queries if tuned_answers[query_id] != untuned_answers[query_id]),
        key=int,
    )
    assert mismatched == [], f"tuned answers differ from untuned for queries: {mismatched}"
    total_rows = sum(len(rows) for rows in untuned_answers.values())
    assert total_rows > 0, "no query returned any row; parity would be vacuously true"
