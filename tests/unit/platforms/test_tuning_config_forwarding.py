"""Registry-driven test: every from_config implementation must forward the
tuning provenance/config keys onto the constructed adapter instance.

Background (see tuning-from-config-forwarding-sweep-20260716): PR #1176's w0
discovery was that on the direct CLI path, tuning config never reached
adapters -- ``DatabaseConfig.model_dump()`` flattens dataclasses and most
adapters' ``from_config`` dropped the tuning keys entirely. #1176 fixed the
channel (a live-object ``tuning_config`` kwarg with a dict-type guard in
``PlatformAdapter.__init__``) and duckdb's forwarding; a follow-up review
fixed questdb. This test sweeps every *registered* adapter and asserts the
exact key set duckdb/questdb established --
``tuning_config``/``tuning_enabled``/``unified_tuning_configuration``/
``tuning_source``/``tuning_source_file`` -- survives ``from_config()`` and
lands on the instance. It is intentionally parametrized over the live
platform registry (not a fixed platform list) so a future platform that adds
``from_config`` without forwarding fails this test automatically.

No live connections are made. The concrete adapter constructor is isolated
only for the duration of each case so the real ``from_config()`` implementation
can be exercised even when its optional runtime driver is not installed.
"""

from __future__ import annotations

from typing import Any

import pytest

