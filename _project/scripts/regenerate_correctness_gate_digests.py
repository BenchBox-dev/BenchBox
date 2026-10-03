#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

CORRECTNESS_GATE_QUERY_IDS_ENV = "BENCHBOX_CORRECTNESS_GATE_QUERY_IDS"
EMIT_RESULT_DIGEST_ENV = "BENCHBOX_EMIT_RESULT_DIGEST"
CLI_MODULE = "benchbox.cli.main"

REFERENCE_PATH = (
    _REPO_ROOT / "benchbox" / "core" / "expected_results" / "reference_digests" / "tpch_value_digests_sf1.json"
)

_PROVENANCE_NOTE = (
    "Reference VALUE digests for the bounded correctness-gate TPC-H queries at SF=1 with the "
    "pinned reference qgen seed. REGENERATE with `make correctness-gate-digests-regen` "
    "(_project/scripts/regenerate_correctness_gate_digests.py), which runs the same gate "
    "configuration with BENCHBOX_EMIT_RESULT_DIGEST=1 and writes this file -- do NOT hand-copy. "
    "This oracle is a REGRESSION SNAPSHOT vs a DuckDB-pinned baseline (it detects change from the "
    "frozen benchbox-on-DuckDB answer), NOT an independent correctness oracle: a conceptual value "
    "bug present at freeze time is enshrined, not caught. The digest is a value+TYPE-rendering "
    "digest (int renders exactly, float/Decimal at fixed significant figures), so it is DuckDB-pinned; cross-engine "
    "reuse is deferred (see _project/analysis/value-digest-cross-engine-independence-decision.md). "
    "Digests are tied to the DuckDB build pinned in uv.lock; a DuckDB bump that changes a query's "
    "emitted values requires regenerating this file."
)


def _query_ids() -> list[str]:
    raw = os.environ.get(CORRECTNESS_GATE_QUERY_IDS_ENV, "").strip()
    if not raw:
        raise SystemExit(
            f"{CORRECTNESS_GATE_QUERY_IDS_ENV} is not set. Run via `make correctness-gate-digests-regen`, "
            "which exports the same query-id set as `make test-correctness-gate`."
        )
    return [qid.strip() for qid in raw.split(",") if qid.strip()]


def _run_gate(work_dir: Path, query_ids: list[str], seed: int) -> dict:
    from benchbox.core.results.loader import find_latest_result

    command = [
        sys.executable,
        "-m",
        CLI_MODULE,
        "run",
        "--platform",
        "duckdb",
        "--benchmark",
        "tpch",
        "--scale",
        "1.0",
        "--phases",
        "generate,load,power",
        "--queries",
        ",".join(query_ids),
        "--seed",
        str(seed),
        "--non-interactive",
    ]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env[EMIT_RESULT_DIGEST_ENV] = "1"
    runs_root = work_dir / "benchmark_runs"
    env["BENCHBOX_OUTPUT_DIR"] = str(runs_root)

    print(f"Running gate: {' '.join(command[3:])}", file=sys.stderr)
    proc = subprocess.run(
        command,
        cwd=str(work_dir),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"gate run failed (exit {proc.returncode})")

    results_dir = runs_root / "results"
    result_path = find_latest_result(results_dir, benchmark="tpch")
    if result_path is None:
        raise SystemExit(f"no result JSON found under {results_dir}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _extract_stream0_digests(payload: dict, query_ids: list[str]) -> dict[str, str]:
    emitted: dict[str, str] = {}
    for query in payload.get("queries", []):
        if int(query.get("stream") or 0) != 0:
            continue
        if query.get("status") != "SUCCESS":
            continue
        digest = query.get("digest")
        if digest is None:
            continue
        emitted[str(query.get("id"))] = str(digest)

    digests: dict[str, str] = {}
    missing: list[str] = []
    for qid in query_ids:
        if qid in emitted:
            digests[qid] = emitted[qid]
        else:
            missing.append(qid)
    if missing:
        raise SystemExit(
            f"no stream-0 digest emitted for query id(s) {missing}; the gate run did not emit a "
            "digest for every configured query (digest emission off, a skipped/failed query, or drift)."
        )
    return digests


def build_reference(digests: dict[str, str], seed: int, duckdb_version: str) -> dict:
    return {
        "benchmark": "tpch",
        "scale_factor": 1.0,
        "reference_seed": seed,
        "digest": {
            "primitive": "benchbox.core.tpchavoc.validation.calculate_checksum",
            "algorithm": "md5-of-order-normalized-rows",
            "numeric_normalization": "float/Decimal cells rendered to fixed significant figures (relative precision) before hashing",
            "emitter": "benchbox.core.results.result_digest.compute_result_digest",
        },
        "provenance": {
            "generated_with_duckdb": duckdb_version,
            "generated_with_platform": "duckdb",
            "phases": "generate,load,power",
            "note": _PROVENANCE_NOTE,
        },
        "digests": digests,
    }


def render(reference: dict) -> str:
    return json.dumps(reference, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    import duckdb

    from benchbox.core.tpch.benchmark import get_reference_seed

    query_ids = _query_ids()
    seed = get_reference_seed(1.0)
    if seed is None:
        raise SystemExit("no reference seed for SF=1 (get_reference_seed(1.0) returned None)")

    with tempfile.TemporaryDirectory(prefix="benchbox-digest-regen-") as tmp:
        payload = _run_gate(Path(tmp), query_ids, seed)
        digests = _extract_stream0_digests(payload, query_ids)

    reference = build_reference(digests, seed, duckdb.__version__)
    REFERENCE_PATH.write_text(render(reference), encoding="utf-8")
    print(
        f"Wrote {REFERENCE_PATH.relative_to(_REPO_ROOT)} "
        f"({len(digests)} digests, DuckDB {duckdb.__version__}, seed {seed})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
