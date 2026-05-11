"""Unit tests for the JoinOrder canonical data build script."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "build_joinorder_data"
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_joinorder_data = _load_script()


def _metadata(files: list[dict]) -> dict:
    return {"data": {"latestVersion": {"files": files}}}


def test_select_pgdump_file_extracts_dataverse_download_metadata() -> None:
    metadata = _metadata(
        [
            {
                "label": "imdb_pg11",
                "dataFile": {
                    "id": 3590041,
                    "filesize": 1_277_543_282,
                    "checksum": {
                        "type": "MD5",
                        "value": "df3e976b235288005cb410cea09a115f",
                    },
                },
            }
        ]
    )

    dataverse_file = build_joinorder_data.select_pgdump_file(metadata)

    assert dataverse_file.file_id == 3590041
    assert dataverse_file.label == "imdb_pg11"
    assert dataverse_file.filesize == 1_277_543_282
    assert dataverse_file.checksum_type == "MD5"
    assert dataverse_file.download_url.endswith("/api/access/datafile/3590041")


def test_select_pgdump_file_rejects_ambiguous_metadata() -> None:
    metadata = _metadata(
        [
            {
                "label": "imdb_pg11",
                "dataFile": {"id": 1, "filesize": 10, "checksum": {"type": "MD5", "value": "a"}},
            },
            {
                "label": "imdb_pg11",
                "dataFile": {"id": 2, "filesize": 10, "checksum": {"type": "MD5", "value": "b"}},
            },
        ]
    )

    with pytest.raises(build_joinorder_data.DataverseMetadataError, match="exactly one"):
        build_joinorder_data.select_pgdump_file(metadata)


def test_validate_row_counts_accepts_one_percent_edge() -> None:
    row_counts = dict(build_joinorder_data.EXPECTED_ROW_COUNTS)
    expected = build_joinorder_data.EXPECTED_ROW_COUNTS["movie_info"]
    row_counts["movie_info"] = expected + int(expected * 0.01)

    validation = build_joinorder_data.validate_row_counts(row_counts)

    assert validation.ok
    assert validation.row_count_failures == []


def test_validate_row_counts_reports_missing_and_out_of_tolerance_tables() -> None:
    row_counts = dict(build_joinorder_data.EXPECTED_ROW_COUNTS)
    row_counts.pop("aka_title")
    row_counts["cast_info"] = build_joinorder_data.EXPECTED_ROW_COUNTS["cast_info"] + 400_000

    validation = build_joinorder_data.validate_row_counts(row_counts, unexpected_tables=["extra_table"])

    assert not validation.ok
    assert validation.missing_tables == ["aka_title"]
    assert validation.unexpected_tables == ["extra_table"]
    assert [(failure.table, failure.expected, failure.actual) for failure in validation.row_count_failures] == [
        ("cast_info", 36_244_344, 36_644_344)
    ]


def test_validate_pgdump_file_requires_custom_format_magic(tmp_path: Path) -> None:
    dump_path = tmp_path / "imdb_pg11"
    dump_path.write_bytes(b"not-a-pgdump")
    sha256, md5, size = build_joinorder_data.hash_file(dump_path)
    dataverse_file = build_joinorder_data.DataverseFile(
        file_id=3590041,
        label="imdb_pg11",
        filesize=size,
        checksum_type="MD5",
        checksum_value=md5,
        download_url="https://example.invalid/file",
    )
    assert sha256

    with pytest.raises(build_joinorder_data.DownloadIntegrityError, match="custom-format"):
        build_joinorder_data.validate_pgdump_file(dump_path, dataverse_file)


def test_write_build_manifest_records_source_sha256(tmp_path: Path) -> None:
    dataverse_file = build_joinorder_data.DataverseFile(
        file_id=3590041,
        label="imdb_pg11",
        filesize=5,
        checksum_type="MD5",
        checksum_value="275876e34cf609db118f3d84b799a790",
        download_url="https://dataverse.harvard.edu/api/access/datafile/3590041",
    )
    artifact = build_joinorder_data.PgDumpArtifact(
        path=tmp_path / "source" / "imdb_pg11",
        size=5,
        sha256="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        md5="275876e34cf609db118f3d84b799a790",
        dataverse_file=dataverse_file,
    )

    manifest_path = build_joinorder_data.write_source_manifest(tmp_path, artifact, reused=False)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset_version"] == "joinorder-imdb-2013-v1"
    assert manifest["source"]["sha256"] == artifact.sha256
    assert manifest["source"]["dataverse_file_id"] == 3590041
    assert manifest["source"]["reused_existing_file"] is False


def test_download_pgdump_recovers_invalid_cached_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    destination = source_dir / "imdb_pg11"
    destination.write_bytes(b"truncated")
    valid_payload = b"PGDMPvalid"
    dataverse_file = build_joinorder_data.DataverseFile(
        file_id=3590041,
        label="imdb_pg11",
        filesize=len(valid_payload),
        checksum_type="MD5",
        checksum_value=hashlib.md5(valid_payload, usedforsecurity=False).hexdigest(),
        download_url="https://dataverse.harvard.edu/api/access/datafile/3590041",
    )

    def fake_download(_url: str, path: Path) -> None:
        assert path.name == "imdb_pg11.part"
        path.write_bytes(valid_payload)

    monkeypatch.setattr(build_joinorder_data, "resolve_dataverse_file", lambda: dataverse_file)
    monkeypatch.setattr(build_joinorder_data, "download_to_file", fake_download)

    artifact = build_joinorder_data.download_pgdump(tmp_path)

    assert destination.read_bytes() == valid_payload
    assert not destination.with_name("imdb_pg11.part").exists()
    assert artifact.path == destination
    assert artifact.sha256 == hashlib.sha256(valid_payload).hexdigest()


def test_query_aliases_and_underlying_count_sql_parse_flat_job_query() -> None:
    sql = """\
