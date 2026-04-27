"""InfluxDB client wrapper for FlightSQL-based connections.

Provides a unified interface for InfluxDB 3.x connections using either the
influxdb3-python client or the flightsql-dbapi library.

InfluxDB 3.x Methods:
- SQL queries via FlightSQL protocol (primary method)
- Line Protocol writes via HTTP API (for data loading)
- InfluxQL for backward compatibility (not used in BenchBox)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ._dependencies import (
    FLIGHTSQL_AVAILABLE,
    INFLUXDB3_AVAILABLE,
    FlightSQLClient,
    InfluxDBClient3,
)

logger = logging.getLogger(__name__)


def escape_tag_value(value: str) -> str:
    """Escape special characters in tag values for Line Protocol.

    Tags must escape: comma, equals, space, backslash.
    """
    return value.replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def escape_field_string(value: str) -> str:
    """Escape special characters in string field values for Line Protocol.

    String fields must escape: double quotes, backslash.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def to_line_protocol(
    measurement: str,
    tags: dict[str, str],
    fields: dict[str, Any],
    timestamp: datetime | int | None = None,
) -> str:
    """Convert data to InfluxDB Line Protocol format.

    Line Protocol format:
        measurement,tag1=val1,tag2=val2 field1=val1,field2=val2 timestamp

    Args:
        measurement: Measurement name (table name)
        tags: Dictionary of tag key-value pairs (indexed)
        fields: Dictionary of field key-value pairs (values)
        timestamp: Unix timestamp (nanoseconds) or datetime

    Returns:
        Line Protocol formatted string
    """
    # Build tag set
    tag_parts = []
    for key, value in sorted(tags.items()):
        if value is not None and value != "":
            tag_parts.append(f"{escape_tag_value(key)}={escape_tag_value(str(value))}")
    tag_set = ",".join(tag_parts)

    # Build field set
    field_parts = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            field_parts.append(f"{key}={str(value).lower()}")
        elif isinstance(value, int):
            field_parts.append(f"{key}={value}i")
        elif isinstance(value, float):
            field_parts.append(f"{key}={value}")
        elif isinstance(value, str):
            field_parts.append(f'{key}="{escape_field_string(value)}"')
        else:
            field_parts.append(f"{key}={value}")
    field_set = ",".join(field_parts)

    if not field_set:
        raise ValueError(f"At least one field is required for measurement '{measurement}'")

    # Build timestamp
    if timestamp is None:
        ts_str = ""
    elif isinstance(timestamp, datetime):
        # Convert to nanoseconds
        ts_str = f" {int(timestamp.timestamp() * 1_000_000_000)}"
    else:
        ts_str = f" {timestamp}"

    # Build line
    if tag_set:
        return f"{measurement},{tag_set} {field_set}{ts_str}"
    else:
        return f"{measurement} {field_set}{ts_str}"


