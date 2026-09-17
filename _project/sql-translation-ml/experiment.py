"""Prepare execution-validated labels without exposing test outcomes to training."""

from __future__ import annotations

import argparse
import difflib
import importlib.metadata
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import sqlglot
from corpus import FEATURES, FIXTURES, SEED, cases
from oracle import connection, equivalent, execute, safe_query

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.dialect_utils import translate_sql_query

MODEL = "Salesforce/codet5-small"
REVISION = "b1ee9570c289f21b5922b9c768a1ce12957bf968"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def edits(original: str, target: str) -> list[dict]:
    return [
        {"start": i, "end": j, "text": target[a:b]}
        for op, i, j, a, b in difflib.SequenceMatcher(None, original, target, autojunk=False).get_opcodes()
        if op != "equal"
    ]


def apply_edits(original: str, replacements: list[dict]) -> str:
    if not isinstance(replacements, list):
        raise ValueError("edit output must be an array")
    position = 0
    pieces = []
    for edit in replacements:
        if not isinstance(edit, dict) or set(edit) != {"start", "end", "text"}:
            raise ValueError("invalid edit fields")
        start, end = edit["start"], edit["end"]
        if type(start) is not int or type(end) is not int or not isinstance(edit["text"], str):
            raise ValueError("invalid edit types")
        if not position <= start <= end <= len(original):
            raise ValueError("overlapping or out-of-bounds edit")
        pieces.extend([original[position:start], edit["text"]])
        position = end
    pieces.append(original[position:])
    return "".join(pieces)


def wire(case: dict, mode: str, baseline: str | None = None) -> str:
    value = {key: case[key] for key in ("sql", "source", "target", "schema", "settings")}
    value["versions"] = {"duckdb": duckdb.__version__, "sqlite": sqlite3.sqlite_version}
    value["task"] = "translate SQL" if mode == "full" else "emit JSON span edits"
    if mode == "edit":
        value["candidate"] = baseline
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class OraclePool:
    def __init__(self) -> None:
        self.connections = {
            (dialect, seed): connection(dialect, seed) for dialect in ("duckdb", "sqlite") for seed in FIXTURES
        }

    def results(self, sql: str, dialect: str) -> list:
        return [execute(self.connections[dialect, seed], sql, dialect) for seed in FIXTURES]

    def compare(self, expected: list, candidate: str, case: dict) -> dict:
        try:
            actual = self.results(candidate, case["target"])
            ordered = bool(safe_query(case["sql"], case["source"]).args.get("order"))
            matches = [equivalent(a, b, ordered) for a, b in zip(expected, actual, strict=True)]
            return {"equivalent": all(matches), "fixtures": matches}
        except Exception as exc:
            return {"equivalent": False, "error": f"{type(exc).__name__}: {exc}"}

    def close(self) -> None:
        for conn in self.connections.values():
            conn.close()


def prepare(run: Path) -> None:
    from transformers import AutoTokenizer

    if (run / "contract.json").exists():
        raise ValueError("run already exists; use a new run directory")
    run.mkdir(parents=True, exist_ok=True)
    contract = {
        "version": 1,
        "seed": SEED,
        "fixtures": FIXTURES,
        "features": FEATURES,
        "model": MODEL,
        "revision": REVISION,
        "duckdb": duckdb.__version__,
        "sqlite": sqlite3.sqlite_version,
        "sqlglot": importlib.metadata.version("sqlglot"),
        "train_pairs": 10000,
        "development_pairs": 2000,
        "test_structures_per_direction": 1000,
        "max_tokens": 1024,
        "max_epochs": 3,
        "max_training_seconds_per_model": 86400,
        "excluded": ["DDL", "DML", "recursive CTE", "extensions", "nondeterminism", "decimal", "timezone"],
    }
    write_json(run / "contract.json", contract)
    source = cases()
    authored = {(case["group_id"], case["source"]): case["sql"] for case in source}
    with (run / "source.jsonl").open("w") as stream:
        for case in source:
            stream.write(json.dumps(case, ensure_ascii=False) + "\n")
    write_json(
        run / "split.json",
        {
            case["case_id"]: {key: case[key] for key in ("family_id", "group_id", "structure", "split")}
            for case in source
        },
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    pool = OraclePool()
    counts: Counter = Counter()
    start = mono_time()
    try:
        with (run / "preparation.jsonl").open("w") as audit, (run / "labels.jsonl").open("w") as labels:
            for index, case in enumerate(source):
                expected = []
                record: dict[str, Any] = {"case_id": case["case_id"], "split": case["split"]}
                try:
                    expected = pool.results(case["sql"], case["source"])
                    record["eligible"] = True
                    record["source_row_counts"] = [len(result[1]) for result in expected]
                except Exception as exc:
                    record.update(eligible=False, error=f"invalid_source: {exc}")
                # Eligibility and splits precede translators. Locked tests are never labeled.
                if record["eligible"] and case["split"] != "test":
                    candidates = {}
                    for name in ("sqlglot", "benchbox"):
                        try:
                            sql = (
                                sqlglot.transpile(case["sql"], read=case["source"], write=case["target"])[0]
                                if name == "sqlglot"
                                else translate_sql_query(case["sql"], case["target"], case["source"], strict=True)
                            )
                            candidates[name] = {"sql": sql, **pool.compare(expected, sql, case)}
                        except Exception as exc:
                            candidates[name] = {"equivalent": False, "error": str(exc)}
                    record["candidates"] = candidates
                    accepted = next((c["sql"] for c in candidates.values() if c["equivalent"]), None)
                    method = "execution_validated_baseline"
                    if accepted is None:
                        native = authored[case["group_id"], case["target"]]
                        record["authored_validation"] = pool.compare(expected, native, case)
                        if record["authored_validation"]["equivalent"]:
                            accepted = native
                            method = "execution_validated_source_native_pair"
                    if accepted is not None:
                        baseline = candidates["sqlglot"].get("sql")
                        for mode in ("full", "edit"):
                            if mode == "edit" and baseline is None:
                                continue
                            prompt = wire(case, mode, baseline)
                            target = (
                                accepted
                                if mode == "full"
                                else json.dumps(edits(baseline, accepted), separators=(",", ":"))
                            )
                            lengths = [len(tokenizer.encode(text)) for text in (prompt, target, accepted)]
                            if max(lengths) > 1024:
                                counts[f"long/{mode}/{case['split']}"] += 1
                                continue
                            label = {
                                "case_id": case["case_id"],
                                "mode": mode,
                                "split": case["split"],
                                "input": prompt,
                                "output": target,
                                "gold": accepted,
                                "lengths": lengths,
                                "validation": "five_fixture_candidate_label",
                                "method": method,
                            }
                            labels.write(json.dumps(label, ensure_ascii=False) + "\n")
                            counts[f"accepted/{mode}/{case['split']}"] += 1
                audit.write(json.dumps(record, ensure_ascii=False) + "\n")
                counts["processed"] += 1
                if index % 100 == 0:
                    audit.flush()
                    labels.flush()
                    print(json.dumps({"counts": dict(counts), "seconds": elapsed_seconds(start)}), flush=True)
    finally:
        pool.close()
    write_json(run / "preparation-summary.json", dict(counts))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare"])
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    repo = Path(__file__).resolve().parents[2]
    if run == repo or repo in run.parents:
        parser.error("run directory must be outside the checkout")
    prepare(run)


if __name__ == "__main__":
    main()
