"""Contract: semantically required producer keys cannot be silently dropped."""

from __future__ import annotations

import pytest

from benchbox.core.platform_config import REQUIRED_FROM_CONFIG_KEYS, get_platform_config
from benchbox.core.schemas import DatabaseConfig
from benchbox.platforms.base.config_utils import TUNING_FORWARD_KEYS, build_adapter_config

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_from_config_required_keys_are_forwarded_by_shared_helper() -> None:
    assert frozenset(TUNING_FORWARD_KEYS) >= REQUIRED_FROM_CONFIG_KEYS
    payload = {key: f"value-{key}" for key in REQUIRED_FROM_CONFIG_KEYS}
    payload["benchmark"] = "tpch"
    payload["scale_factor"] = 1.0
    built = build_adapter_config(payload, platform="sqlite", generated_key=None)
    for key in REQUIRED_FROM_CONFIG_KEYS:
        assert built[key] == payload[key]


def test_from_config_required_key_missing_from_helper_fails_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: a required key dropped from the forwarding set is silently lost.

    Simulates the exact break this contract guards against: if a required key
    were ever removed from ``TUNING_FORWARD_KEYS``, ``build_adapter_config``
    would stop forwarding it with no error, rather than raising.
    """
    key = next(iter(REQUIRED_FROM_CONFIG_KEYS))
    reduced_keys = tuple(k for k in TUNING_FORWARD_KEYS if k != key)
    monkeypatch.setattr("benchbox.platforms.base.config_utils.TUNING_FORWARD_KEYS", reduced_keys)

    payload = {k: f"value-{k}" for k in REQUIRED_FROM_CONFIG_KEYS}
    payload["benchmark"] = "tpch"
    payload["scale_factor"] = 1.0
    built = build_adapter_config(payload, platform="sqlite", generated_key=None)

    assert key not in built


def test_from_config_required_get_platform_config_emits_tuning_config() -> None:
    config = DatabaseConfig(type="sqlite", name="t")
    produced = get_platform_config(config, None, benchmark_name="tpch", scale_factor=1.0, tuning_config={"x": 1})
    assert produced["tuning_config"] == {"x": 1}
    assert produced["benchmark"] == "tpch"
    assert produced["scale_factor"] == 1.0
