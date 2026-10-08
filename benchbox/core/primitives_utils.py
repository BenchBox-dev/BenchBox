from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

EntryT = TypeVar("EntryT")


def get_entry_by_id(entries: Mapping[str, EntryT], entry_id: str, entry_type_name: str) -> EntryT:
    try:
        return entries[entry_id]
    except KeyError as exc:
        available = ", ".join(sorted(entries.keys()))
        raise ValueError(f"Invalid {entry_type_name} ID: {entry_id}. Available: {available}") from exc
