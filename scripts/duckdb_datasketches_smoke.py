#!/usr/bin/env python3
"""CI smoke for the DuckDB community `datasketches` extension.

Installs the extension fresh and probes one representative function per
family BenchBox plans on. Exits non-zero if any planned family raises a
Catalog Error -- the failure mode the 2026-05-02 audit caught after the
extension silently dropped `theta` and `frequent_items` between two
builds on the same day.

Network failures fetching the extension are reported but non-fatal,
per the TODO's must_preserve.
"""

from __future__ import annotations

import sys

import duckdb

REQUIRED_FAMILIES: dict[str, str] = {
    "theta": "SELECT datasketch_theta(v) FROM (VALUES (1::INTEGER)) t(v)",
    "frequent_items": "SELECT datasketch_frequent_items(8, v) FROM (VALUES ('x')) t(v)",
    "cpc": "SELECT datasketch_cpc(11, v) FROM (VALUES (1::INTEGER)) t(v)",
    "req": "SELECT datasketch_req(12, v) FROM (VALUES (1.0::FLOAT)) t(v)",
    "kll": "SELECT datasketch_kll(200, v) FROM (VALUES (1.0::DOUBLE)) t(v)",
    "hll": "SELECT datasketch_hll(11, v) FROM (VALUES (1::INTEGER)) t(v)",
}

NETWORK_ERROR_HINTS = (
    "Failed to download extension",
    "Could not connect",
    "HTTP",
    "Network",
)


def _is_network_error(message: str) -> bool:
    return any(hint.lower() in message.lower() for hint in NETWORK_ERROR_HINTS)


def main() -> int:
    con = duckdb.connect(":memory:")

    try:
        con.execute("INSTALL datasketches FROM community")
        con.execute("LOAD datasketches")
    except duckdb.Error as exc:
        message = str(exc)
        if _is_network_error(message):
            print(f"network: SKIP ({message.splitlines()[0]})")
            return 0
        print(f"install: FAIL ({message.splitlines()[0]})")
        return 1

    version = con.execute(
        "SELECT extension_version FROM duckdb_extensions() WHERE extension_name = 'datasketches'"
    ).fetchone()
    print(f"extension_version: {version[0] if version else 'unknown'}")

    failures: list[str] = []
    for family, probe in REQUIRED_FAMILIES.items():
        try:
            con.execute(probe)
            print(f"{family}: OK")
        except duckdb.Error as exc:
            line = str(exc).splitlines()[0]
            print(f"{family}: FAIL ({line})")
            failures.append(family)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
