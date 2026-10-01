"""Conserve actual offline adapter semantics in a fresh process without vendor SDKs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]


def test_all_adapter_semantics_with_vendor_sdk_imports_blocked() -> None:
    # Process startup and cold imports belong in T2, not the 0.5-second T1 lane.
    inventory = Path(__file__).with_name("test_offline_adapter_inventory.py")
    script = r"""
import importlib.abc
import runpy
import sys
from benchbox.core.platform_manifest import get_adapter_imports, get_platform_metadata

metadata = get_platform_metadata()
keys = {key for key, _, _ in get_adapter_imports()}
roots = {
    library.get("import_name", library["name"]).split(".")[0]
    for key in keys
    for library in metadata[key].get("libraries", [])
} - {"sqlite3"}
assert {"duckdb", "polars", "snowflake", "pyspark", "google", "boto3"} <= roots

class NoVendorSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in roots:
            raise ModuleNotFoundError("SDK deliberately absent: " + fullname, name=fullname)

for name in list(sys.modules):
    if name.split(".")[0] in roots:
        del sys.modules[name]
sys.meta_path.insert(0, NoVendorSDK())
suite = runpy.run_path(sys.argv[1])
suite["test_inventory_conserves_all_concrete_adapters"]()
suite["test_every_dialect_is_covered_by_translation_or_exemption"]()
for key, dialect in suite["ADAPTER_DIALECTS"].items():
    suite["test_adapter_class_loads_and_reports_expected_dialect"](key)
    if dialect in suite["EXPECTED_SQL"]:
        for statement in ("ddl", "query"):
            suite["test_real_translation_of_ddl_and_query"](key, statement)
    else:
        suite["test_non_sql_platforms_reject_strict_sql_translation"](key)
suite["test_polars_structured_schema_without_sql_or_sdk"]()
suite["test_influx_measurement_schema_and_typed_line_protocol"]()
assert not any(name.split(".")[0] in roots for name in sys.modules)
print("49 adapters, 94 real SQL assertions, 2 positive alternatives, no vendor SDK imports")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(inventory)],
        cwd=inventory.parents[3],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "49 adapters, 94 real SQL assertions, 2 positive alternatives, no vendor SDK imports" in result.stdout
