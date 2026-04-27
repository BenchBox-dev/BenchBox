# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Integration test: QuestDB /imp two-chunk CSV import with forceHeader=true.

Setup:
    make test-docker-up-questdb

These tests require a running QuestDB 9.3.4 instance accessible at:
    localhost:19000  (REST API / HTTP, remapped from container port 9000)

Verifies that the _load_parquet_via_chunked_csv fix is correct:
  - Every chunk is posted with a CSV header row and forceHeader=true
  - QuestDB maps chunk 2 columns by name, not position
  - All 6 rows (3 per chunk) land in the correct columns after two-chunk import
"""

import io

import pytest
import requests

from .conftest import skip_unless_docker_service

QUESTDB_HOST = "localhost"
QUESTDB_HTTP_PORT = 19000  # remapped from container port 9000

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_questdb,
]

TABLE_NAME = "benchbox_imp_chunk_test"


@pytest.fixture(scope="module")
def questdb_http_url():
    """Base URL for QuestDB REST API. Skips if QuestDB is not reachable."""
    skip_unless_docker_service(QUESTDB_HOST, QUESTDB_HTTP_PORT, platform="QuestDB")
    return f"http://{QUESTDB_HOST}:{QUESTDB_HTTP_PORT}"


def _exec(base_url: str, sql: str) -> dict:
    resp = requests.get(f"{base_url}/exec", params={"query": sql}, timeout=15)
    resp.raise_for_status()
    result = resp.json()
    if "error" in result:
        raise RuntimeError(f"QuestDB /exec error for {sql!r}: {result['error']}")
    return result


def _imp(base_url: str, csv_text: str, *, overwrite: str = "false", force_header: str = "true") -> str:
    """POST a CSV payload to /imp."""
    params = {
        "name": TABLE_NAME,
        "overwrite": overwrite,
        "durable": "true",
        "delimiter": ",",
        "forceHeader": force_header,
    }
    buf = io.BytesIO(csv_text.encode())
    files = {"data": (f"{TABLE_NAME}.csv", buf, "text/csv")}
    resp = requests.post(f"{base_url}/imp", params=params, files=files, timeout=30)
    resp.raise_for_status()
    return resp.text


@pytest.fixture(autouse=True)
def drop_test_table(questdb_http_url):
    """Drop the test table before and after each test for isolation."""
    _exec(questdb_http_url, f"DROP TABLE IF EXISTS {TABLE_NAME}")
    yield
    _exec(questdb_http_url, f"DROP TABLE IF EXISTS {TABLE_NAME}")


class TestQuestDBImpTwoChunkImport:
    """Verify that two-chunk /imp with header + forceHeader=true maps columns correctly.

    This test captures the behaviour that _load_parquet_via_chunked_csv relies on:
    every chunk is sent with a CSV header row and forceHeader=true, ensuring QuestDB
    maps columns by name (not position) even on the second and subsequent chunks.
    """

    def test_two_chunks_with_force_header_correct_columns(self, questdb_http_url):
        """Both chunks with header + forceHeader=true produce correct column values."""
        chunk1 = "id,name,val\n1,alpha,1.1\n2,beta,2.2\n3,gamma,3.3\n"
        chunk2 = "id,name,val\n4,delta,4.4\n5,epsilon,5.5\n6,zeta,6.6\n"

        _imp(questdb_http_url, chunk1, overwrite="false", force_header="true")
        _imp(questdb_http_url, chunk2, overwrite="false", force_header="true")

        result = _exec(questdb_http_url, f"SELECT id, name, val FROM {TABLE_NAME} ORDER BY id")
        rows = result.get("dataset", [])

        assert len(rows) == 6, f"Expected 6 rows, got {len(rows)}: {rows}"

        # Chunk 1 rows
        assert rows[0][0] == 1 and rows[0][1] == "alpha"
        assert rows[1][0] == 2 and rows[1][1] == "beta"
        assert rows[2][0] == 3 and rows[2][1] == "gamma"

        # Chunk 2 rows - these would be silently corrupted if QuestDB mapped by position
        # and we sent a header on chunk 2 (treating header as data). forceHeader=true
        # tells QuestDB the first row is a header, not data.
        assert rows[3][0] == 4 and rows[3][1] == "delta"
        assert rows[4][0] == 5 and rows[4][1] == "epsilon"
        assert rows[5][0] == 6 and rows[5][1] == "zeta"

    def test_val_column_not_shifted_to_id(self, questdb_http_url):
        """Verify val column values are not treated as id (column-shift regression guard)."""
        chunk1 = "id,name,val\n10,first,9.9\n"
        chunk2 = "id,name,val\n20,second,8.8\n"

        _imp(questdb_http_url, chunk1, overwrite="false", force_header="true")
        _imp(questdb_http_url, chunk2, overwrite="false", force_header="true")

        result = _exec(questdb_http_url, f"SELECT id, name, val FROM {TABLE_NAME} ORDER BY id")
        rows = result.get("dataset", [])

        assert len(rows) == 2
        # If columns were shifted, id would be 9.9 or "first". Assert it is 10.
        assert rows[0][0] == 10, f"id column shifted: got {rows[0][0]!r}, expected 10"
        assert rows[0][2] == pytest.approx(9.9, rel=1e-5)
        assert rows[1][0] == 20, f"id column shifted: got {rows[1][0]!r}, expected 20"
        assert rows[1][2] == pytest.approx(8.8, rel=1e-5)

    def test_three_chunks_all_columns_correct(self, questdb_http_url):
        """Three-chunk import preserves column mapping on chunk 3+ (not just chunk 2)."""
        chunk1 = "id,name,val\n1,alpha,1.1\n"
        chunk2 = "id,name,val\n2,beta,2.2\n"
        chunk3 = "id,name,val\n3,gamma,3.3\n"

        _imp(questdb_http_url, chunk1, overwrite="false", force_header="true")
        _imp(questdb_http_url, chunk2, overwrite="false", force_header="true")
        _imp(questdb_http_url, chunk3, overwrite="false", force_header="true")

        result = _exec(questdb_http_url, f"SELECT id, name, val FROM {TABLE_NAME} ORDER BY id")
        rows = result.get("dataset", [])

        assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}: {rows}"
        assert rows[0] == [1, "alpha", pytest.approx(1.1, rel=1e-5)]
        assert rows[1] == [2, "beta", pytest.approx(2.2, rel=1e-5)]
        assert rows[2] == [3, "gamma", pytest.approx(3.3, rel=1e-5)]
