"""ClickBench schema definitions.

This module defines the schema for the ClickBench benchmark, which consists of
a single flat table representing web analytics data with ~100 columns covering
various aspects of web traffic analysis.

The table schema is based on real-world web analytics data and includes
metrics for user sessions, browser information, referrers, search phrases,
geographical data, and various event attributes.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from typing import cast

from benchbox.core.tuning import BenchmarkTunings, TableTuning, TuningColumn

# ClickBench uses a single flat table called 'hits' with web analytics data.
#
# Type-width notes for SMALLINT columns
# ──────────────────────────────────────
# Several ClickHouse source types are unsigned (UInt8, UInt16) and thus wider
# than signed SMALLINT on the positive side.  Three columns that can genuinely
# exceed SMALLINT_MAX (32 767) in ClickHouse data are widened to INTEGER below
# (Interests, RefererCategoryID, URLCategoryID).
#
# The remaining UInt16 columns are kept as SMALLINT because the BenchBox
# synthetic generator intentionally caps their values well below 32 767:
#
#   Column              ClickHouse type   BenchBox generator range
#   ────────────────    ───────────────   ────────────────────────
#   UserAgent           UInt16            randint(1, 1_000)
#   ResolutionWidth     UInt16            choice from standard resolutions, max 1_920
#   ResolutionHeight    UInt16            choice from standard resolutions, max 1_200
#   UserAgentMajor      UInt16            randint(1, 100)
#   SearchEngineID      UInt16            randint(0, 50)
#   WindowClientWidth   UInt16            same as ResolutionWidth
#   WindowClientHeight  UInt16            same as ResolutionHeight
#   SilverlightVersion2 UInt16            randint(0, 50)
#   SilverlightVersion4 UInt16            randint(0, 100)
#   HistoryLength       UInt16            randint(1, 100)
#   HTTPError           UInt16            choice([0, 200, 404, 500])
#   ParamCurrencyID     UInt16            randint(0, 10)
#
# If loading real ClickHouse-exported data (not BenchBox-generated), widen
# these columns to INTEGER before loading into strict-mode databases.
# See TestClickBenchSchemaRanges in tests/unit/test_clickbench_csv_loading.py.
HITS_TABLE = {
    "name": "hits",
    "columns": [
        {"name": "WatchID", "type": "BIGINT", "nullable": False},
        {"name": "JavaEnable", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "Title", "type": "TEXT", "nullable": False},
        {"name": "GoodEvent", "type": "SMALLINT", "nullable": False},  # Int16; BenchBox: always 1
        {"name": "EventTime", "type": "TIMESTAMP", "nullable": False},
        {"name": "EventDate", "type": "DATE", "nullable": False},
        {"name": "CounterID", "type": "BIGINT", "nullable": False},
        {"name": "ClientIP", "type": "BIGINT", "nullable": False},
        {"name": "RegionID", "type": "BIGINT", "nullable": False},
        {"name": "UserID", "type": "BIGINT", "nullable": False},
        {"name": "CounterClass", "type": "SMALLINT", "nullable": False},  # Int8; BenchBox: always 0
        {"name": "OS", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 1-50
        {"name": "UserAgent", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: 1-1_000 (< 32 767)
        {"name": "URL", "type": "TEXT", "nullable": False},
        {"name": "Referer", "type": "TEXT", "nullable": False},
        {"name": "IsRefresh", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        # RefererCategoryID and URLCategoryID are UInt16 (0-65 535); BenchBox generates full range
        {"name": "RefererCategoryID", "type": "INTEGER", "nullable": False},
        {"name": "RefererRegionID", "type": "BIGINT", "nullable": False},
        {"name": "URLCategoryID", "type": "INTEGER", "nullable": False},
        {"name": "URLRegionID", "type": "BIGINT", "nullable": False},
        {"name": "ResolutionWidth", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: ≤ 1_920
        {"name": "ResolutionHeight", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: ≤ 1_200
        {"name": "ResolutionDepth", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 16/24/32
        {"name": "FlashMajor", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-20
        {"name": "FlashMinor", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-20
        {"name": "FlashMinor2", "type": "VARCHAR(255)", "nullable": False},
        {"name": "NetMajor", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-10
        {"name": "NetMinor", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-20
        {"name": "UserAgentMajor", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: 1-100
        {"name": "UserAgentMinor", "type": "VARCHAR(255)", "nullable": False},
        {"name": "CookieEnable", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "JavascriptEnable", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "IsMobile", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "MobilePhone", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "MobilePhoneModel", "type": "VARCHAR(255)", "nullable": False},
        {"name": "Params", "type": "TEXT", "nullable": False},
        {"name": "IPNetworkID", "type": "BIGINT", "nullable": False},
        {"name": "TraficSourceID", "type": "SMALLINT", "nullable": False},  # Int8; BenchBox: -1-10
        {"name": "SearchEngineID", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: 0-50
        {"name": "SearchPhrase", "type": "VARCHAR(1024)", "nullable": False},
        {"name": "AdvEngineID", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-20
        {"name": "IsArtifical", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "WindowClientWidth", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: ≤ 1_920
        {"name": "WindowClientHeight", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: ≤ 1_200
        {"name": "ClientTimeZone", "type": "SMALLINT", "nullable": False},  # Int16; BenchBox: -12 to 12
        {"name": "ClientEventTime", "type": "TIMESTAMP", "nullable": False},
        {"name": "SilverlightVersion1", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-5
        {"name": "SilverlightVersion2", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: 0-50
        # SilverlightVersion3 is UInt32 in ClickHouse (0-4 294 967 295); BIGINT is the narrowest safe signed type
        {"name": "SilverlightVersion3", "type": "BIGINT", "nullable": False},
        {"name": "SilverlightVersion4", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: 0-100
        {"name": "PageCharset", "type": "VARCHAR(255)", "nullable": False},
        {"name": "CodeVersion", "type": "BIGINT", "nullable": False},
        {"name": "IsLink", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "IsDownload", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "IsNotBounce", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "FUniqID", "type": "BIGINT", "nullable": False},
        {"name": "OriginalURL", "type": "TEXT", "nullable": False},
        {"name": "HID", "type": "BIGINT", "nullable": False},
        {"name": "IsOldCounter", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "IsEvent", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "IsParameter", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "DontCountHits", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "WithHash", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "HitColor", "type": "VARCHAR(1)", "nullable": False},
        {"name": "LocalEventTime", "type": "TIMESTAMP", "nullable": False},
        {"name": "Age", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 18-65
        {"name": "Sex", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-2
        {"name": "Income", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-10
        # Interests is UInt16 in ClickHouse (0-65 535); BenchBox generates full range, so SMALLINT overflows
        {"name": "Interests", "type": "INTEGER", "nullable": False},
        {"name": "Robotness", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-255
        {"name": "RemoteIP", "type": "BIGINT", "nullable": False},
        {"name": "WindowName", "type": "INTEGER", "nullable": False},
        {"name": "OpenerName", "type": "INTEGER", "nullable": False},
        {"name": "HistoryLength", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: 1-100
        {"name": "BrowserLanguage", "type": "VARCHAR(2)", "nullable": False},
        {"name": "BrowserCountry", "type": "VARCHAR(2)", "nullable": False},
        {"name": "SocialNetwork", "type": "VARCHAR(255)", "nullable": False},
        {"name": "SocialAction", "type": "VARCHAR(255)", "nullable": False},
        {"name": "HTTPError", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: 0/200/404/500
        {"name": "SendTiming", "type": "INTEGER", "nullable": False},
        {"name": "DNSTiming", "type": "INTEGER", "nullable": False},
        {"name": "ConnectTiming", "type": "INTEGER", "nullable": False},
        {"name": "ResponseStartTiming", "type": "INTEGER", "nullable": False},
        {"name": "ResponseEndTiming", "type": "INTEGER", "nullable": False},
        {"name": "FetchTiming", "type": "INTEGER", "nullable": False},
        {"name": "SocialSourceNetworkID", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-50
        {"name": "SocialSourcePage", "type": "TEXT", "nullable": False},
        {"name": "ParamPrice", "type": "BIGINT", "nullable": False},
        {"name": "ParamOrderID", "type": "VARCHAR(255)", "nullable": False},
        {"name": "ParamCurrency", "type": "VARCHAR(3)", "nullable": False},
        {"name": "ParamCurrencyID", "type": "SMALLINT", "nullable": False},  # UInt16; BenchBox: 0-10
        {"name": "OpenstatServiceName", "type": "VARCHAR(255)", "nullable": False},
        {"name": "OpenstatCampaignID", "type": "VARCHAR(255)", "nullable": False},
        {"name": "OpenstatAdID", "type": "VARCHAR(255)", "nullable": False},
        {"name": "OpenstatSourceID", "type": "VARCHAR(255)", "nullable": False},
        {"name": "UTMSource", "type": "VARCHAR(255)", "nullable": False},
        {"name": "UTMMedium", "type": "VARCHAR(255)", "nullable": False},
        {"name": "UTMCampaign", "type": "VARCHAR(255)", "nullable": False},
        {"name": "UTMContent", "type": "VARCHAR(255)", "nullable": False},
        {"name": "UTMTerm", "type": "VARCHAR(255)", "nullable": False},
        {"name": "FromTag", "type": "VARCHAR(255)", "nullable": False},
        {"name": "HasGCLID", "type": "SMALLINT", "nullable": False},  # UInt8; BenchBox: 0-1
        {"name": "RefererHash", "type": "BIGINT", "nullable": False},
        {"name": "URLHash", "type": "BIGINT", "nullable": False},
        {"name": "CLID", "type": "BIGINT", "nullable": False},
    ],
    "primary_key": ["CounterID", "EventDate", "UserID", "EventTime", "WatchID"],
}


def get_create_table_sql(
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for the ClickBench hits table.

    Args:
        dialect: SQL dialect to use ("standard", "postgres", "mysql", etc.)
        enable_primary_keys: Whether to include primary key constraints
        enable_foreign_keys: Whether to include foreign key constraints

    Returns:
        SQL CREATE TABLE statement
    """
    table = HITS_TABLE
    columns = []

    for col in table["columns"]:
        col_def = f"{cast(str, col['name'])} {cast(str, col['type'])}"
        if not col.get("nullable", True):
            col_def += " NOT NULL"
        columns.append(f"  {col_def}")

    # Add primary key
    if table.get("primary_key") and enable_primary_keys:
        pk_cols = ", ".join(cast(list[str], table["primary_key"]))
        columns.append(f"  PRIMARY KEY ({pk_cols})")

    columns_sql = ",\n".join(columns)

    return f"""CREATE TABLE {table["name"]} (
{columns_sql}
);"""


# Schema as a dictionary for compatibility with other benchmarks
TABLES = {"hits": HITS_TABLE}


def get_tunings() -> BenchmarkTunings:
    """Get the default tuning configurations for ClickBench tables.

    These tunings are for web analytics workloads with focus on
    time-series analysis and high-cardinality filtering common in ClickBench queries.

    Returns:
        BenchmarkTunings containing tuning configurations for ClickBench tables
    """
    tunings = BenchmarkTunings("clickbench")

    # Hits table - single large table for web analytics queries
    hits_tuning = TableTuning(
        table_name="hits",
        partitioning=[TuningColumn("EventDate", "DATE", 1)],
        clustering=[
            TuningColumn("CounterID", "BIGINT", 1),
            TuningColumn("UserID", "BIGINT", 2),
        ],
        sorting=[
            TuningColumn("EventTime", "TIMESTAMP", 1),
            TuningColumn("RegionID", "BIGINT", 2),
        ],
    )
    tunings.add_table_tuning(hits_tuning)

    return tunings
