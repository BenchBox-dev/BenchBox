"""Retag legacy synthetic JoinOrder result bundles.

Renames develop-tree bundle pairs:

    joinorder_sf1_* -> joinorder_synthetic_sf1_*

and updates the result bundle benchmark id plus submission sidecar metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BundlePair:
    result: Path
    manifest: Path

    @property
    def new_result(self) -> Path:
        return self.result.with_name(self.result.name.replace("joinorder_sf1_", "joinorder_synthetic_sf1_", 1))

    @property
    def new_manifest(self) -> Path:
        return self.manifest.with_name(self.manifest.name.replace("joinorder_sf1_", "joinorder_synthetic_sf1_", 1))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def discover_pairs(bundle_dir: Path) -> list[BundlePair]:
    pairs: list[BundlePair] = []
    anomalies: list[str] = []
    for result in sorted(bundle_dir.glob("joinorder_sf1_*.json")):
        if result.name.endswith(".manifest.json"):
            continue
        manifest = result.with_name(f"{result.stem}.manifest.json")
        if not manifest.exists():
            anomalies.append(f"missing manifest for {result}")
            continue
        pairs.append(BundlePair(result=result, manifest=manifest))
    for manifest in sorted(bundle_dir.glob("joinorder_sf1_*.manifest.json")):
        result = manifest.with_name(manifest.name.removesuffix(".manifest.json") + ".json")
        if not result.exists():
            anomalies.append(f"orphan manifest {manifest}")
    if anomalies:
        raise SystemExit("Bundle migration anomalies:\n" + "\n".join(f"- {item}" for item in anomalies))
    return pairs


def render_plan(pairs: list[BundlePair]) -> str:
    lines = [
        "# JoinOrder Bundle Migration Plan",
        "",
        f"Pairs: {len(pairs)}",
        f"Files: {len(pairs) * 2}",
        "",
    ]
    for pair in pairs:
        lines.extend(
            [
                f"## {pair.result.name}",
                "",
                f"- Result: `{pair.result}` -> `{pair.new_result}`",
                f"- Manifest: `{pair.manifest}` -> `{pair.new_manifest}`",
                "- Result JSON: benchmark.id `joinorder` -> `joinorder_synthetic`; "
                "benchmark.name -> `JoinOrderSyntheticBenchmark`",
                "- Manifest JSON: bundle_file updated; benchmark -> `JoinOrderSyntheticBenchmark`; "
                "bundle_hash recomputed after result JSON update",
                "",
            ]
        )
    return "\n".join(lines)


def _git_mv(src: Path, dst: Path) -> None:
    subprocess.run(["git", "mv", str(src), str(dst)], check=True)


def apply_migration(pairs: list[BundlePair]) -> None:
    expected_old = [path for pair in pairs for path in (pair.result, pair.manifest)]
    expected_new = [path for pair in pairs for path in (pair.new_result, pair.new_manifest)]
    for path in expected_new:
        if path.exists():
            raise SystemExit(f"target already exists: {path}")

    for pair in pairs:
        _git_mv(pair.result, pair.new_result)
        _git_mv(pair.manifest, pair.new_manifest)

        result_data = _load_json(pair.new_result)
        benchmark = result_data.setdefault("benchmark", {})
        if isinstance(benchmark, dict):
            benchmark["id"] = "joinorder_synthetic"
            benchmark["name"] = "JoinOrderSyntheticBenchmark"
        result_data["synthetic_retag"] = {
            "previous_benchmark_id": "joinorder",
            "reason": "pre-cutover JoinOrder bundles used the synthetic generator",
        }
        _write_json(pair.new_result, result_data)

        manifest_data = _load_json(pair.new_manifest)
        manifest_data["bundle_file"] = pair.new_result.name
        manifest_data["bundle_hash"] = _sha256(pair.new_result)
        manifest_data["benchmark"] = "JoinOrderSyntheticBenchmark"
        _write_json(pair.new_manifest, manifest_data)

    remaining_old = [path for path in expected_old if path.exists()]
    missing_new = [path for path in expected_new if not path.exists()]
    if remaining_old or missing_new:
        details = [f"old still present: {p}" for p in remaining_old]
        details.extend(f"new missing: {p}" for p in missing_new)
        raise SystemExit("incomplete migration:\n" + "\n".join(details))


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--bundle-dir", default="results-data/bundles")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    pairs = discover_pairs(Path(args.bundle_dir))
    if args.dry_run:
        plan = render_plan(pairs)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(plan + "\n", encoding="utf-8")
        else:
            print(plan)
        return 0

    if len(pairs) != 5:
        raise SystemExit(f"expected 5 bundle pairs, found {len(pairs)}")
    apply_migration(pairs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
