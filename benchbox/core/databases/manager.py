from __future__ import annotations

from benchbox.core.platform_config import get_platform_config
from benchbox.core.schemas import DatabaseConfig, SystemProfile
from benchbox.platforms import get_platform_adapter


def check_connection(database_config: DatabaseConfig, system_profile: SystemProfile | None = None) -> bool:
    platform_cfg = get_platform_config(database_config, system_profile)
    adapter = get_platform_adapter(database_config.type, **platform_cfg)
    return adapter.test_connection()
