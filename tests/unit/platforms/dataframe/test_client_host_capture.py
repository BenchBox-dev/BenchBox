"""The DataFrame families must record the same client host the SQL adapters do.

Regression cover for `dataframe-client-host-capture-gap`: every DataFrame
result published an environment block containing only `platform_runtime`. No
`client_host` at all -- no os, arch, python, cpu_count, memory_gb or CPU
identity. 0 of 107 sampled raw DataFrame results carried it, and all 43
DataFrame bundles in the published corpus lacked it.

The cause was structural rather than a missing call. SQL adapters descend from
`benchbox/platforms/base/adapter.py`, whose `_build_execution_metadata` collects
a system profile; the DataFrame families descend from
`BenchmarkExecutionMixin` instead and never ran that path, so
`result.system_profile` stayed unset and `_build_environment_block` produced an
empty block that `_compact` then dropped.
"""

from __future__ import annotations

import pytest

from benchbox.core.results.environment import build_environment_payload
from benchbox.platforms.dataframe.benchmark_mixin import _client_host_profile
from benchbox.utils.system_info import get_system_info

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _client_host(system_profile: object) -> dict:
    payload = build_environment_payload(system_profile=system_profile, execution_environment=None)
    return payload.get("client_host", {})


def test_dataframe_profile_yields_a_populated_client_host() -> None:
    host = _client_host(_client_host_profile(None))
    assert host, "a DataFrame run must record a client host, not an empty block"
    for field in ("os", "arch", "python", "cpu_count", "memory_gb", "cpu_model"):
        assert field in host, f"DataFrame client_host is missing {field!r}"


def test_dataframe_and_sql_record_the_same_client_host_fields() -> None:
    # The SQL path builds its profile from get_system_info().to_dict()
    # (base/adapter.py -> result_capture._build_execution_metadata). Comparing
    # the KEY SETS is the point: the two hierarchies drifted silently once, and
    # only a test that spans both notices it happening again.
    sql_host = _client_host(get_system_info().to_dict())
    dataframe_host = _client_host(_client_host_profile(None))
    assert set(dataframe_host) == set(sql_host)


def test_a_caller_supplied_mapping_is_honoured_verbatim() -> None:
    supplied = {"os_type": "Linux", "architecture": "x86_64", "cpu_model": "Some CPU"}
    assert _client_host_profile(supplied) == supplied


def test_a_typed_profile_is_not_reshaped_into_the_wrong_keys() -> None:
    # A typed SystemProfile spells its fields os_name / cpu_cores_logical /
    # memory_total_gb, which are NOT the names from_system_profile reads.
    # Passing one through would reintroduce exactly the silent key mismatch
    # that dropped cpu_count, memory_gb and os_release from every bundle, so
    # the helper collects a fresh profile instead.
    class _Typed:
        os_name = "Linux"
        cpu_cores_logical = 8

    profile = _client_host_profile(_Typed())
    assert "cpu_count" in profile
    assert "memory_gb" in profile
