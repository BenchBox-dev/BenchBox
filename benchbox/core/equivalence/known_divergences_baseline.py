from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml


class BaselineUpdateError(RuntimeError):
    pass


def load_baseline(path: Path) -> dict[str, dict[str, str]]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BaselineUpdateError(f"{path} is not valid YAML: {exc}") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise BaselineUpdateError(f"{path} must contain a top-level mapping, got {type(payload).__name__}")
    return payload


def prune_known_divergences(
    data: dict[str, dict[str, str]], resolved_keys: Iterable[str], gate_name: str
) -> dict[str, dict[str, str]]:
    resolved = set(resolved_keys)
    section = data.get(gate_name)
    if not resolved or not section:
        return data
    updated_section = {key: reason for key, reason in section.items() if key not in resolved}
    if updated_section == section:
        return data
    updated = dict(data)
    updated[gate_name] = updated_section
    return updated


def _dump(data: dict[str, dict[str, str]]) -> str:
    body = yaml.safe_dump(data, sort_keys=True, default_flow_style=False, allow_unicode=True, width=88)
    return body


def update_baseline_file(path: Path, resolved_keys: Iterable[str], gate_name: str) -> list[str]:
    data = load_baseline(path)
    before = set(data.get(gate_name, {}))
    updated = prune_known_divergences(data, resolved_keys, gate_name)
    after = set(updated.get(gate_name, {}))
    removed = sorted(before - after)
    if not removed:
        return []
    path.write_text(_dump(updated), encoding="utf-8")
    return removed
