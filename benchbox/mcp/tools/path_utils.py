from __future__ import annotations

from pathlib import Path


def resolve_result_file_path(result_file: str, results_dir: Path) -> Path | None:
    if ".." in result_file or result_file.startswith("/") or result_file.startswith("\\"):
        return None

    candidates = [results_dir / result_file]
    if not result_file.endswith(".json"):
        candidates.append(results_dir / f"{result_file}.json")

    resolved_root = results_dir.resolve()

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            candidate.resolve().relative_to(resolved_root)
        except (ValueError, OSError):
            continue
        return candidate

    return None