SELECT MIN(mc.note), MIN(t.title)
FROM company_type AS ct,
     movie_companies AS mc,
     title AS t
WHERE ct.kind = 'production companies'
  AND ct.id = mc.company_type_id
  AND t.id = mc.movie_id;
"""

    aliases = build_joinorder_data.query_aliases(sql, query_id="1a")
    count_sql = build_joinorder_data.underlying_count_sql(sql, query_id="1a")
    id_sql = build_joinorder_data.alias_id_sql(sql, query_id="1a", limit=2)

    assert aliases == [
        build_joinorder_data.QueryAlias(table="company_type", alias="ct"),
        build_joinorder_data.QueryAlias(table="movie_companies", alias="mc"),
        build_joinorder_data.QueryAlias(table="title", alias="t"),
    ]
    assert count_sql.startswith("SELECT count(*) FROM company_type AS ct")
    assert "WHERE ct.kind = 'production companies'" in count_sql
    assert 'ct.id AS "ct__id"' in id_sql
    assert id_sql.endswith("LIMIT 2")


def test_underlying_count_contract_allows_only_canonical_known_zero_queries() -> None:
    assert build_joinorder_data.underlying_count_failure("2c", 0) is None
    assert build_joinorder_data.underlying_count_failure("1a", 1) is None

    assert build_joinorder_data.underlying_count_failure("1a", 0) == {
        "query_id": "1a",
        "expected_underlying_row_count": ">=1",
        "actual_underlying_row_count": 0,
        "reason": "unexpected_empty",
    }
    assert build_joinorder_data.underlying_count_failure("2c", 1) == {
        "query_id": "2c",
        "expected_underlying_row_count": 0,
        "actual_underlying_row_count": 1,
        "reason": "known_zero_drift",
    }


def test_validate_predicate_domain_accepts_known_zero_and_exact_null_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    query_dir = tmp_path / "queries"
    query_dir.mkdir()
    (query_dir / "1a.sql").write_text("SELECT MIN(t.id) FROM title AS t WHERE t.id > 0;", encoding="utf-8")
    (query_dir / "2c.sql").write_text("SELECT MIN(t.id) FROM title AS t WHERE t.id < 0;", encoding="utf-8")

    def fake_psql(*, container_name: str, database: str, user: str, sql: str) -> str:
        assert container_name == "pg"
        assert database == "imdb"
        assert user == "postgres"
        if "t.id < 0" in sql:
            return "0\n"
        if "t.id > 0" in sql:
            return "7\n"
        raise AssertionError(sql)

    def fake_psql_json_rows(*, container_name: str, database: str, user: str, sql: str) -> list[dict]:
        assert container_name == "pg"
        assert database == "imdb"
        assert user == "postgres"
        for (table, _column), (nulls, rows) in build_joinorder_data.CANONICAL_NULL_COUNTS.items():
            if f'FROM public."{table}"' in sql:
                return [{"row_count": rows, "null_count": nulls}]
        raise AssertionError(sql)

    monkeypatch.setattr(build_joinorder_data, "psql", fake_psql)
    monkeypatch.setattr(build_joinorder_data, "psql_json_rows", fake_psql_json_rows)

    report = build_joinorder_data.validate_predicate_domain(
        work_dir=tmp_path,
        query_dir=query_dir,
        container_name="pg",
        database="imdb",
        user="postgres",
        expected_query_count=None,
    )

    assert report["query_failures"] == []
    assert report["known_zero_underlying_row_counts"] == {"2c": 0}
    assert report["query_underlying_row_counts"] == {"1a": 7, "2c": 0}
    assert report["null_count_failures"] == []


def test_validate_predicate_domain_rejects_unexpected_empty_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    query_dir = tmp_path / "queries"
    query_dir.mkdir()
    (query_dir / "1a.sql").write_text("SELECT MIN(t.id) FROM title AS t WHERE t.id > 0;", encoding="utf-8")

    monkeypatch.setattr(build_joinorder_data, "psql", lambda **_kwargs: "0\n")
    monkeypatch.setattr(
        build_joinorder_data,
        "psql_json_rows",
        lambda **_kwargs: [{"row_count": 2_609_129, "null_count": 1_271_989}],
    )

    with pytest.raises(build_joinorder_data.JoinOrderBuildError, match="1 unexpected empty"):
        build_joinorder_data.validate_predicate_domain(
            work_dir=tmp_path,
            query_dir=query_dir,
            container_name="pg",
            database="imdb",
            user="postgres",
            expected_query_count=None,
        )


def test_validate_predicate_domain_rejects_incomplete_query_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    query_dir = tmp_path / "queries"
    query_dir.mkdir()
    (query_dir / "1a.sql").write_text("SELECT MIN(t.id) FROM title AS t WHERE t.id > 0;", encoding="utf-8")

    monkeypatch.setattr(build_joinorder_data, "psql", lambda **_kwargs: "7\n")
    monkeypatch.setattr(
        build_joinorder_data,
        "psql_json_rows",
        lambda **_kwargs: [{"row_count": 2_609_129, "null_count": 1_271_989}],
    )

    with pytest.raises(build_joinorder_data.JoinOrderBuildError, match="query-count failures"):
        build_joinorder_data.validate_predicate_domain(
            work_dir=tmp_path,
            query_dir=query_dir,
            container_name="pg",
            database="imdb",
            user="postgres",
            expected_query_count=build_joinorder_data.EXPECTED_QUERY_COUNT,
        )


def test_aggregate_table_hash_is_deterministic_independent_of_input_order(tmp_path: Path) -> None:
    a = build_joinorder_data.TableFile("aka_name", tmp_path / "a.parquet", "a" * 64, 10, 1)
    b = build_joinorder_data.TableFile("title", tmp_path / "t.parquet", "b" * 64, 20, 2)

    assert build_joinorder_data.aggregate_table_hash([a, b]) == build_joinorder_data.aggregate_table_hash([b, a])


def test_render_data_manifest_writes_self_consistent_hash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(build_joinorder_data, "git_head_sha", lambda: "abc123")
    schema = {
        "title": [
            build_joinorder_data.ColumnSchema(
                table="title",
                name="id",
                postgres_type="integer",
                udt_name="int4",
                ordinal_position=1,
                is_nullable=False,
            ),
            build_joinorder_data.ColumnSchema(
                table="title",
                name="title",
                postgres_type="character varying",
                udt_name="varchar",
                ordinal_position=2,
                is_nullable=True,
            ),
        ]
    }
    table_files = [
        build_joinorder_data.TableFile(
            table="title",
            path=tmp_path / "title.parquet",
            sha256="c" * 64,
            bytes=123,
            row_count=2,
        )
    ]
    manifest_path = tmp_path / "data_manifest.toml"

    build_joinorder_data.render_data_manifest(
        work_dir=tmp_path,
        schema=schema,
        table_files=table_files,
        url="https://example.com/archive.tar.zst",
        archive_sha256="d" * 64,
        output_path=manifest_path,
    )

    text = manifest_path.read_text(encoding="utf-8")
    assert f'manifest_hash = "{build_joinorder_data.compute_manifest_hash(manifest_path)}"' in text
    assert 'schema.id = "integer"' in text
    assert 'schema.title = "character varying"' in text


def test_manifest_hash_ignores_archive_sha256_after_packaging(tmp_path: Path) -> None:
    manifest = tmp_path / "data_manifest.toml"
    archive_hash_a = "a" * 64
    archive_hash_b = "b" * 64
    manifest.write_text(
        "\n".join(
            [
                'dataset_version = "joinorder-imdb-2013-v1"',
                'manifest_hash = "0"',
                f'archive_sha256 = "{archive_hash_a}"',
                'data_archive_hash = "logical"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    before = build_joinorder_data.compute_manifest_hash(manifest)
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(archive_hash_a, archive_hash_b), encoding="utf-8")

    assert build_joinorder_data.compute_manifest_hash(manifest) == before
