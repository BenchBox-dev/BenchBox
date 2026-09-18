# Query Plan Fixture Provenance

Every sample under this directory that was synthesized from documented
EXPLAIN output (rather than captured from a running engine) carries a
sibling `<fixture>.meta.json` sidecar:

```json
{"provenance": "synthetic", "models": "<what shape it models>", "validated_against_live": false}
```

When a fixture is diffed against real engine output, keep the synthetic
file for fast no-credential coverage, add the captured file alongside it,
and flip `validated_against_live` to `true` with the engine/version noted
in `models`.

## Parser validation status

| Parser | Fixture(s) | Live-validated |
|---|---|---|
| Presto/Trino (`presto_trino.py`) | `presto_explain_sample.json`, `trino_explain_sample.json`, `trino_distributed_explain_sample.json`, `athena_explain_sample.json` | No |
| ClickHouse (`clickhouse.py`) | `clickhouse_explain_plan_sample.txt`, `clickhouse_explain_pipeline_sample.txt` | No |
| Spark (`spark.py`) | `spark_explain_sample.txt` | No |
| Databend (`databend.py`) | `databend_explain_sample.txt` | No |
| QuestDB (`questdb.py`) | `questdb_explain_sample.txt` | No |
| Doris (`doris.py`) | `doris_shape_plan_sample.txt` | No |
| SingleStore (`singlestore.py`) | `singlestore_explain_sample.txt` | No |

Live hooks: `tests/integration/test_plan_capture_synthetic_parsers_live.py`
(Presto/Trino, ClickHouse, Spark) and
`tests/integration/test_misc_plan_capture_live.py`
(Databend, QuestDB, Doris, SingleStore). Each module skips unless its
engine env var is set.
