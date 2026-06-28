#!/usr/bin/env python3
"""Regenerate the bounded correctness-gate TPC-H value-digest reference.

This WRITES
``benchbox/core/expected_results/reference_digests/tpch_value_digests_sf1.json``
from a live gate run, replacing the historical hand-copy (the old provenance note
asked a human to run the gate and paste the stream-0 digests). It is the auditable,
one-command regeneration path required by
``correctness-gate-value-digest-fidelity-followups`` w3.

It deliberately REUSES the same configuration as ``make test-correctness-gate``
rather than re-hardcoding it:

  * query-id set: read from ``BENCHBOX_CORRECTNESS_GATE_QUERY_IDS`` -- the SAME env
    var the gate target exports (the Makefile defines it once in
    ``CORRECTNESS_GATE_QUERY_IDS`` and passes it to both targets);
  * scale: SF=1 (the only scale with stored TPC-H answers / a pinned seed);
  * seed: ``benchbox.core.tpch.benchmark.get_reference_seed(1.0)`` (the reference
    qgen seed the answer files were generated with);
  * digest emission: ``BENCHBOX_EMIT_RESULT_DIGEST=1`` (gate-only flag).

The output is deterministic on a clean tree: a regenerate -> no-diff round trip is
the idempotency check (``make correctness-gate-digests-regen && git diff --exit-code``).
The digests are tied to the DuckDB build pinned in ``uv.lock``; the DuckDB version
that produced them is stamped into the provenance block.

NOTE: the value oracle this feeds is a REGRESSION SNAPSHOT vs a DuckDB-pinned
baseline (it detects change from the frozen benchbox-on-DuckDB answer), NOT an
independent correctness oracle -- a conceptual value bug present at freeze time is
enshrined, not caught. See
``_project/analysis/value-digest-cross-engine-independence-decision.md``.

Usage (always via the make target, which exports the shared query-id env var):

    make correctness-gate-digests-regen

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The gate exports this; it is the ONE source of the gate query-id set (defined once
# in the Makefile and shared between test-correctness-gate and the regen target).
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
    """The gate query-id list, in gate order, from the shared env var."""
    raw = os.environ.get(CORRECTNESS_GATE_QUERY_IDS_ENV, "").strip()
    if not raw:
        raise SystemExit(
            f"{CORRECTNESS_GATE_QUERY_IDS_ENV} is not set. Run via `make correctness-gate-digests-regen`, "
            "which exports the same query-id set as `make test-correctness-gate`."
        )
    return [qid.strip() for qid in raw.split(",") if qid.strip()]


def _run_gate(work_dir: Path, query_ids: list[str], seed: int) -> dict:
    """Run the DuckDB TPC-H SF=1 gate slice with digest emission and return the payload."""
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
    # Pin the child's output root to the temp work dir. Otherwise a caller that has
    # BENCHBOX_OUTPUT_DIR set (a supported configuration -- it relocates the
    # benchmark_runs root, see benchbox.utils.path_utils.resolve_benchmark_runs_dir)
    # would make `benchbox run` write its result under that configured root while we
    # search work_dir, and the run would complete but then fail with "no result JSON".
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
    """Map each gate query id -> its emitted stream-0 value digest, in gate order."""
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
    """Assemble the reference JSON payload in the committed key order (deterministic)."""
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
    """Serialize deterministically (2-space indent, insertion order, trailing newline)."""
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
