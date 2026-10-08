import logging
from typing import Any, Optional, Protocol, Union

logger = logging.getLogger(__name__)


class DBCursor(Protocol):
    def execute(self, query: str, parameters: Optional[Any] = None) -> Any: ...
    def executemany(self, query: str, parameters: list[Any]) -> Any: ...
    def fetchone(self) -> Optional[tuple[Any, ...]]: ...
    def fetchmany(self, size: int = 1) -> list[tuple[Any, ...]]: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
    def close(self) -> None: ...
    def __enter__(self) -> "DBCursor": ...
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...


class DBConnection(Protocol):
    def cursor(self) -> DBCursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class DatabaseError(Exception):
    pass


class DatabaseConnection:
    def __init__(self, connection: DBConnection, dialect: Optional[str] = None) -> None:
        if connection is None:
            raise TypeError("Connection object cannot be None")

        if not hasattr(connection, "cursor") and not hasattr(connection, "execute"):
            raise ValueError("Connection object must have either 'cursor' or 'execute' method to be DB-API compatible")

        self.connection = connection
        self.dialect = dialect
        self.cursor: Optional[DBCursor] = None

    def execute(
        self,
        query: str,
        parameters: Optional[Union[list[Any], dict[str, Any], tuple[Any, ...]]] = None,
    ) -> DBCursor:
        if not query or not str(query).strip():
            raise ValueError("Query cannot be empty or None")

        snippet = str(query).strip().replace("\n", " ") if query else ""
        truncated = (snippet[:100] + "...") if len(snippet) > 100 else (snippet + ("..." if snippet else ""))

        try:
            if hasattr(self.connection, "execute"):
                logger.debug(f"Executing query with direct execute method: {truncated}")
                if parameters is None:
                    self.cursor = self.connection.execute(query)
                else:
                    self.cursor = self.connection.execute(query, parameters)
                return self.cursor

            if hasattr(self.connection, "cursor"):
                logger.debug(f"Executing query with cursor method: {truncated}")
                cur = self.connection.cursor()
                if parameters is None:
                    cur.execute(query)
                else:
                    cur.execute(query, parameters)
                self.cursor = cur
                return self.cursor

            raise ValueError("Connection object has neither 'execute' nor 'cursor' method")
        except Exception as e:
            base = "Error executing query"
            if self.dialect:
                base += f" (dialect: {self.dialect})"
            error_msg = f"{base}: {e}"
            if snippet:
                error_msg += f" | Query: {snippet if len(snippet) <= 120 else snippet[:120] + '...'}"
            logger.error(error_msg)
            raise DatabaseError(error_msg) from e

    def fetchall(self, cursor: Optional[DBCursor] = None) -> list[tuple[Any, ...]]:
        try:
            cur = cursor or self.cursor
            if cur is None:
                raise ValueError("No cursor available - execute a query first")
            if hasattr(cur, "fetchall"):
                return cur.fetchall()
            raise ValueError("Cursor object does not have fetchall method")
        except Exception as e:
            error_msg = f"Error fetching results: {e}"
            logger.error(error_msg)
            raise DatabaseError(error_msg) from e

    def fetchone(self, cursor: Optional[DBCursor] = None) -> Optional[tuple[Any, ...]]:
        try:
            cur = cursor or self.cursor
            if cur is None:
                raise ValueError("No cursor available - execute a query first")
            if hasattr(cur, "fetchone"):
                return cur.fetchone()
            raise ValueError("Cursor object does not have fetchone method")
        except Exception as e:
            error_msg = f"Error fetching result: {e}"
            logger.error(error_msg)
            raise DatabaseError(error_msg) from e

    def close(self) -> None:
        try:
            if hasattr(self.connection, "close"):
                self.connection.close()
                logger.debug("Database connection closed")
            else:
                logger.warning("Connection object does not have close method")
        except Exception as e:
            error_msg = f"Error closing connection: {e}"
            logger.error(error_msg)
            raise DatabaseError(error_msg) from e

    def commit(self) -> None:
        try:
            if hasattr(self.connection, "commit"):
                self.connection.commit()
                logger.debug("Transaction committed")
            else:
                logger.warning("Connection object does not have commit method")
        except Exception as e:
            error_msg = f"Error committing transaction: {e}"
            logger.error(error_msg)
            raise DatabaseError(error_msg) from e

    def rollback(self) -> None:
        try:
            if hasattr(self.connection, "rollback"):
                self.connection.rollback()
                logger.debug("Transaction rolled back")
            else:
                logger.warning("Connection object does not have rollback method")
        except Exception as e:
            error_msg = f"Error rolling back transaction: {e}"
            logger.error(error_msg)
            raise DatabaseError(error_msg) from e

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        dialect_str = f", dialect={self.dialect}" if self.dialect else ""
        return f"DatabaseConnection({type(self.connection).__name__}{dialect_str})"
