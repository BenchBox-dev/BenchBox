"""Locked-test execution outcomes and conservative directional uncertainty."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import numpy as np
import psutil
import sqlglot
import torch
from artifacts import checkpoint, inputs, runtime
from corpus import SEED
from experiment import MODEL, REVISION, OraclePool, load_lines, wire, write_json
from scipy.stats import beta
from supplemental import cases as supplemental_cases
from train import infer
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.dialect_utils import translate_sql_query


def bounds(outcomes: list[dict]) -> dict:
    n = len(outcomes)
    k = sum(record["success"] for record in outcomes)
    families = defaultdict(list)
    for record in outcomes:
        families[record["family_id"]].append(record["success"])
    exact = float(beta.ppf(0.05, k, n - k + 1)) if k else 0.0
    clusters = list(families.values())
    rng = np.random.default_rng(SEED)
    bootstrap = []
    if clusters:
        totals = np.array([len(cluster) for cluster in clusters])
        successes = np.array([sum(cluster) for cluster in clusters])
        for _ in range(10000):
            sample = rng.integers(0, len(clusters), len(clusters))
            bootstrap.append(float(successes[sample].sum() / totals[sample].sum()))
    lower = sorted(bootstrap)[499] if bootstrap else 0.0
    # Requiring every member of a family to pass protects against the degenerate
    # all-success bootstrap (whose lower bound is otherwise exactly one).
    family_k = sum(all(cluster) for cluster in clusters)
    family_exact = float(beta.ppf(0.05, family_k, len(clusters) - family_k + 1)) if family_k else 0.0
    return {
        "n": n,
        "k": k,
        "accuracy": k / n if n else None,
        "exact_lower": exact,
        "families": len(clusters),
        "cluster_bootstrap_lower": lower,
        "all_members_family_lower": family_exact,
        "decision_lower": min(exact, lower, family_exact),
        "sufficient_families": len(clusters) >= 100,
    }


def check_runtime(run: Path) -> None:
    contract = json.loads((run / "contract.json").read_text(encoding="utf-8"))
    if (contract["model"], contract["revision"]) != (MODEL, REVISION):
        raise ValueError("model/tokenizer identity changed")
    for name, actual in {
        "duckdb": duckdb.__version__,
        "sqlite": sqlite3.sqlite_version,
        "sqlglot": importlib.metadata.version("sqlglot"),
    }.items():
        if contract[name] != actual:
            raise ValueError(f"runtime drift: {name}")


def evaluate(run: Path, system: str) -> None:
    check_runtime(run)
    output = run / f"evaluation-{system}.jsonl"
    if output.exists():
        raise ValueError("locked-test outcomes already exist; do not overwrite")
    sources = [case for case in load_lines(run / "source.jsonl") if case["split"] == "test"]
    preparation = {r["case_id"]: r for r in load_lines(run / "preparation.jsonl")}
    seen = set()
    cases = []
    # Count each normalized structure once per direction; variants are supplementary.
    for case in sources:
        key = (case["source"], case["structure"])
        if key not in seen and preparation[case["case_id"]]["eligible"]:
            cases.append(case)
            seen.add(key)
    torch.set_num_threads(4)
    cold = mono_time()
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    model = None
    model_identity = None
    if system in ("full", "edit"):
        if not (run / f"model-{system}" / "training.json").exists():
            raise ValueError("model training incomplete")
        training = json.loads((run / f"model-{system}" / "training.json").read_text(encoding="utf-8"))
        if training["input_hashes"] != inputs(run):
            raise ValueError("training input drift")
        model_identity = checkpoint(run / f"model-{system}" / "selected")
        if model_identity != training["selected_checkpoint"]:
            raise ValueError("selected checkpoint changed")
        tokenizer = AutoTokenizer.from_pretrained(run / f"model-{system}" / "selected")
        model = AutoModelForSeq2SeqLM.from_pretrained(run / f"model-{system}" / "selected").to("cpu").eval()
    cold_seconds = elapsed_seconds(cold)
    pool = OraclePool()
    try:
        for case in supplemental_cases():
            expected = pool.results(case["sql"], case["source"])
            preparation[case["case_id"]] = {"source_row_counts": [len(result[1]) for result in expected]}
            cases.append(case)
        with output.open("w", encoding="utf-8") as stream:
            for index, case in enumerate(cases):
                record = {key: case[key] for key in ("case_id", "family_id", "structure", "source", "features")}
                source_tokens = len(tokenizer.encode(wire(case, "full")))
                record.update(
                    system=system,
                    success=False,
                    eligible=True,
                    suite=case["split"],
                    source_tokens=source_tokens,
                    held_out_workload=case["held_out_workload"],
                    all_fixtures_empty=not any(preparation[case["case_id"]]["source_row_counts"]),
                )
                start = mono_time()
                try:
                    if source_tokens > 1024:
                        record["eligible"] = False
                        raise ValueError("source-only long input")
                    if system == "benchbox":
                        candidate = translate_sql_query(case["sql"], case["target"], case["source"], strict=True)
                    elif system == "full":
                        candidate, record["output_tokens"] = infer(model, tokenizer, wire(case, "full"), "full", "cpu")
                    else:
                        candidate = sqlglot.transpile(case["sql"], read=case["source"], write=case["target"])[0]
                        if system == "edit":
                            candidate, record["output_tokens"] = infer(
                                model, tokenizer, wire(case, "edit", candidate), "edit", "cpu"
                            )
                    record["translation_seconds"] = elapsed_seconds(start)
                    record["candidate"] = candidate
                    expected = pool.results(case["sql"], case["source"])
                    record["validation"] = pool.compare(expected, candidate, case)
                    record["success"] = record["validation"]["equivalent"]
                except Exception as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    record.setdefault("translation_seconds", elapsed_seconds(start))
                record["rss"] = psutil.Process().memory_info().rss
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                if index % 20 == 0:
                    stream.flush()
                    print(json.dumps({"system": system, "processed": index + 1, "total": len(cases)}), flush=True)
    finally:
        pool.close()
    records = load_lines(output)
    summary = {
        "system": system,
        "cold_seconds": cold_seconds,
        "directions": {},
        "runtime": runtime(),
        "input_hashes": inputs(run),
        "model_identity": model_identity,
        "inference_device": "cpu",
        "supplemental_cases": supplemental_cases(),
    }
    for dialect in ("duckdb", "sqlite"):
        rows = [row for row in records if row["source"] == dialect and row["eligible"] and row["suite"] == "test"]
        timing = [row["translation_seconds"] for row in rows]
        summary["directions"][dialect] = dict(
            bounds(rows), median_seconds=float(np.median(timing)), p95_seconds=float(np.percentile(timing, 95))
        )
        metric = summary["directions"][dialect]
        supplemental = [r for r in records if r["source"] == dialect and r["suite"] == "supplemental"]
        metric["existing_workload"] = {"n": len(supplemental), "k": sum(r["success"] for r in supplemental)}
        metric["long_input_case_ids"] = [r["case_id"] for r in records if r["source"] == dialect and not r["eligible"]]
        metric["long_input_count"] = len(metric["long_input_case_ids"])
        metric["all_fixtures_empty_count"] = sum(r["all_fixtures_empty"] for r in rows)
        metric["failure_inventory"] = dict(
            Counter(
                r.get("error", r.get("validation", {}).get("error", "result_mismatch")).split(":", 1)[0]
                for r in rows
                if not r["success"]
            )
        )
        categories = {
            "feature/" + feature: [r for r in rows if feature in r["features"]]
            for feature in {f for r in rows for f in r["features"]}
        }
        categories.update(
            {
                "tokens/0-256": [r for r in rows if r["source_tokens"] <= 256],
                "tokens/257-512": [r for r in rows if 256 < r["source_tokens"] <= 512],
                "tokens/513-1024": [r for r in rows if 512 < r["source_tokens"] <= 1024],
                "held_out_workload": [r for r in rows if r["held_out_workload"]],
            }
        )
        metric["breakdowns"] = {
            name: {"n": len(group), "k": sum(r["success"] for r in group)} for name, group in categories.items()
        }
    summary["peak_sampled_rss"] = max(row["rss"] for row in records)
    summary["finite_fixture_limit"] = "Execution agreement on five witnesses is not universal SQL equivalence."
    write_json(run / f"evaluation-{system}.json", summary)


def report(run: Path) -> None:
    from curves import plot

    systems = ["sqlglot", "benchbox", "full", "edit"]
    summaries = {
        system: json.loads((run / f"evaluation-{system}.json").read_text(encoding="utf-8")) for system in systems
    }
    outcomes = {
        system: {
            r["case_id"]: r
            for r in load_lines(run / f"evaluation-{system}.jsonl")
            if r["eligible"] and r["suite"] == "test"
        }
        for system in systems
    }
    lines = [
        "# SQL translation feasibility result",
        "",
        "| System | Direction | Correct / total | Lower bound |",
        "| --- | --- | --- | --- |",
    ]
    for system, summary in summaries.items():
        for dialect, metric in summary["directions"].items():
            metric["failure_inventory"] = dict(
                Counter(
                    r.get("error", r.get("validation", {}).get("error", "result_mismatch")).split(":", 1)[0]
                    for r in outcomes[system].values()
                    if r["source"] == dialect and not r["success"]
                )
            )
            lines.append(f"| {system} | {dialect} | {metric['k']} / {metric['n']} | {metric['decision_lower']:.4%} |")
    for system in ("full", "edit"):
        passed = all(
            m["decision_lower"] >= 0.99 and m["sufficient_families"] and m["n"] >= 1000
            for m in summaries[system]["directions"].values()
        )
        lines.extend(["", f"{system}: {'supports' if passed else 'does not support'} the 99% hypothesis."])
    comparisons = {}
    for model in ("full", "edit"):
        for baseline in ("sqlglot", "benchbox"):
            if outcomes[model].keys() != outcomes[baseline].keys():
                raise ValueError("system denominators differ")
            for dialect in ("duckdb", "sqlite"):
                ids = [key for key, row in outcomes[model].items() if row["source"] == dialect]
                repaired = sum(
                    outcomes[model][key]["success"] and not outcomes[baseline][key]["success"] for key in ids
                )
                broken = sum(not outcomes[model][key]["success"] and outcomes[baseline][key]["success"] for key in ids)
                comparisons[f"{model}/{baseline}/{dialect}"] = {"repaired": repaired, "broken": broken}
                lines.extend(
                    ["", f"{model} versus {baseline}, source {dialect}: {repaired} repaired; {broken} broken."]
                )
    for system, summary in summaries.items():
        lines.extend(
            [
                "",
                f"{system}: cold loading {summary['cold_seconds']:.2f}s; "
                f"sampled peak RSS {summary['peak_sampled_rss']} bytes.",
            ]
        )
        if summary["model_identity"]:
            lines.append(f"Checkpoint size: {summary['model_identity']['bytes']} bytes.")
        for dialect, metric in summary["directions"].items():
            lines.append(
                f"Source {dialect}: {metric['long_input_count']} long inputs reported separately; "
                f"{metric['all_fixtures_empty_count']} cases empty on all fixtures; "
                f"median {metric['median_seconds']:.4f}s, p95 {metric['p95_seconds']:.4f}s."
            )
            lines.append(
                f"Existing-workload supplement: {metric['existing_workload']['k']} / "
                f"{metric['existing_workload']['n']} (separate from the locked synthetic population)."
            )
            lines.append("")
            lines.append(f"Failure counts: {json.dumps(metric.get('failure_inventory', {}), sort_keys=True)}")
            lines.append("")
            for category, value in metric["breakdowns"].items():
                lines.append(f"- {dialect} {category}: {value['k']} / {value['n']}")
    lines.extend(["", "Five finite fixtures provide evidence, not universal equivalence proof."])
    (run / "verdict.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    plot(run)
    hashes = {}
    for path in run.rglob("*"):
        if path.is_file() and path.name != "run-manifest.json":
            checksum = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(chunk)
            hashes[str(path.relative_to(run))] = checksum.hexdigest()
    write_json(run / "run-manifest.json", {"hashes": hashes, "summaries": summaries, "comparisons": comparisons})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--system", choices=["sqlglot", "benchbox", "full", "edit"])
    args = parser.parse_args()
    evaluate(args.run_dir, args.system) if args.system else report(args.run_dir)
