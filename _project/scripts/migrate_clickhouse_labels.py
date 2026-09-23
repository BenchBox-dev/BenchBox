"""Retag result bundles carrying the pre-split bare `clickhouse` platform label.

Before the first-class split, ClickHouse results were recorded under the bare
``clickhouse`` platform name. That label cannot be mapped automatically: it
does not say which deployment produced the data (embedded chDB, self-hosted
server, or managed cloud). This script rewrites the label to the
operator-chosen first-class platform for every bundle that still carries it:

- ``platform.name`` ``clickhouse``/``ClickHouse`` -> the target display name
- a bare ``_clickhouse_`` filename slug -> ``_<target>_`` (underscored form)
- the ``.manifest.json`` sidecar ``bundle_file`` entry plus a recomputed
  ``bundle_hash`` over the rewritten result file

Dry-run by default; pass ``--apply`` to write. After applying, regenerate
``results-data/corpus-inventory.json`` (see ``results-data/REGENERATION.md``)
and re-run ``results-data/validate_corpus.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

TARGETS = {
    "clickhouse-local": "ClickHouse Local",
    "clickhouse-server": "ClickHouse Server",
    "clickhouse-cloud": "ClickHouse Cloud",
}

_BARE_LABEL = re.compile(r"^clickhouse$", re.IGNORECASE)
# Bare `_clickhouse_` filename slug, excluding the first-class
# `_clickhouse_local|server|cloud_` slugs (and the hyphenated spellings).
_BARE_SLUG = re.compile(r"_clickhouse_(?!(local|server|cloud)[_-])", re.IGNORECASE)


@dataclass(frozen=True)
class BundleHit:
    result: Path
    manifest: Path | None
    old_label: str


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def platform_label_of(payload: dict) -> str | None:
    platform = payload.get("platform")
    if isinstance(platform, dict):
        name = platform.get("name")
        return str(name) if name is not None else None
    if isinstance(platform, str):
        return platform
    return None


def discover_hits(bundle_dir: Path) -> tuple[list[BundleHit], list[str]]:
    hits: list[BundleHit] = []
    anomalies: list[str] = []
    for result in sorted(bundle_dir.rglob("*.json")):
        if result.name.endswith(".manifest.json"):
            continue
        try:
            payload = _load_json(result)
        except (OSError, ValueError) as exc:
            anomalies.append(f"unreadable bundle {result.name}: {exc}")
            continue
        label = platform_label_of(payload)
        old_slug = bool(_BARE_SLUG.search(result.name))
        if (label is not None and _BARE_LABEL.match(label)) or old_slug:
            manifest = result.with_name(f"{result.stem}.manifest.json")
            hits.append(
                BundleHit(
                    result=result,
                    manifest=manifest if manifest.exists() else None,
                    old_label=label or "(filename slug only)",
                )
            )
            if not manifest.exists():
                anomalies.append(f"missing manifest sidecar for {result.name}")
    return hits, anomalies


def migrate_hit(hit: BundleHit, target: str) -> tuple[Path, Path | None]:
    """Rewrite one bundle (and sidecar) to the target platform. Returns new paths.

    Raises:
        FileExistsError: If the rewritten result or sidecar path already
            exists. `--apply` never overwrites a published artifact; resolve
            the collision by hand and re-run.
    """
    display = TARGETS[target]
    slug = target.replace("-", "_")

    new_result = hit.result
    if _BARE_SLUG.search(hit.result.name):
        new_result = hit.result.with_name(_BARE_SLUG.sub(f"_{slug}_", hit.result.name, count=1))
    if new_result != hit.result and new_result.exists():
        raise FileExistsError(f"refusing to overwrite existing bundle {new_result}")
    new_manifest_guess = (
        hit.manifest.with_name(f"{new_result.stem}.manifest.json") if hit.manifest is not None else None
    )
    if new_manifest_guess is not None and new_manifest_guess != hit.manifest and new_manifest_guess.exists():
        raise FileExistsError(f"refusing to overwrite existing sidecar {new_manifest_guess}")

    payload = _load_json(hit.result)
    platform = payload.get("platform")
    if isinstance(platform, dict):
        if platform.get("name") is not None and _BARE_LABEL.match(str(platform["name"])):
            platform["name"] = display
    elif isinstance(platform, str) and _BARE_LABEL.match(platform):
        payload["platform"] = display

    _write_json(new_result, payload)
    if new_result != hit.result:
        hit.result.unlink()

    new_manifest: Path | None = None
    if hit.manifest is not None:
        sidecar = _load_json(hit.manifest)
        sidecar["bundle_file"] = new_result.name
        sidecar["bundle_hash"] = _sha256(new_result)
        new_manifest = hit.manifest
        if new_result != hit.result:
            new_manifest = hit.manifest.with_name(f"{new_result.stem}.manifest.json")
            hit.manifest.unlink()
        _write_json(new_manifest, sidecar)
    return new_result, new_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, default=Path("results-data/bundles"))
    parser.add_argument(
        "--target", choices=sorted(TARGETS), help="First-class platform to retag to (required with --apply)"
    )
    parser.add_argument("--apply", action="store_true", help="Write rewrites (default is dry-run)")
    args = parser.parse_args(argv)

    if args.apply and not args.target:
        parser.error("--target is required with --apply")

    hits, anomalies = discover_hits(args.bundle_dir)
    for hit in hits:
        print(f"{hit.result.name}: platform label {hit.old_label!r}")
    for anomaly in anomalies:
        print(f"anomaly: {anomaly}")
    print(f"{len(hits)} bundle(s) carry the legacy bare `clickhouse` label")

    if not args.apply:
        print("dry-run: pass --target <platform> --apply to rewrite")
        return 0

    assert args.target is not None
    blocked = 0
    for hit in hits:
        try:
            new_result, _ = migrate_hit(hit, args.target)
        except FileExistsError as exc:
            blocked += 1
            print(f"blocked: {exc}")
            continue
        print(f"rewrote {hit.result.name} -> {new_result.name} ({TARGETS[args.target]})")
    if blocked:
        print(f"{blocked} hit(s) blocked by existing files; resolve by hand and re-run")
        return 1
    print("done: regenerate corpus-inventory.json and re-run validate_corpus.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
