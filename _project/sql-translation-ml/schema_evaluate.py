"""Freeze a schema-based challenge corpus, then evaluate immutable checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import sqlglot
import torch
from artifacts import checkpoint, inputs
from evaluate import check_runtime
from experiment import load_lines, wire, write_json
from independent_queries import QUERIES
from oracle import equivalent, execute, safe_query
from schema_generator import generate, record
from tpch_fixtures import SCHEMA, SEEDS, connection, rows
from train import infer
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from benchbox.core import schema_primitives
from benchbox.core.tpch import schema as tpch_schema
from benchbox.utils import clock, dialect_utils
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.dialect_utils import translate_sql_query

SYSTEMS = ("sqlglot", "benchbox", "full", "edit")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identities(training: Path) -> dict:
    check_runtime(training)
    result = {}
    for mode in ("full", "edit"):
        metadata = json.loads((training / f"model-{mode}/training.json").read_text())
        actual = checkpoint(training / f"model-{mode}/selected")
        if actual != metadata["selected_checkpoint"] or inputs(training) != metadata["input_hashes"]:
            raise ValueError("frozen training identity changed")
        result[mode] = actual
    return result


def dependency_hashes() -> dict:
    modules = (schema_primitives, tpch_schema, clock, dialect_utils)
    result = {module.__name__: sha(Path(module.__file__)) for module in modules}
    result["tpch/schema_specs.yaml"] = sha(Path(tpch_schema.__file__).with_name("schema_specs.yaml"))
    return result


class Pool:
    def __init__(self) -> None:
        self.connections = {(d, s): connection(d, s) for d in ("duckdb", "sqlite") for s in SEEDS}

    def results(self, sql: str, dialect: str, schema: dict) -> list:
        return [execute(self.connections[dialect, seed], sql, dialect, schema=schema) for seed in SEEDS]

    def close(self) -> None:
        for conn in self.connections.values():
            conn.close()


def prepare(run: Path, training: Path, variants: int) -> None:
    model_ids = identities(training)
    if run.exists():
        raise ValueError("new output directory required; never overwrite a frozen suite")
    run.mkdir(parents=True)
    cases, coverage = generate(variants)
    for query in QUERIES:
        for dialect in ("duckdb", "sqlite"):
            cases.append(record(query["sql"], dialect, query["id"], query["feature_tags"], "independent"))
    write_json(run / "capabilities.json", coverage)
    write_json(run / "fixtures.json", {str(seed): rows(seed) for seed in SEEDS})
    # Freeze every attempted source before validation; rejected cases stay visible.
    with (run / "cases.jsonl").open("w") as stream:
        for case in cases:
            stream.write(json.dumps(case, ensure_ascii=False) + "\n")
    pool = Pool()
    validations = []
    try:
        for case in cases:
            entry = {"case_id": case["case_id"], "valid": False}
            try:
                results = pool.results(case["sql"], case["source"], case["schema"])
                entry.update(valid=True, row_counts=[len(r[1]) for r in results])
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            validations.append(entry)
    finally:
        pool.close()
    write_json(run / "source-validation.json", validations)
    local = Path(__file__).parent
    provenance = [
        "schema_generator.py",
        "tpch_fixtures.py",
        "independent_queries.py",
        "schema_evaluate.py",
        "oracle.py",
        "train.py",
        "experiment.py",
        "artifacts.py",
        "corpus.py",
        "uv.lock",
    ]
    write_json(
        run / "contract.json",
        {
            "training": str(training.resolve()),
            "models": model_ids,
            "benchbox_dependencies": dependency_hashes(),
            "seeds": SEEDS,
            "inputs": {p.name: sha(p) for p in run.iterdir() if p.is_file()},
            "code": {name: sha(local / name) for name in provenance},
            "schema": SCHEMA,
            "max_input_tokens": 1024,
            "max_query_seconds": 2,
            "purpose": "post-training independent challenge; never used for checkpoint selection",
        },
    )
    print(json.dumps({"cases": len(cases), "source_valid": sum(bool(v["valid"]) for v in validations)}), flush=True)


def verify(run: Path) -> tuple[dict, Path]:
    contract = json.loads((run / "contract.json").read_text())
    training = Path(contract["training"])
    if contract["schema"] != SCHEMA:
        raise ValueError("TPC-H schema changed")
    if contract["benchbox_dependencies"] != dependency_hashes():
        raise ValueError("BenchBox dependency changed")
    if identities(training) != contract["models"]:
        raise ValueError("model identity drift")
    for name, expected in contract["inputs"].items():
        if sha(run / name) != expected:
            raise ValueError(f"frozen input changed: {name}")
    frozen_fixtures = json.loads((run / "fixtures.json").read_text())
    regenerated = json.loads(json.dumps({str(seed): rows(seed) for seed in SEEDS}))
    if frozen_fixtures != regenerated:
        raise ValueError("fixture regeneration drift")
    for name, expected in contract["code"].items():
        if sha(Path(__file__).parent / name) != expected:
            raise ValueError(f"frozen code changed: {name}; use a new run")
    return contract, training


def evaluate(run: Path, system: str) -> None:
    _, training = verify(run)
    path = run / f"outcomes-{system}.jsonl"
    if path.exists():
        raise ValueError("outcomes already exist; no overwrite or feedback retry")
    cases = load_lines(run / "cases.jsonl")
    validations = {v["case_id"]: v for v in json.loads((run / "source-validation.json").read_text())}
    torch.set_num_threads(4)
    tokenizer = AutoTokenizer.from_pretrained(training / "model-full/selected")
    model = None
    if system in ("full", "edit"):
        tokenizer = AutoTokenizer.from_pretrained(training / f"model-{system}/selected")
        model = AutoModelForSeq2SeqLM.from_pretrained(training / f"model-{system}/selected").eval()
    pool = Pool()
    deadline = mono_time() + 3600
    try:
        with path.open("w") as stream:
            for index, case in enumerate(cases):
                if mono_time() >= deadline:
                    raise TimeoutError("one-hour evaluation budget reached; partial outcomes retained")
                outcome = {k: case[k] for k in ("case_id", "family_id", "suite", "source", "features", "structure")}
                outcome.update(source_valid=validations[case["case_id"]]["valid"], success=False)
                outcome["source_input_tokens"] = len(tokenizer.encode(wire(case, "full")))
                outcome["within_source_budget"] = outcome["source_input_tokens"] <= 1024
                start = mono_time()
                try:
                    if not outcome["source_valid"]:
                        raise ValueError("source invalid; excluded from translator denominator")
                    if system == "full":
                        outcome["model_input_tokens"] = outcome["source_input_tokens"]
                        outcome["within_model_budget"] = outcome["within_source_budget"]
                        candidate, _ = infer(model, tokenizer, wire(case, "full"), "full", "cpu")
                    elif system == "benchbox":
                        candidate = translate_sql_query(case["sql"], case["target"], case["source"], strict=True)
                    else:
                        candidate = sqlglot.transpile(case["sql"], read=case["source"], write=case["target"])[0]
                        if system == "edit":
                            prompt = wire(case, "edit", candidate)
                            outcome["model_input_tokens"] = len(tokenizer.encode(prompt))
                            outcome["within_model_budget"] = outcome["model_input_tokens"] <= 1024
                            candidate, _ = infer(model, tokenizer, prompt, "edit", "cpu")
                    outcome["translation_seconds"] = elapsed_seconds(start)
                    outcome["candidate"] = candidate
                    expected = pool.results(case["sql"], case["source"], case["schema"])
                    actual = pool.results(candidate, case["target"], case["schema"])
                    ordered = bool(safe_query(case["sql"], case["source"], SCHEMA).args.get("order"))
                    matches = [equivalent(a, b, ordered) for a, b in zip(expected, actual, strict=True)]
                    outcome.update(success=all(matches), fixtures=matches)
                except Exception as exc:
                    outcome["error"] = f"{type(exc).__name__}: {exc}"
                outcome.setdefault("translation_seconds", elapsed_seconds(start))
                stream.write(json.dumps(outcome, ensure_ascii=False) + "\n")
                if index % 20 == 0:
                    stream.flush()
                    print(json.dumps({"system": system, "processed": index + 1, "total": len(cases)}), flush=True)
    finally:
        pool.close()
    verify(run)
    write_json(run / f"complete-{system}.json", {"sha256": sha(path), "cases": len(cases)})


def report(run: Path) -> None:
    verify(run)
    cases = load_lines(run / "cases.jsonl")
    valid = {v["case_id"]: v for v in json.loads((run / "source-validation.json").read_text())}
    summary = {"coverage": {}, "systems": {}}
    for family in sorted({c["family_id"] for c in cases}):
        members = [c for c in cases if c["family_id"] == family]
        summary["coverage"][family] = {
            "attempted": len(members),
            "source_valid": sum(valid[c["case_id"]]["valid"] for c in members),
            "nonempty_witness": sum(any(valid[c["case_id"]].get("row_counts", [])) for c in members),
        }
    lines = [
        "# Frozen-model schema challenge",
        "",
        "Accuracy describes this finite challenge, not all SQL.",
        "",
        "| System | Suite | Source | Correct / valid | Source prompt <=1024 tokens |",
        "| --- | --- | --- | --- | --- |",
    ]
    for system in SYSTEMS:
        path = run / f"outcomes-{system}.jsonl"
        receipt = json.loads((run / f"complete-{system}.json").read_text())
        data = load_lines(path)
        if sha(path) != receipt["sha256"] or len(data) != len(cases):
            raise ValueError("outcomes incomplete or changed")
        groups = {}
        for suite in ("generated", "independent"):
            for dialect in ("duckdb", "sqlite"):
                group = [r for r in data if r["suite"] == suite and r["source"] == dialect and r["source_valid"]]
                bounded = [r for r in group if r["within_source_budget"]]
                k = sum(r["success"] for r in group)
                bk = sum(r["success"] for r in bounded)
                groups[f"{suite}/{dialect}"] = {
                    "n": len(group),
                    "k": k,
                    "within_budget_n": len(bounded),
                    "within_budget_k": bk,
                    "over_model_budget": sum(r.get("within_model_budget") is False for r in group),
                    "structures": len({r["structure"] for r in group}),
                    "median_seconds": float(np.median([r["translation_seconds"] for r in group])),
                    "errors": dict(
                        Counter(r.get("error", "result mismatch").split(":")[0] for r in group if not r["success"])
                    ),
                    "features": {
                        feature: {
                            "n": sum(feature in r["features"] for r in group),
                            "k": sum(r["success"] and feature in r["features"] for r in group),
                        }
                        for feature in sorted({f for r in group for f in r["features"]})
                    },
                    "token_bins": {
                        f"{low}-{high}": {
                            "n": sum(low <= r["source_input_tokens"] <= high for r in group),
                            "k": sum(r["success"] and low <= r["source_input_tokens"] <= high for r in group),
                        }
                        for low, high in ((0, 256), (257, 512), (513, 1024), (1025, 1000000))
                    },
                }
                lines.append(f"| {system} | {suite} | {dialect} | {k}/{len(group)} | {bk}/{len(bounded)} |")
        summary["systems"][system] = groups
    write_json(run / "summary.json", summary)
    (run / "report.md").write_text("\n".join(lines) + "\n")
    write_json(
        run / "manifest.json", {p.name: sha(p) for p in run.iterdir() if p.is_file() and p.name != "manifest.json"}
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "evaluate", "report"])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--training-dir", type=Path)
    parser.add_argument("--variants", type=int, default=2)
    parser.add_argument("--system", choices=SYSTEMS)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.training_dir is None:
            parser.error("prepare requires --training-dir")
        prepare(args.run_dir, args.training_dir, args.variants)
    elif args.action == "evaluate":
        if args.system is None:
            parser.error("evaluate requires --system")
        evaluate(args.run_dir, args.system)
    else:
        report(args.run_dir)