class InfluxDBConnection:
    """Unified connection wrapper for InfluxDB 3.x.

    Abstracts the differences between influxdb3-python and flightsql-dbapi
    clients, providing a consistent interface for query execution.

    The connection uses FlightSQL protocol for SQL queries, which returns
    Arrow data that can be converted to Python types.
    """

    def __init__(
        self,
        host: str,
        token: str,
        database: str,
        port: int = 443,
        ssl: bool = True,
        org: str | None = None,
        verify_ssl: bool = True,
        ca_cert_path: str | None = None,
    ):
        """Initialize InfluxDB connection.

        Args:
            host: InfluxDB server hostname (without protocol)
            token: Authentication token with read/write permissions
            database: Database (bucket) name to query
            port: Server port (default: 443 for HTTPS)
            ssl: Use SSL/TLS connection (default: True)
            org: Organization name (required for some InfluxDB deployments)
            verify_ssl: Verify TLS certificates (default: True). Set False for self-signed certs.
            ca_cert_path: Path to custom CA certificate bundle for TLS verification.
        """
        self.host = host
        self.token = token
        self.database = database
        self.port = port
        self.ssl = ssl
        self.org = org
        self.verify_ssl = verify_ssl
        self.ca_cert_path = ca_cert_path

        self._client = None
        self._client_type: str | None = None

        # Determine protocol
        protocol = "https" if ssl else "http"
        self._url = f"{protocol}://{host}:{port}"

    def connect(self) -> None:
        """Establish connection to InfluxDB.

        Prefers influxdb3-python if available, falls back to flightsql-dbapi.

        Raises:
            ImportError: If no InfluxDB client library is available
            ConnectionError: If connection to InfluxDB fails
        """
        if INFLUXDB3_AVAILABLE:
            self._connect_influxdb3()
        elif FLIGHTSQL_AVAILABLE:
            self._connect_flightsql()
        else:
            raise ImportError(
                "No InfluxDB client library available. Install one of:\n"
                "  - influxdb3-python: uv add influxdb3-python\n"
                "  - flightsql-dbapi: uv add flightsql-dbapi"
            )

    def _connect_influxdb3(self) -> None:
        """Connect using influxdb3-python client."""
        try:
            kwargs: dict[str, Any] = {}
            if not self.verify_ssl:
                kwargs["verify_ssl"] = False
            if self.ca_cert_path:
                kwargs["ssl_ca_cert"] = self.ca_cert_path

            self._client = InfluxDBClient3(
                host=self._url,
                token=self.token,
                database=self.database,
                org=self.org,
                **kwargs,
            )
            self._client_type = "influxdb3"
            logger.info(f"Connected to InfluxDB via influxdb3-python: {self._url}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to InfluxDB at {self._url}: {e}") from e

    def _connect_flightsql(self) -> None:
        """Connect using flightsql-dbapi client."""
        try:
            # FlightSQL uses host:port without protocol for gRPC
            grpc_host = f"{self.host}:{self.port}"

            kwargs: dict[str, Any] = {}
            if not self.verify_ssl:
                kwargs["disable_server_verification"] = True

            self._client = FlightSQLClient(
                host=grpc_host,
                token=self.token,
                metadata={"database": self.database},
                features={"metadata-reflection": "true"},
                **kwargs,
            )
            self._client_type = "flightsql"
            logger.info(f"Connected to InfluxDB via flightsql-dbapi: {grpc_host}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to InfluxDB at {self.host}:{self.port}: {e}") from e

    def execute(self, query: str, params: dict[str, Any] | None = None) -> list[tuple]:
        """Execute SQL query and return results as list of tuples.

        Args:
            query: SQL query string
            params: Optional query parameters (not yet supported)

        Returns:
            List of tuples containing row data

        Raises:
            RuntimeError: If query execution fails
        """
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            if self._client_type == "influxdb3":
                return self._execute_influxdb3(query)
            elif self._client_type == "flightsql":
                return self._execute_flightsql(query)
            else:
                raise RuntimeError(f"Unknown client type: {self._client_type}")
        except Exception as e:
            raise RuntimeError(f"InfluxDB query failed: {e}") from e

    def _execute_influxdb3(self, query: str) -> list[tuple]:
        """Execute query using influxdb3-python client."""
        # influxdb3-python returns a PyArrow Table
        table = self._client.query(query)

        if table is None or table.num_rows == 0:
            return []

        # Convert Arrow Table to list of tuples (transpose column-oriented dict to rows)
        dict_data = table.to_pydict()
        if not dict_data:
            return []
        columns = list(dict_data.keys())
        num_rows = len(dict_data[columns[0]])
        return [tuple(dict_data[col][i] for col in columns) for i in range(num_rows)]

    def _execute_flightsql(self, query: str) -> list[tuple]:
        """Execute query using flightsql-dbapi client."""
        # FlightSQL returns flight info with ticket
        info = self._client.execute(query)

        if not info.endpoints:
            return []

        # Get the data using the ticket
        ticket = info.endpoints[0].ticket
        reader = self._client.do_get(ticket)

        # Read all data as Arrow Table
        table = reader.read_all()

        if table.num_rows == 0:
            return []

        # Convert to list of tuples
        rows = []
        for i in range(table.num_rows):
            row = tuple(table.column(j)[i].as_py() for j in range(table.num_columns))
            rows.append(row)
        return rows

    def fetchone(self) -> tuple | None:
        """Fetch one row from the last query result.

        Note: InfluxDB FlightSQL doesn't support cursor-based fetching.
        This method is provided for DB-API compatibility but isn't efficient
        for large result sets.
        """
        raise NotImplementedError(
            "InfluxDB FlightSQL doesn't support cursor-based fetching. Use execute() to get all results at once."
        )

    def fetchall(self) -> list[tuple]:
        """Fetch all rows from the last query result.

        Note: InfluxDB FlightSQL returns all results in execute().
        This method is provided for DB-API compatibility.
        """
        raise NotImplementedError(
            "InfluxDB FlightSQL returns all results in execute(). Use execute() instead of fetchall()."
        )

    def close(self) -> None:
        """Close the InfluxDB connection."""
        if self._client is not None:
            try:
                if hasattr(self._client, "close"):
                    self._client.close()
            except Exception as e:
                logger.warning(f"Error closing InfluxDB connection: {e}")
            finally:
                self._client = None
                self._client_type = None

    def commit(self) -> None:
        """Commit transaction (no-op for InfluxDB)."""
        # InfluxDB doesn't support transactions in the traditional sense

    def write_line_protocol(self, lines: list[str], precision: str = "ns") -> int:
        """Write data using Line Protocol format.

        Args:
            lines: List of Line Protocol formatted strings
            precision: Timestamp precision (ns, us, ms, s). Default: ns (nanoseconds)

        Returns:
            Number of lines written

        Raises:
            RuntimeError: If write fails or client doesn't support writes
        """
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")

        if self._client_type != "influxdb3":
            raise RuntimeError("Write operations require influxdb3-python client. flightsql-dbapi is read-only.")

        try:
            # Join lines and write as single batch
            data = "\n".join(lines)
            self._client.write(data, write_precision=precision)
            return len(lines)
        except Exception as e:
            raise RuntimeError(f"InfluxDB write failed: {e}") from e

    def write_batch(
        self,
        measurement: str,
        records: list[dict[str, Any]],
        tag_columns: list[str],
        field_columns: list[str],
        timestamp_column: str | None = "time",
        precision: str = "ns",
        batch_size: int = 10000,
    ) -> int:
        """Write records as Line Protocol in batches.

        Args:
            measurement: Measurement name (table name)
            records: List of dictionaries containing the data
            tag_columns: Column names to use as tags (indexed)
            field_columns: Column names to use as fields (values)
            timestamp_column: Column name for timestamp, or None for server time
            precision: Timestamp precision (ns, us, ms, s)
            batch_size: Number of lines per batch

        Returns:
            Total number of records written
        """
        total_written = 0
        lines: list[str] = []

        for record in records:
            # Extract tags
            tags = {col: record.get(col) for col in tag_columns if record.get(col) is not None}

            # Extract fields
            fields = {col: record.get(col) for col in field_columns if record.get(col) is not None}

            if not fields:
                continue  # Skip records with no fields

            # Extract timestamp
            timestamp = None
            if timestamp_column and timestamp_column in record:
                ts_value = record[timestamp_column]
                if isinstance(ts_value, datetime):
                    timestamp = ts_value
                elif isinstance(ts_value, (int, float)):
                    timestamp = int(ts_value)

            # Convert to line protocol
            line = to_line_protocol(measurement, tags, fields, timestamp)
            lines.append(line)

            # Write batch when full
            if len(lines) >= batch_size:
                self.write_line_protocol(lines, precision)
                total_written += len(lines)
                lines = []

        # Write remaining lines
        if lines:
            self.write_line_protocol(lines, precision)
            total_written += len(lines)

        return total_written

    def test_connection(self) -> bool:
        """Test if connection is alive.

        Returns:
            True if connection is working
        """
        try:
            # Simple query to test connection
            result = self.execute("SELECT 1")
            return len(result) > 0
        except Exception:
            return False

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._client is not None


__all__ = ["InfluxDBConnection"]
