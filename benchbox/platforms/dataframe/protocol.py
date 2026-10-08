# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LazyFrameLike(Protocol):
    @property
    def columns(self) -> list[str] | tuple[str, ...]: ...
