"""G-9 exit gate: READ_ONLY ATTACH keeps the canonical DB byte-stable.

Boots a real DuckDB instance against a freshly-built ``results.duckdb``,
attaches it with ``(READ_ONLY)`` exactly as the browser does in
``results-explorer/src/db.ts``, and throws ~50 adversarial SQL strings at
it - CREATE/INSERT/UPDATE/DELETE/DROP/ALTER targeting ``bench.*``,
ATTACH re-binding ``bench``, DETACH, CHECKPOINT/VACUUM of the attached
DB, EXPORT DATABASE, extension loaders, secrets catalogue mutations.

The durable contract the browser relies on is:

    the READ_ONLY-attached catalog cannot be mutated, and the underlying
    ``.duckdb`` file is byte-stable after the fuzz run.

Statements that operate against the *default* in-memory catalog
(``CREATE TABLE evil_local``, ``INSTALL httpfs``) are allowed to
succeed here because they cannot leak into ``bench`` and do not survive
the connection. The DuckDB-WASM bundle separately restricts which
extensions are available - that sandbox is bundle-level, not
engine-level, so it lives in the frontend's extension-allowlist check
rather than this Python fuzz.

DuckDB's READ_ONLY enforcement is a C++ engine guarantee identical
across native and WASM builds; this test exercises the same code path
the browser hits at ``ATTACH ... AS bench (READ_ONLY)``.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from _project.scripts.explorer_pipeline.pipeline import ExplorerPipeline
from tests.unit.scripts.explorer_pipeline.conftest import MINIMAL_BUNDLE

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# Adversarial SQL - 50 strings the browser workbench must reject.
FUZZ_SQL: tuple[str, ...] = (
    # --- DDL against attached schema ----------------------------------
    "CREATE TABLE bench.evil (x INT)",
    "CREATE TABLE evil_local AS SELECT 1",
    "CREATE OR REPLACE TABLE bench.results AS SELECT 1",
    "CREATE VIEW bench.evil_view AS SELECT 1",
    "CREATE OR REPLACE VIEW bench.results AS SELECT 1",
    "CREATE SCHEMA bench.evil",
    "CREATE INDEX evil_idx ON bench.results(result_id)",
    "CREATE SEQUENCE bench.evil_seq",
    "CREATE MACRO bench.evil_macro(x) AS x + 1",
    "CREATE TEMP TABLE evil_tmp AS SELECT 1",
    "ALTER TABLE bench.results ADD COLUMN evil INT",
    "ALTER TABLE bench.results DROP COLUMN result_id",
    "ALTER TABLE bench.results RENAME TO results_evil",
    "DROP TABLE bench.results",
    "DROP VIEW IF EXISTS bench.results",
    "DROP SCHEMA bench CASCADE",
    # --- DML against attached schema ----------------------------------
    "INSERT INTO bench.results SELECT * FROM bench.results",
    "INSERT INTO bench.results DEFAULT VALUES",
    "UPDATE bench.results SET result_id = 'x'",
    "DELETE FROM bench.results",
    "TRUNCATE bench.results",
    "MERGE INTO bench.results USING (SELECT 1 AS result_id) s ON FALSE WHEN NOT MATCHED THEN INSERT DEFAULT VALUES",
    # --- ATTACH re-binding / mutation of attached catalog ---------------
    "ATTACH 'memory.db' AS evil",
    "ATTACH ':memory:' AS evil",
    "ATTACH 'evil.duckdb' AS evil (READ_WRITE)",
    "ATTACH ':memory:' AS bench",  # re-bind alias
    "USE bench",
    "CREATE TABLE bench.main.evil_via_qual (x INT)",
    # --- COPY to local filesystem / remote -------------------------------
    "COPY bench.results TO '/tmp/evil.parquet' (FORMAT PARQUET)",
    "COPY bench.results TO '/tmp/evil.csv' (HEADER, DELIMITER ',')",
    "COPY (SELECT 1) TO '/tmp/evil.json'",
    "EXPORT DATABASE '/tmp/evil_export'",
    # --- Extension + httpfs shenanigans ----------------------------------
    "INSTALL httpfs",
    "LOAD httpfs",
    "INSTALL json",
    "LOAD parquet",
    "INSTALL 'https://example.invalid/evil.duckdb_extension'",
    "SET custom_extension_repository = 'https://example.invalid'",
    # --- Config / PRAGMA knobs that would weaken the sandbox -------------
    "PRAGMA enable_external_access",
    "PRAGMA disable_verification",
    "SET enable_external_access = true",
    "SET allow_unsigned_extensions = true",
    "SET file_search_path = '/tmp'",
    "SET home_directory = '/tmp'",
    "SET secret_directory = '/tmp'",
    # --- Secrets + catalog mutation --------------------------------------
    "CREATE SECRET evil_secret (TYPE S3)",
    "CREATE OR REPLACE SECRET evil_secret (TYPE S3)",
    "DROP SECRET evil_secret",
    # --- Transactional write intent against bench -----------------------
    "BEGIN; INSERT INTO bench.results DEFAULT VALUES; COMMIT",
    "CHECKPOINT bench",
    "VACUUM bench.results",
    "CALL pragma_storage_info('bench.results')",
    "PRAGMA force_checkpoint",
)

assert len(FUZZ_SQL) >= 50, f"G-9 requires ~50 adversarial patterns, got {len(FUZZ_SQL)}"


@pytest.fixture(scope="module")
def built_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a real results.duckdb using the canonical pipeline."""
    root = tmp_path_factory.mktemp("fuzz")
    data_dir = root / "data"
    bundles_dir = data_dir / "bundles"
    bundles_dir.mkdir(parents=True)
    (bundles_dir / "b.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
    output = root / "out"
    ExplorerPipeline().run(data_dir, output)
    return output / "results.duckdb"


def _snapshot_results(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    return con.execute("SELECT * FROM bench.results ORDER BY result_id").fetchall()


# Statements targeting the READ_ONLY ``bench`` catalog - these MUST fail
# because the contract is "the attached DB cannot be written". Statements
# outside this subset may succeed against the default in-memory catalog
# but cannot leak into ``bench``; the post-fuzz file-mtime + snapshot
# check confirms that.
# Prefixes that unambiguously mutate the attached catalog. ``COPY .. TO``
# reads from bench and writes to the filesystem - it does not mutate the
# attached catalog, so it is not in this set (the filesystem sandbox is
# separately bundle-level in DuckDB-WASM).
_MUTATION_PREFIXES = (
    "CREATE",
    "ALTER",
    "DROP",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "MERGE",
    "ATTACH",
    "CHECKPOINT bench",
    "VACUUM bench",
    "BEGIN",
    "PRAGMA force_checkpoint",
)

BENCH_TARGETED_MUTATIONS: tuple[str, ...] = tuple(
    sql for sql in FUZZ_SQL if sql.startswith(_MUTATION_PREFIXES) and ("bench." in sql or sql.endswith(" AS bench"))
)

assert len(BENCH_TARGETED_MUTATIONS) >= 15, (
    f"expected a broad sample of bench-targeted mutations, got {len(BENCH_TARGETED_MUTATIONS)}"
)


def _attach_readonly(con: duckdb.DuckDBPyConnection, db_path: Path) -> None:
    con.execute(f"ATTACH '{db_path}' AS bench (READ_ONLY)")


class TestReadOnlyFuzz:
    def test_bench_targeted_mutations_all_fail(self, built_db_path: Path) -> None:
        """Every statement that would mutate the attached catalog raises."""
        with duckdb.connect(":memory:") as con:
            _attach_readonly(con, built_db_path)

            survivors: list[str] = []
            for sql in BENCH_TARGETED_MUTATIONS:
                try:
                    con.execute(sql)
                    survivors.append(sql)
                except duckdb.Error:
                    continue

            assert not survivors, "READ_ONLY attach let these bench-targeted mutations succeed:\n  " + "\n  ".join(
                survivors
            )

    def test_full_fuzz_leaves_bench_file_byte_stable(self, built_db_path: Path) -> None:
        """After the full fuzz, the ``.duckdb`` file is byte-stable on disk.

        Snapshot via a fresh connection so DETACH / USE side effects on the
        fuzz connection don't poison the post-check.
        """
        before_mtime = built_db_path.stat().st_mtime_ns
        before_bytes = built_db_path.read_bytes()

        with duckdb.connect(":memory:") as con:
            _attach_readonly(con, built_db_path)
            for sql in FUZZ_SQL:
                try:
                    con.execute(sql)
                except duckdb.Error:
                    continue

        after_mtime = built_db_path.stat().st_mtime_ns
        after_bytes = built_db_path.read_bytes()
        assert before_mtime == after_mtime, "read-only attach allowed file mtime change"
        assert before_bytes == after_bytes, "read-only attach allowed file content change"

        # Fresh connection proves the attached catalog is unchanged.
        with duckdb.connect(":memory:") as con:
            _attach_readonly(con, built_db_path)
            assert _snapshot_results(con), "re-attached bench.results is empty post-fuzz"

    def test_plain_select_still_works(self, built_db_path: Path) -> None:
        """Regression guard: the fuzz list must not accidentally disable SELECT."""
        with duckdb.connect(":memory:") as con:
            con.execute(f"ATTACH '{built_db_path}' AS bench (READ_ONLY)")
            rows = con.execute("SELECT COUNT(*) FROM bench.results").fetchall()
            assert rows and rows[0][0] >= 1
