from __future__ import annotations

import os
from typing import Any


def build_fabric_spark_config_from_env() -> dict[str, Any]:
    mapping = {
        "workspace_id": "FABRIC_WORKSPACE_ID",
        "lakehouse_id": "FABRIC_LAKEHOUSE_ID",
        "tenant_id": "FABRIC_TENANT_ID",
        "livy_endpoint": "FABRIC_LIVY_ENDPOINT",
        "onelake_path": "FABRIC_ONELAKE_PATH",
        "spark_pool_name": "FABRIC_SPARK_POOL_NAME",
    }

    config: dict[str, Any] = {}
    for key, env_name in mapping.items():
        value = os.getenv(env_name)
        if value:
            config[key] = value

    timeout = os.getenv("FABRIC_TIMEOUT_MINUTES")
    if timeout:
        try:
            config["timeout_minutes"] = int(timeout)
        except ValueError:
            pass

    return config


__all__ = ["build_fabric_spark_config_from_env"]
