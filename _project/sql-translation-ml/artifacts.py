"""Bind checkpoints and outcomes to the local inputs that produced them."""

import hashlib
import importlib.metadata
import platform
from pathlib import Path


def sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def inputs(run: Path) -> dict[str, str]:
    return {
        name: sha256(run / name)
        for name in (
            "contract.json",
            "source.jsonl",
            "split.json",
            "labels.jsonl",
            "preparation.jsonl",
        )
    }


def runtime() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "machine": platform.machine(),
        **{name: importlib.metadata.version(name) for name in ("torch", "transformers", "duckdb", "sqlglot")},
    }


def checkpoint(path: Path) -> dict:
    files = sorted(p for p in path.rglob("*") if p.is_file())
    if not files:
        raise ValueError("checkpoint has no files")
    return {
        "hashes": {str(p.relative_to(path)): sha256(p) for p in files},
        "bytes": sum(p.stat().st_size for p in files),
    }
