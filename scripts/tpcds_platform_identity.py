#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark(TM) DS (TPC-DS) - Copyright (c) Transaction Processing Performance Council

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

CLI_DESCRIPTION = "Check that the bundled TPC-DS generators agree across platforms."

DEFAULT_SCALE_FACTOR = 0.01
DEFAULT_SEED = 7
DEFAULT_PARAMETER_SCALE_FACTORS = (100.0,)
QUERY_IDS = tuple(range(1, 100))
_CHUNK = 1 << 20
VOLATILE_TABLES = frozenset({"dbgen_version"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table_entry(path: Path) -> dict[str, Any]:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return {"rows": data.count(b"\n"), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


_BUNDLE_ROOT = Path(__file__).resolve().parents[1] / "benchbox" / "_binaries"


def _bundle_platform() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        arch = machine
    return f"{platform.system().lower()}-{arch}"


def pinned_bundle_hashes() -> dict[str, str]:
    from benchbox.utils.binary_manifest import read_binary_manifest

    files = read_binary_manifest((_BUNDLE_ROOT / "SHA256MANIFEST.json").read_bytes())
    directory = f"tpc-ds/{_bundle_platform()}"
    suffix = ".exe" if platform.system() == "Windows" else ""
    return {name: files[f"{directory}/{name}{suffix}"] for name in ("dsqgen", "dsdgen")}


def generate_tables(scale_factor: float, output_dir: Path) -> dict[str, dict[str, Any]]:
    from benchbox.core.tpcds.benchmark import TPCDSBenchmark

    TPCDSBenchmark(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    return {path.stem: table_entry(path) for path in sorted(output_dir.glob("*.dat"))}


def query_entries(dsqgen: Any, scale_factor: float, seed: int, query_ids: Iterable[int]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for query_id in query_ids:
        logged = dsqgen.generate_parameter_log(query_id, seed=seed, scale_factor=scale_factor)
        sql = dsqgen.generate(query_id, seed=seed, scale_factor=scale_factor)
        entries[str(query_id)] = {
            "values": dict(logged.substitutions),
            "sql_sha256": hashlib.sha256(sql.replace("\r\n", "\n").encode("utf-8")).hexdigest(),
        }
    return entries


def build_manifest(
    scale_factor: float = DEFAULT_SCALE_FACTOR,
    seed: int = DEFAULT_SEED,
    query_ids: Sequence[int] = QUERY_IDS,
    with_tables: bool = True,
    parameter_scale_factors: Sequence[float] = DEFAULT_PARAMETER_SCALE_FACTORS,
) -> dict[str, Any]:
    from benchbox.core.tpcds.c_tools import DSQGenBinary

    dsqgen = DSQGenBinary()
    manifest: dict[str, Any] = {
        "scale_factor": scale_factor,
        "seed": seed,
        "platform": {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()},
        "binaries": {
            "dsqgen": sha256_file(Path(dsqgen.dsqgen_path)),
            "dsdgen": sha256_file(
                Path(dsqgen.dsqgen_path).with_name(Path(dsqgen.dsqgen_path).name.replace("dsqgen", "dsdgen"))
            ),
        },
        "tables": {},
        "queries": query_entries(dsqgen, scale_factor, seed, query_ids),
        "parameter_scales": {
            str(factor): query_entries(dsqgen, factor, seed, query_ids) for factor in parameter_scale_factors
        },
    }
    if with_tables:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest["tables"] = generate_tables(scale_factor, Path(temp_dir))
    return manifest


def _diff_table(name: str, reference: dict[str, Any], other: dict[str, Any]) -> list[str]:
    problems = []
    if reference["rows"] != other["rows"]:
        problems.append(f"table {name}: {reference['rows']} rows against {other['rows']}")
    if name not in VOLATILE_TABLES and reference["sha256"] != other["sha256"]:
        problems.append(f"table {name}: sha256 {reference['sha256'][:12]} against {other['sha256'][:12]}")
    return problems


def compare_manifests(manifests: dict[str, dict[str, Any]]) -> list[str]:
    names = sorted(manifests)
    if len(names) < 2:
        return ["need at least two manifests to compare"]
    reference_name, reference = names[0], manifests[names[0]]
    problems: list[str] = []
    for name in names[1:]:
        other = manifests[name]
        label = f"{reference_name} vs {name}"
        incomparable = [key for key in ("scale_factor", "seed") if reference[key] != other[key]]
        for key in incomparable:
            problems.append(
                f"{label}: {key} differs ({reference[key]} against {other[key]}); manifests are not comparable"
            )
        if incomparable:
            continue
        tables_a, tables_b = reference["tables"], other["tables"]
        for table in sorted(set(tables_a) | set(tables_b)):
            if table not in tables_a or table not in tables_b:
                problems.append(f"{label}: table {table} only in {reference_name if table in tables_a else name}")
            else:
                problems.extend(f"{label}: {item}" for item in _diff_table(table, tables_a[table], tables_b[table]))
        problems.extend(_diff_queries(label, reference_name, name, reference["queries"], other["queries"]))
        scales_a, scales_b = reference.get("parameter_scales", {}), other.get("parameter_scales", {})
        if set(scales_a) != set(scales_b):
            problems.append(
                f"{label}: parameter-only scales differ ({sorted(scales_a)} against {sorted(scales_b)}); "
                "those parameters are not comparable"
            )
            continue
        for factor in sorted(scales_a, key=float):
            problems.extend(
                _diff_queries(f"{label} at SF {factor}", reference_name, name, scales_a[factor], scales_b[factor])
            )
    return problems


def _diff_queries(
    label: str, reference_name: str, name: str, queries_a: dict[str, Any], queries_b: dict[str, Any]
) -> list[str]:
    problems: list[str] = []
    for query in sorted(set(queries_a) | set(queries_b), key=int):
        if query not in queries_a or query not in queries_b:
            problems.append(f"{label}: query {query} only in {reference_name if query in queries_a else name}")
            continue
        values_a, values_b = queries_a[query]["values"], queries_b[query]["values"]
        changed = sorted(key for key in set(values_a) | set(values_b) if values_a.get(key) != values_b.get(key))
        if changed:
            shown = ", ".join(f"{key}: {values_a.get(key)!r} against {values_b.get(key)!r}" for key in changed[:3])
            problems.append(f"{label}: query {query} parameters differ ({len(changed)}): {shown}")
        elif queries_a[query]["sql_sha256"] != queries_b[query]["sql_sha256"]:
            problems.append(f"{label}: query {query} renders different SQL for identical parameters")
    return problems


def _load(paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for path in paths:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        info = manifest.get("platform", {})
        name = f"{info.get('system', 'unknown')}-{info.get('machine', 'unknown')}".lower()
        manifests[name if name not in manifests else f"{name}:{path.stem}"] = manifest
    return manifests


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("manifest", help="generate data and parameters and write a manifest")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--scale-factor", type=float, default=DEFAULT_SCALE_FACTOR)
    build.add_argument("--seed", type=int, default=DEFAULT_SEED)
    build.add_argument(
        "--parameter-scale-factor",
        type=float,
        action="append",
        help="parameter-only scale to record (repeatable; default: SF 100)",
    )
    compare = commands.add_parser("compare", help="compare manifests from different platforms")
    compare.add_argument("manifests", type=Path, nargs="+")
    args = parser.parse_args(argv)

    if args.command == "manifest":
        manifest = build_manifest(
            args.scale_factor,
            args.seed,
            parameter_scale_factors=args.parameter_scale_factor or DEFAULT_PARAMETER_SCALE_FACTORS,
        )
        args.out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}: {len(manifest['tables'])} tables, {len(manifest['queries'])} queries")
        try:
            pinned = pinned_bundle_hashes()
        except (OSError, ValueError, KeyError) as exc:
            print(f"could not verify the bundled binaries: {exc}")
            return 1
        mismatched = sorted(name for name, digest in pinned.items() if manifest["binaries"].get(name) != digest)
        if mismatched:
            print(f"manifest was not produced by the bundled binaries: {', '.join(mismatched)}")
            return 1
        return 0

    manifests = _load(args.manifests)
    problems = compare_manifests(manifests)
    for problem in problems:
        print(problem)
    first = manifests[sorted(manifests)[0]]
    print(
        f"compared {', '.join(sorted(manifests))}: {len(first['tables'])} tables, {len(first['queries'])} queries, "
        f"{len(problems)} difference(s)"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
