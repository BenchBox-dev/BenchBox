"""Collect and deterministically partition release-canary pytest node IDs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

MARKER_EXPRESSION = "(slow or resource_heavy) and not (stress or live_integration)"
DEFAULT_SHARD_COUNT = 6


def _canonical_node_ids(node_ids: Iterable[str]) -> list[str]:
    """Validate node IDs and return them in a stable order."""
    values = list(node_ids)
    if not values:
        raise ValueError("node-id input is empty")
    if any(not isinstance(node_id, str) or not node_id.strip() for node_id in values):
        raise ValueError("node-id input contains an empty or non-string value")
    if len(set(values)) != len(values):
        raise ValueError("node-id input contains duplicates")
    return sorted(values)


def parse_collection_output(output: str) -> list[str]:
    """Extract pytest node IDs from ``--collect-only -q`` output."""
    node_ids = []
    for line in output.splitlines():
        candidate = line.strip()
        if candidate.startswith("tests/") and "::" in candidate:
            node_ids.append(candidate)
    return _canonical_node_ids(node_ids)


def read_node_ids(path: Path) -> list[str]:
    """Read and validate a newline-delimited node-id file."""
    return _canonical_node_ids(path.read_text(encoding="utf-8").splitlines())


def partition_node_ids(node_ids: Sequence[str], shard_index: int, shard_count: int) -> list[str]:
    """Return one deterministic, disjoint shard of ``node_ids``.

    Sorting before round-robin assignment makes the result independent of
    pytest's collection order while spreading adjacent test modules across
    shards. Invalid parameters and duplicate input fail closed.
    """
    if isinstance(shard_count, bool) or not isinstance(shard_count, int) or shard_count < 1:
        raise ValueError("shard_count must be a positive integer")
    if isinstance(shard_index, bool) or not isinstance(shard_index, int) or not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be an integer in [0, shard_count)")
    ordered = _canonical_node_ids(node_ids)
    return ordered[shard_index::shard_count]


def _node_ids_sha256(node_ids: Sequence[str]) -> str:
    payload = "\n".join(node_ids) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_node_ids(path: Path, node_ids: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(node_ids) + "\n" if node_ids else ""
    path.write_text(payload, encoding="utf-8")


def collect_node_ids(
    input_path: Path,
    nodeids_output: Path,
    summary_output: Path,
    *,
    expected_count: int,
    shard_count: int,
    checked_ref: str = "",
    checked_sha: str = "",
    github_output: Path | None = None,
) -> int:
    """Create the canonical node-id artifact and collection manifest."""
    if expected_count < 1:
        raise ValueError("expected_count must be a positive integer")
    if isinstance(shard_count, bool) or not isinstance(shard_count, int) or shard_count < 1:
        raise ValueError("shard_count must be a positive integer")

    node_ids = parse_collection_output(input_path.read_text(encoding="utf-8"))
    if len(node_ids) != expected_count:
        raise ValueError(f"collected node-id count {len(node_ids)} does not match expected count {expected_count}")

    shard_counts = [len(partition_node_ids(node_ids, index, shard_count)) for index in range(shard_count)]
    if sum(shard_counts) != len(node_ids):
        raise ValueError("shard count conservation check failed")

    _write_node_ids(nodeids_output, node_ids)
    _write_json(
        summary_output,
        {
            "workflow": "release-canary.yml",
            "job": "collect-credential-free-non-fast",
            "checked_ref": checked_ref,
            "commit_sha": checked_sha,
            "marker_expression": MARKER_EXPRESSION,
            "total_count": len(node_ids),
            "shard_count": shard_count,
            "shard_counts": shard_counts,
            "node_ids_sha256": _node_ids_sha256(node_ids),
        },
    )
    if github_output is not None:
        with github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"collected_count={len(node_ids)}\n")
    return len(node_ids)


def write_shard(
    input_path: Path,
    nodeids_output: Path,
    summary_output: Path,
    *,
    shard_index: int,
    shard_count: int,
) -> int:
    """Write one shard file and its manifest from the collection artifact."""
    node_ids = read_node_ids(input_path)
    shard_node_ids = partition_node_ids(node_ids, shard_index, shard_count)
    _write_node_ids(nodeids_output, shard_node_ids)
    _write_json(
        summary_output,
        {
            "workflow": "release-canary.yml",
            "job": "credential-free-non-fast",
            "marker_expression": MARKER_EXPRESSION,
            "shard_index": shard_index,
            "shard_count": shard_count,
            "assigned_count": len(shard_node_ids),
            "total_count": len(node_ids),
            "source_node_ids_sha256": _node_ids_sha256(node_ids),
            "node_ids_sha256": _node_ids_sha256(shard_node_ids),
        },
    )
    return len(shard_node_ids)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="create the canonical node-id artifact")
    collect_parser.add_argument("--input", type=Path, required=True)
    collect_parser.add_argument("--nodeids-output", type=Path, required=True)
    collect_parser.add_argument("--summary-output", type=Path, required=True)
    collect_parser.add_argument("--expected-count", type=int, required=True)
    collect_parser.add_argument("--shard-count", type=int, default=DEFAULT_SHARD_COUNT)
    collect_parser.add_argument("--checked-ref", default="")
    collect_parser.add_argument("--checked-sha", default="")
    collect_parser.add_argument("--github-output", type=Path)

    shard_parser = subparsers.add_parser("shard", help="write one deterministic node-id shard")
    shard_parser.add_argument("--input", type=Path, required=True)
    shard_parser.add_argument("--nodeids-output", type=Path, required=True)
    shard_parser.add_argument("--summary-output", type=Path, required=True)
    shard_parser.add_argument("--shard-index", type=int, required=True)
    shard_parser.add_argument("--shard-count", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "collect":
            collect_node_ids(
                args.input,
                args.nodeids_output,
                args.summary_output,
                expected_count=args.expected_count,
                shard_count=args.shard_count,
                checked_ref=args.checked_ref,
                checked_sha=args.checked_sha,
                github_output=args.github_output,
            )
        else:
            write_shard(
                args.input,
                args.nodeids_output,
                args.summary_output,
                shard_index=args.shard_index,
                shard_count=args.shard_count,
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"release-canary sharding error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
