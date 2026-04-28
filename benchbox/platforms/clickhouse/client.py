"""Local ClickHouse client implementation."""

from __future__ import annotations

import contextlib
import csv
import logging
import re

logger = logging.getLogger(__name__)


class _ResultProxy:
    """Cursor-like wrapper around a result returned by chDB.

    Accepts either a list of row tuples or a pandas DataFrame. When backed by a
    DataFrame, tuple materialization is deferred until the caller iterates,
    indexes, or compares — keeping `len(result)` O(1) for large result sets.
    """

    def __init__(self, rows_or_df) -> None:
        self._df = None
        self._rows: list | None = None
        if rows_or_df is None:
            self._rows = []
        elif hasattr(rows_or_df, "itertuples"):  # pandas DataFrame
            self._df = rows_or_df
        else:
            self._rows = list(rows_or_df)
        self._pos = 0

    def _ensure_rows(self) -> list:
        if self._rows is None:
            assert self._df is not None
            self._rows = [tuple(r) for r in self._df.itertuples(index=False, name=None)]
        return self._rows

    def fetchone(self):
        rows = self._ensure_rows()
        if self._pos < len(rows):
            row = rows[self._pos]
            self._pos += 1
            return row
        return None

    def fetchall(self):
        rows = self._ensure_rows()
        remaining = rows[self._pos :]
        self._pos = len(rows)
        return remaining

    # Allow direct indexing / iteration so existing code that treats the
    # result as a list (e.g. `result[0][0]`) continues to work.
    def __getitem__(self, idx):
        return self._ensure_rows()[idx]

    def __iter__(self):
        return iter(self._ensure_rows())

    def __len__(self):
        if self._df is not None and self._rows is None:
            return len(self._df)
        return len(self._rows or [])

    def __bool__(self):
        return self.__len__() > 0

    def __eq__(self, other):
        if isinstance(other, _ResultProxy):
            return self._ensure_rows() == other._ensure_rows()
        if isinstance(other, list):
            return self._ensure_rows() == other
        return NotImplemented


class ClickHouseLocalClient:
    """Minimal client for interacting with local ClickHouse (chdb) instances."""

    _conn: object
    _is_persistent: bool

    def __init__(self, db_path: str | None = None):
        """Initialize local client with optional persistent storage path."""
        self._initialized = True
        # Use persistent session if path provided, otherwise use in-memory connection
        if db_path:
            from chdb.session import Session

            self._conn = Session(path=db_path)
            self._is_persistent = True
        else:
            import chdb

            self._conn = chdb.connect()
            self._is_persistent = False

    def execute(self, query: str, params=None):
        """Execute query using chDB."""
        try:
            # Handle INSERT with data values specially
            if query.strip().upper().startswith("INSERT") and params:
                return self._execute_insert(query, params)

            # `format="DataFrame"` returns a pandas DataFrame directly from chDB,
            # avoiding the per-row Python CSV parsing that previously dominated
            # wall-clock time for queries returning many rows (10–100× speedup
            # on multi-million-row results).
            # Session API: query(sql, format)  /  Connection API: query(sql, format=format)
            df = (
                self._conn.query(query, "DataFrame")
                if self._is_persistent
                else self._conn.query(query, format="DataFrame")
            )
            return _ResultProxy(df)

        except Exception as e:
            # Re-raise with more context
            raise RuntimeError(f"ClickHouse local query failed: {e}") from e

    def close(self):
        """Close the local connection and ensure data is persisted."""
        if hasattr(self, "_conn"):
            try:
                # For persistent sessions, ensure proper cleanup
                if hasattr(self._conn, "close"):
                    self._conn.close()
                elif hasattr(self._conn, "__del__"):
                    del self._conn
            except Exception:
                pass
        self._conn = None

    def _execute_insert(self, query: str, params):
        """Handle INSERT queries with data parameters."""
        # For INSERT operations with data, we need to format the query differently
        if isinstance(params, list) and params:
            # Convert list of rows into VALUES format
            values_list = []
            for row in params:
                # Convert row to properly formatted values
                formatted_values = []
                for val in row:
                    if isinstance(val, str):
                        # Escape single quotes and wrap in quotes
                        escaped_val = val.replace("'", "''")
                        formatted_values.append(f"'{escaped_val}'")
                    elif val is None:
                        formatted_values.append("NULL")
                    else:
                        formatted_values.append(str(val))
                values_list.append(f"({', '.join(formatted_values)})")

            # Construct full INSERT query
            full_query = f"{query} {', '.join(values_list)}"
            if self._is_persistent:
                self._conn.query(full_query)
            else:
                self._conn.query(full_query, format="CSV")
            return _ResultProxy([])  # INSERT typically doesn't return data
        else:
            # Regular query execution
            if self._is_persistent:
                self._conn.query(query)
            else:
                self._conn.query(query, format="CSV")
            return _ResultProxy([])

    def _parse_csv_line(self, line: str) -> tuple:
        """Parse a CSV line into a tuple with proper type conversion."""
        import io

        # Use proper CSV parsing
        reader = csv.reader(io.StringIO(line))
        row = next(reader)

        # Convert types
        converted_row = []
        for val in row:
            if val == "":
                converted_row.append(None)
            else:
                try:
                    # Try integer first
                    if "." not in val and val.lstrip("-").isdigit():
                        converted_row.append(int(val))
                    elif self._is_float(val):
                        # Try float
                        converted_row.append(float(val))
                    else:
                        # Keep as string
                        converted_row.append(val)
                except (ValueError, TypeError):
                    # Keep as string if conversion fails
                    converted_row.append(val)

        return tuple(converted_row)

    def _is_float(self, val: str) -> bool:
        """Check if string represents a float."""
        try:
            float(val)
            return True
        except ValueError:
            return False

    def executemany(self, query: str, params: list) -> _ResultProxy:
        """Execute a parameterized INSERT for multiple rows.

        Generic file-loading paths pass an INSERT...VALUES(?,?,...) template
        plus a list of row tuples.  ClickHouse doesn't support ? placeholders,
        so we build a single VALUES clause and execute it directly.
        """
        if not params:
            return _ResultProxy([])

        # Strip the placeholder VALUES(...) suffix from the template and
        # rebuild with concrete rows so ClickHouse accepts the statement.
        parts = re.split(r"\sVALUES\s", query, maxsplit=1, flags=re.IGNORECASE)
        base_query = parts[0]

        values_list = []
        for row in params:
            formatted_values = []
            for val in row:
                if isinstance(val, str):
                    # Escape backslashes first, then single quotes
                    escaped = val.replace("\\", "\\\\").replace("'", "''")
                    formatted_values.append(f"'{escaped}'")
                elif val is None:
                    formatted_values.append("NULL")
                else:
                    formatted_values.append(str(val))
            values_list.append(f"({', '.join(formatted_values)})")

        full_query = f"{base_query} VALUES {', '.join(values_list)}"
        if self._is_persistent:
            self._conn.query(full_query)
        else:
            self._conn.query(full_query, format="CSV")
        return _ResultProxy([])

    def disconnect(self):
        """Local mode doesn't need explicit disconnect."""

    def commit(self):
        """ClickHouse auto-commits, so this is a no-op for compatibility."""