from benchbox.core.platform_registry import PlatformRegistry
from benchbox.platforms.base import PlatformAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _TuningConfigSentinel:
    """Stand-in for a live ``UnifiedTuningConfiguration`` object.

    ``PlatformAdapter.__init__`` special-cases a *dict*-valued
    ``unified_tuning_configuration`` (treating it as a stale, round-tripped
    dict rather than a live object -- see the class docstring there), so the
    sentinel must not be a dict for the assertions below to exercise the real
    "live object" precedence path.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<TuningConfigSentinel>"


TUNING_CONFIG_SENTINEL = _TuningConfigSentinel()
TUNING_ENABLED_SENTINEL = True
TUNING_SOURCE_SENTINEL = "auto_discovered"
TUNING_SOURCE_FILE_SENTINEL = "tuning/templates/duckdb_tuned.yaml"


def _registered_platform_names() -> list[str]:
    return sorted(PlatformRegistry.get_available_platforms())


def _build_stub_config(tmp_dir: str) -> dict[str, Any]:
    """A generic config dict wide enough to satisfy every from_config's
    required fields, so construction reaches the point where tuning kwargs
    would (or should) be forwarded.

    Every value here is a dummy placeholder -- from_config()/__init__() never
    open a connection, so none of these need to resolve to anything real.
    ``output_dir`` is the one exception: several from_config implementations
    (duckdb, datafusion, sqlite, polars, ducklake, ...) create a directory
    for generated database paths, so it must point at a real (temp) location
    rather than polluting the repo's benchmark_runs/.
    """
    return {
        "benchmark": "tpch",
        "scale_factor": 1,
        "output_dir": tmp_dir,
        # Generic connection fields read via config.get() by most SQL adapters
        "host": "localhost",
        "port": 9999,
        "username": "benchbox",
        "user": "benchbox",
        "password": "benchbox",
        "database": "benchbox_test",
        "schema": "benchbox_test",
        # "duckdb" is a valid catalog *value* for both DuckLake's catalog
        # backend (duckdb/sqlite/postgres) and Trino/Presto/Starburst's
        # unvalidated-at-construction catalog name.
        "catalog": "duckdb",
        "account": "dummy_account",
        "warehouse": "COMPUTE_WH",
        "role": "SYSADMIN",
        # Cloud staging / required fields for cloud-native adapters
        "project_id": "dummy-project",
        "gcs_staging_dir": "gs://dummy-bucket/staging",
        "s3_staging_dir": "s3://dummy-bucket/staging",
        "s3_bucket": "dummy-bucket",
        "workgroup": "dummy-workgroup",
        "execution_role_arn": "arn:aws:iam::123456789012:role/dummy",
        "application_id": "dummy-app-id",
        "job_role": "arn:aws:iam::123456789012:role/dummy",
        "iam_role": "arn:aws:iam::123456789012:role/dummy",
        "s3_output_location": "s3://dummy-bucket/output",
        # Databricks
        "server_hostname": "dummy.cloud.databricks.com",
        "http_path": "/sql/1.0/warehouses/dummy",
        "access_token": "dummy-token",
        # Firebolt / Snowpark / Onehouse cloud (omit "url" so Firebolt
        # resolves the cloud path unambiguously via client_id/client_secret
        # instead of raising on "both Core URL and Cloud credentials
        # provided")
        "client_id": "dummy-client-id",
        "client_secret": "dummy-client-secret",
        "account_name": "dummy-account",
        "engine_name": "dummy-engine",
        "api_key": "dummy-api-key",
        "api_endpoint": "https://dummy.onehouse.ai",
        "motherduck_token": "dummy-motherduck-token",
        # Azure
        "workspace_id": "dummy-workspace-id",
        "lakehouse_id": "dummy-lakehouse-id",
        "tenant_id": "dummy-tenant-id",
        "livy_endpoint": "https://dummy.livy.endpoint",
        "workspace_name": "dummy-workspace",
        "spark_pool_name": "dummy-pool",
        "storage_account": "dummystorageaccount",
        "storage_container": "dummy-container",
        "storage_path": "dummy/path",
        "server": "dummy-server.database.windows.net",
        "workspace": "dummy-workspace",
        "onelake_workspace": "dummy-onelake-ws",
        # Spark-family
        "master": "local[2]",
        "app_name": "benchbox-test",
        "endpoint": "http://localhost:50051",
        # Tuning sentinels -- the actual thing under test. Both the live-object
        # key (tuning_config) and the legacy/fallback key
        # (unified_tuning_configuration) are set so the test also proves
        # from_config forwards the literal "unified_tuning_configuration" key
        # (precedence rules mean tuning_config wins when both are present --
        # see PlatformAdapter.__init__ -- but the raw kwarg must still survive
        # onto platform_config).
        "tuning_config": TUNING_CONFIG_SENTINEL,
        "tuning_enabled": TUNING_ENABLED_SENTINEL,
        "unified_tuning_configuration": object(),
        "tuning_source": TUNING_SOURCE_SENTINEL,
        "tuning_source_file": TUNING_SOURCE_FILE_SENTINEL,
    }


@pytest.mark.parametrize("platform_name", _registered_platform_names())
def test_from_config_forwards_tuning_kwargs(platform_name: str, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every registered adapter's from_config() must preserve the tuning keys.

    Constructs the adapter through the real ``from_config()`` classmethod
    (the same path ``get_platform_adapter()`` uses) with a stub config
    carrying sentinel tuning values, then asserts those sentinels land on the
    constructed instance's base-class attributes
    (``tuning_enabled``/``unified_tuning_configuration``/``tuning_source``/
    ``tuning_source_file``, set by ``PlatformAdapter.__init__``).
    """
    adapter_class = PlatformRegistry.get_adapter_class(platform_name)
    if adapter_class is None:
        pytest.skip(f"{platform_name}: adapter class unavailable in this environment")

    stub_config = _build_stub_config(str(tmp_path))

    # The forwarding contract is independent of optional driver availability.
    # Patch only this adapter class's constructor, for this one call, so the
    # real from_config() implementation still builds the constructor kwargs
    # under test without opening a driver-specific dependency gate.
    original_init = adapter_class.__init__
    with monkeypatch.context() as constructor_patch:
        constructor_patch.setattr(adapter_class, "__init__", PlatformAdapter.__init__)
        instance = adapter_class.from_config(dict(stub_config))

    # Make the isolation contract explicit: this test must not leave a
    # constructor patch behind for later parametrized cases or tests.
    assert adapter_class.__init__ is original_init

    assert instance.tuning_enabled is TUNING_ENABLED_SENTINEL, (
        f"{platform_name}: from_config() did not forward tuning_enabled onto the adapter"
    )
    assert instance.unified_tuning_configuration is TUNING_CONFIG_SENTINEL, (
        f"{platform_name}: from_config() did not forward tuning_config (live tuning object) onto the adapter"
    )
    assert instance.tuning_source == TUNING_SOURCE_SENTINEL, (
        f"{platform_name}: from_config() did not forward tuning_source onto the adapter"
    )
    assert instance.tuning_source_file == TUNING_SOURCE_FILE_SENTINEL, (
        f"{platform_name}: from_config() did not forward tuning_source_file onto the adapter"
    )
    # The raw "unified_tuning_configuration" kwarg must also survive
    # from_config() verbatim (even though tuning_config wins precedence in
    # PlatformAdapter.__init__) -- this is what actually proves from_config()
    # forwards the literal key, not just tuning_config.
    assert (
        instance.platform_config.get("unified_tuning_configuration") is stub_config["unified_tuning_configuration"]
    ), f"{platform_name}: from_config() did not forward the literal unified_tuning_configuration key"
