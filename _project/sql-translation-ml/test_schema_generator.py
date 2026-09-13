"""Execution and replay checks for the independent schema challenge."""

import pytest
from oracle import cell, equivalent, execute, safe_query
from schema_generator import generate
from tpch_fixtures import SCHEMA, SEEDS, connection, rows


@pytest.mark.parametrize("variants", [1, 2])
def test_generation_replays_and_covers_available_pairs(variants):
    first, coverage = generate(variants)
    assert first == generate(variants)[0]
    assert len(first) == 936 * variants
    assert len({c["case_id"] for c in first}) == len(first)
    assert {c["family_id"] for c in first} == set(coverage["targets"])
    assert len(coverage["unavailable"]) == 108
    assert set(SCHEMA) == {t for c in first for t in c["schema"]}
    assert any("\n" in c["sql"] for c in first) == (variants == 2)
    assert any('"Result Value"' in c["sql"] for c in first)
    with pytest.raises(ValueError, match="1 or 2"):
        generate(3)


def test_all_scheduled_queries_execute_in_source_engine():
    cases, _ = generate(1)
    for dialect in ("duckdb", "sqlite"):
        conn = connection(dialect, SEEDS[0])
        try:
            for case in cases:
                if case["source"] == dialect:
                    result = execute(conn, case["sql"], dialect, schema=SCHEMA)
                    assert result[0] > 0
        finally:
            conn.close()


def test_independent_queries_bind_and_agree_across_fixtures():
    from independent_queries import QUERIES

    for seed in SEEDS:
        left, right = connection("duckdb", seed), connection("sqlite", seed)
        try:
            for query in QUERIES:
                a = execute(left, query["sql"], "duckdb", schema=SCHEMA)
                b = execute(right, query["sql"], "sqlite", schema=SCHEMA)
                assert equivalent(a, b, bool(safe_query(query["sql"], "duckdb", SCHEMA).args.get("order"))), query["id"]
        finally:
            left.close()
            right.close()


def test_new_schema_does_not_expand_original_allowlist():
    with pytest.raises(ValueError, match="unknown table"):
        safe_query("SELECT * FROM orders", "duckdb")
    safe_query("SELECT * FROM orders", "duckdb", SCHEMA)
    for sql in ("SELECT * FROM read_csv('/tmp/data')", "DELETE FROM orders", "SELECT random() FROM orders"):
        with pytest.raises(ValueError):
            safe_query(sql, "duckdb", SCHEMA)


def test_fixtures_replay_and_preserve_key_relationships():
    from benchbox.core.tpch.schema import TABLES

    for seed in SEEDS:
        data = rows(seed)
        assert data == rows(seed)
        for table in TABLES:
            for index, column in enumerate(table.columns):
                if not column.nullable:
                    assert all(row[index] is not None for row in data[table.name])
                if column.foreign_key:
                    parent, key = column.foreign_key
                    target_index = list(SCHEMA[parent]).index(key)
                    assert {r[index] for r in data[table.name]} <= {r[target_index] for r in data[parent]}
    assert rows(SEEDS[-1])["lineitem"] == []


def test_decimal_comparison_is_exact():
    from decimal import Decimal

    assert cell(Decimal("2")) == cell(2)
    assert cell(Decimal("0.1")) != cell(0.1)
    with pytest.raises(ValueError, match="nonfinite"):
        cell(Decimal("NaN"))


def test_frozen_challenge_rejects_input_drift_and_overwrite(tmp_path, monkeypatch):
    import schema_evaluate as runner

    cases, coverage = generate(1)
    monkeypatch.setattr(runner, "identities", lambda path: {})
    monkeypatch.setattr(runner, "generate", lambda variants: (cases[:2], coverage))
    monkeypatch.setattr(runner, "QUERIES", [])
    run = tmp_path / "challenge"
    runner.prepare(run, tmp_path / "training", 1)
    runner.verify(run)
    with monkeypatch.context() as scoped:
        scoped.setattr(runner, "rows", lambda seed: {})
        with pytest.raises(ValueError, match="fixture regeneration drift"):
            runner.verify(run)
    original_dependencies = runner.dependency_hashes()
    with monkeypatch.context() as scoped:
        scoped.setattr(runner, "dependency_hashes", lambda: dict(original_dependencies, dialect_utils="changed"))
        with pytest.raises(ValueError, match="BenchBox dependency changed"):
            runner.verify(run)
    with pytest.raises(ValueError, match="new output"):
        runner.prepare(run, tmp_path / "training", 1)
    (run / "cases.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="frozen input changed"):
        runner.verify(run)


def test_edit_prompt_budget_is_distinct_from_common_source_budget(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import schema_evaluate as runner

    cases, coverage = generate(1)
    monkeypatch.setattr(runner, "identities", lambda path: {})
    monkeypatch.setattr(runner, "generate", lambda variants: (cases[:2], coverage))
    monkeypatch.setattr(runner, "QUERIES", [])
    run = tmp_path / "challenge"
    runner.prepare(run, tmp_path / "training", 1)
    tokenizer = SimpleNamespace(encode=lambda text: list(text))
    monkeypatch.setattr(runner.AutoTokenizer, "from_pretrained", lambda path: tokenizer)
    monkeypatch.setattr(
        runner.AutoModelForSeq2SeqLM, "from_pretrained", lambda path: SimpleNamespace(eval=lambda: None)
    )
    monkeypatch.setattr(runner.sqlglot, "transpile", lambda *args, **kwargs: ["SELECT 1 " * 200])

    def reject(model, tokenizer, prompt, mode, device):
        assert len(tokenizer.encode(prompt)) > 1024
        raise ValueError("input exceeds 1024 tokens")

    monkeypatch.setattr(runner, "infer", reject)
    runner.evaluate(run, "edit")
    for result in runner.load_lines(run / "outcomes-edit.jsonl"):
        assert result["within_source_budget"]
        assert not result["within_model_budget"]
        assert not result["success"]


def test_candidate_cannot_reference_unprovided_table():
    from schema_evaluate import Pool

    pool = Pool()
    try:
        schema = {"orders": SCHEMA["orders"]}
        source = "SELECT o_orderkey FROM orders"
        candidate = source + " WHERE EXISTS (SELECT 1 FROM region)"
        assert pool.results(source, "sqlite", SCHEMA) == pool.results(candidate, "sqlite", SCHEMA)
        with pytest.raises(ValueError, match="unknown table"):
            pool.results(candidate, "sqlite", schema)
    finally:
        pool.close()
