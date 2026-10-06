"""Conformance: adapter tuning arity.

Signature-drift gate over every registered adapter:
``apply_unified_tuning`` must accept the two arguments the base setup phase
passes (``PlatformAdapter`` calls ``apply_unified_tuning(config, connection)``).
A one-argument override raises ``TypeError`` on tuned runs.

No live connections are opened: the check inspects signatures statically.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import inspect

import pytest

from benchbox.core.platform_registry import PlatformRegistry

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _adapter_names() -> list[str]:
    return sorted(PlatformRegistry.get_available_platforms())


@pytest.mark.parametrize("name", _adapter_names())
def test_apply_unified_tuning_accepts_config_and_connection(name: str) -> None:
    """Every adapter's apply_unified_tuning binds the two setup-phase arguments."""
    adapter_class = PlatformRegistry.get_adapter_class(name)
    signature = inspect.signature(adapter_class.apply_unified_tuning)
    try:
        signature.bind(object(), object(), object())
    except TypeError as exc:
        pytest.fail(f"{name}.{adapter_class.__name__}.apply_unified_tuning does not accept (config, connection): {exc}")