class ClickHouseCloudClient:
    """Client for ClickHouse Cloud using clickhouse-connect (HTTPS protocol).

    This client provides a compatible interface with ClickHouseLocalClient and
    clickhouse-driver's Client, enabling ClickHouse Cloud connections via HTTPS.

    Authentication modes:
    - Password: Traditional username/password authentication (default)
    - OAuth/Bearer token: Token-based authentication via clickhouse-connect's access_token parameter
    """

    def __init__(
        self,
        host: str,
        port: int = 8443,
        user: str = "default",
        password: str = "",
        database: str = "default",
        secure: bool = True,
        access_token: str | None = None,
        **kwargs,
    ):
        """Initialize cloud client.

        Args:
            host: ClickHouse Cloud hostname (e.g., abc123.us-east-2.aws.clickhouse.cloud)
            port: HTTPS port (default: 8443)
            user: Username (default: default)
            password: Password for authentication
            database: Database name (default: default)
            secure: Use HTTPS (default: True, required for cloud)
            access_token: OAuth/bearer token for token-based authentication.
                When provided, this is used instead of username/password.
            **kwargs: Additional clickhouse-connect options
        """
        from ._dependencies import clickhouse_connect

        if clickhouse_connect is None:
            raise ImportError(
                "ClickHouse Cloud mode requires the clickhouse-connect package.\n"
                "Install with: uv add benchbox --extra clickhouse-cloud\n"
            )

        self._host = host
        self._port = port
        self._database = database

        # Build connection kwargs based on authentication mode
        connect_kwargs: dict = {
            "host": host,
            "port": port,
            "database": database,
            "secure": secure,
        }

        if access_token:
            # OAuth/bearer token authentication - pass via clickhouse-connect's access_token parameter
            connect_kwargs["access_token"] = access_token
            logger.info("Using OAuth/bearer token authentication for ClickHouse Cloud")
        else:
            # Traditional password authentication
            connect_kwargs["username"] = user
            connect_kwargs["password"] = password

        connect_kwargs.update(kwargs)

        # Create clickhouse-connect client
        self._client = clickhouse_connect.get_client(**connect_kwargs)

        logger.info(f"ClickHouse Cloud client initialized: {host}:{port}")

    def execute(self, query: str, params=None):
        """Execute query against ClickHouse Cloud.

        Args:
            query: SQL query to execute
            params: Optional query parameters (for INSERT operations)

        Returns:
            List of tuples containing query results
        """
        try:
            # Handle INSERT with data
            if query.strip().upper().startswith("INSERT") and params:
                return self._execute_insert(query, params)

            # Execute query
            result = self._client.query(query)

            # Convert to list of tuples (matching clickhouse-driver format)
            if result.result_set:
                return [tuple(row) for row in result.result_set]
            return []

        except Exception as e:
            raise RuntimeError(f"ClickHouse Cloud query failed: {e}") from e

    def _execute_insert(self, query: str, params):
        """Handle INSERT operations with data."""
        if isinstance(params, list) and params:
            # Extract table name from INSERT statement
            # Format: INSERT INTO table_name [(columns)] VALUES
            import re

            match = re.match(r"INSERT\s+INTO\s+(\S+)", query, re.IGNORECASE)
            if match:
                table_name = match.group(1)
                # Use clickhouse-connect's insert method for efficient bulk insert
                self._client.insert(table_name, params)
                return []

        # Fall back to regular execute
        self._client.command(query)
        return []

    def command(self, query: str):
        """Execute a command (DDL/DML) that doesn't return results."""
        return self._client.command(query)

    def close(self):
        """Close the cloud connection."""
        if hasattr(self, "_client") and self._client:
            with contextlib.suppress(Exception):
                self._client.close()
            self._client = None

    def disconnect(self):
        """Alias for close() for compatibility."""
        self.close()

    def commit(self):
        """ClickHouse auto-commits, so this is a no-op for compatibility."""

    @property
    def database(self) -> str:
        """Return the current database name."""
        return self._database


__all__ = ["ClickHouseLocalClient", "ClickHouseCloudClient"]
