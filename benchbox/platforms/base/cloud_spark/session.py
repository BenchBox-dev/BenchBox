# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.dependencies import get_package_install_message

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

logger = logging.getLogger(__name__)


class SessionProtocol(Enum):
    LIVY = "livy"
    SPARK_CONNECT = "spark_connect"
    DATABRICKS_CONNECT = "databricks_connect"
    NATIVE_SDK = "native_sdk"


class SessionState(Enum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    SHUTTING_DOWN = "shutting_down"
    ERROR = "error"
    DEAD = "dead"


@dataclass
class SessionConfig:
    protocol: SessionProtocol
    endpoint: str
    port: int = 443

    credentials: dict[str, Any] = field(default_factory=dict)

    session_name: str = "benchbox-session"
    spark_version: str | None = None
    driver_memory: str = "4g"
    executor_memory: str = "4g"
    executor_cores: int = 2
    num_executors: int | None = None

    spark_conf: dict[str, str] = field(default_factory=dict)

    session_start_timeout: int = 300
    statement_timeout: int = 3600
    idle_timeout: int = 600

    track_cost: bool = True
    cost_unit: str = "DBU"


@dataclass
class SessionMetrics:
    session_id: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    statements_executed: int = 0
    bytes_scanned: int = 0
    bytes_shuffled: int = 0
    cost_units: float = 0.0

    @property
    def duration_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or mono_time()
        elapsed = elapsed_seconds(self.start_time, end)
        if elapsed >= 0:
            return elapsed
        wall_end = self.end_time or time.time()
        return max(0.0, wall_end - self.start_time)


class CloudSparkSessionManager(ABC):
    def __init__(self, config: SessionConfig) -> None:
        self.config = config
        self._session: Any = None
        self._state = SessionState.NOT_STARTED
        self._metrics = SessionMetrics()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @classmethod
    def for_emr(
        cls,
        cluster_id: str,
        region: str = "us-east-1",
        **kwargs: Any,
    ) -> CloudSparkSessionManager:
        config = SessionConfig(
            protocol=SessionProtocol.LIVY,
            endpoint=f"https://{cluster_id}.emr.{region}.amazonaws.com",
            credentials={"region": region},
            **kwargs,
        )
        return LivySessionManager(config)

    @classmethod
    def for_dataproc(
        cls,
        project_id: str,
        region: str,
        cluster_name: str,
        **kwargs: Any,
    ) -> CloudSparkSessionManager:
        config = SessionConfig(
            protocol=SessionProtocol.LIVY,
            endpoint=f"https://{cluster_name}-m.{region}.c.{project_id}.internal:8998",
            credentials={"project_id": project_id, "region": region},
            **kwargs,
        )
        return LivySessionManager(config)

    @classmethod
    def for_synapse(
        cls,
        workspace_name: str,
        spark_pool_name: str,
        **kwargs: Any,
    ) -> CloudSparkSessionManager:
        config = SessionConfig(
            protocol=SessionProtocol.LIVY,
            endpoint=f"https://{workspace_name}.dev.azuresynapse.net/livyApi/versions/2019-11-01-preview/sparkPools/{spark_pool_name}",
            **kwargs,
        )
        return LivySessionManager(config)

    @classmethod
    def for_databricks(
        cls,
        host: str,
        cluster_id: str,
        token: str,
        **kwargs: Any,
    ) -> CloudSparkSessionManager:
        config = SessionConfig(
            protocol=SessionProtocol.DATABRICKS_CONNECT,
            endpoint=host,
            credentials={"token": token, "cluster_id": cluster_id},
            **kwargs,
        )
        return DatabricksConnectSessionManager(config)

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def metrics(self) -> SessionMetrics:
        return self._metrics

    @property
    def is_active(self) -> bool:
        return self._state in (SessionState.IDLE, SessionState.BUSY)

    @abstractmethod
    def create_session(self) -> Any:
        pass

    @abstractmethod
    def get_session(self) -> Any:
        pass

    @abstractmethod
    def close_session(self) -> None:
        pass

    @abstractmethod
    def execute_statement(self, code: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def get_session_info(self) -> dict[str, Any]:
        pass

    @contextmanager
    def session(self) -> Iterator[Any]:
        try:
            spark = self.get_session()
            self._metrics.start_time = mono_time()
            yield spark
        finally:
            self._metrics.end_time = mono_time()
            self.close_session()


class LivySessionManager(CloudSparkSessionManager):
    def __init__(self, config: SessionConfig) -> None:
        super().__init__(config)
        self._session_id: int | None = None
        self._http_client: Any = None

    def _get_http_client(self) -> Any:
        if self._http_client is None:
            try:
                import requests
            except ImportError as e:
                raise ImportError(get_package_install_message("requests", "requests required for Livy API.")) from e
            self._http_client = requests.Session()
        return self._http_client

    def _livy_request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._get_http_client()
        url = f"{self.config.endpoint}{path}"

        headers = {"Content-Type": "application/json"}

        response = client.request(method, url, json=json, headers=headers)
        response.raise_for_status()

        return response.json()

    def create_session(self) -> Any:
        self._state = SessionState.STARTING
        self._logger.info("Creating Livy session...")

        session_conf = {
            "kind": "pyspark",
            "name": self.config.session_name,
            "driverMemory": self.config.driver_memory,
            "executorMemory": self.config.executor_memory,
            "executorCores": self.config.executor_cores,
        }

        if self.config.num_executors:
            session_conf["numExecutors"] = self.config.num_executors

        if self.config.spark_conf:
            session_conf["conf"] = self.config.spark_conf

        response = self._livy_request("POST", "/sessions", json=session_conf)
        self._session_id = response["id"]
        self._metrics.session_id = str(self._session_id)

        self._wait_for_session_ready()

        self._state = SessionState.IDLE
        self._logger.info(f"Livy session {self._session_id} ready")

        return self._session_id

    def _wait_for_session_ready(self) -> None:
        start = mono_time()
        timeout = self.config.session_start_timeout

        while elapsed_seconds(start) < timeout:
            info = self._livy_request("GET", f"/sessions/{self._session_id}")
            state = info.get("state", "unknown")

            if state == "idle":
                return
            elif state in ("dead", "error", "killed"):
                raise RuntimeError(f"Livy session failed: {state}")

            time.sleep(5)

        raise TimeoutError(f"Session start timeout after {timeout}s")

    def get_session(self) -> Any:
        if self._session_id is None:
            self.create_session()
        return self._session_id

    def close_session(self) -> None:
        if self._session_id is not None:
            self._state = SessionState.SHUTTING_DOWN
            try:
                self._livy_request("DELETE", f"/sessions/{self._session_id}")
                self._logger.info(f"Livy session {self._session_id} closed")
            except Exception as e:
                self._logger.warning(f"Error closing session: {e}")
            finally:
                self._session_id = None
                self._state = SessionState.DEAD

    def execute_statement(self, code: str) -> dict[str, Any]:
        if self._session_id is None:
            raise RuntimeError("No active session")

        self._state = SessionState.BUSY

        response = self._livy_request(
            "POST",
            f"/sessions/{self._session_id}/statements",
            json={"code": code},
        )
        statement_id = response["id"]

        result = self._wait_for_statement(statement_id)

        self._metrics.statements_executed += 1
        self._state = SessionState.IDLE

        return result

    def _wait_for_statement(self, statement_id: int) -> dict[str, Any]:
        start = mono_time()
        timeout = self.config.statement_timeout

        while elapsed_seconds(start) < timeout:
            response = self._livy_request(
                "GET",
                f"/sessions/{self._session_id}/statements/{statement_id}",
            )
            state = response.get("state", "waiting")

            if state == "available":
                return response.get("output", {})
            elif state in ("error", "cancelled"):
                raise RuntimeError(f"Statement failed: {response}")

            time.sleep(1)

        raise TimeoutError(f"Statement timeout after {timeout}s")

    def get_session_info(self) -> dict[str, Any]:
        if self._session_id is None:
            return {"state": "not_started"}
        return self._livy_request("GET", f"/sessions/{self._session_id}")


class DatabricksConnectSessionManager(CloudSparkSessionManager):
    def __init__(self, config: SessionConfig) -> None:
        super().__init__(config)
        self._spark: Any = None

    def create_session(self) -> SparkSession:
        try:
            from databricks.connect import DatabricksSession
        except ImportError as e:
            raise ImportError(get_package_install_message("databricks-connect", "databricks-connect required.")) from e

        self._state = SessionState.STARTING
        self._logger.info("Creating Databricks Connect session...")

        builder = DatabricksSession.builder
        builder = builder.host(self.config.endpoint)

        if "token" in self.config.credentials:
            builder = builder.token(self.config.credentials["token"])
        if "cluster_id" in self.config.credentials:
            builder = builder.clusterId(self.config.credentials["cluster_id"])

        self._spark = builder.getOrCreate()
        self._state = SessionState.IDLE
        self._metrics.session_id = "databricks-connect"
        self._metrics.start_time = mono_time()

        self._logger.info("Databricks Connect session ready")
        return self._spark

    def get_session(self) -> SparkSession:
        if self._spark is None:
            self.create_session()
        return self._spark

    def close_session(self) -> None:
        if self._spark is not None:
            self._state = SessionState.SHUTTING_DOWN
            try:
                self._spark.stop()
                self._logger.info("Databricks Connect session stopped")
            except Exception as e:
                self._logger.warning(f"Error stopping session: {e}")
            finally:
                self._spark = None
                self._state = SessionState.DEAD
                self._metrics.end_time = mono_time()

    def execute_statement(self, code: str) -> dict[str, Any]:
        if self._spark is None:
            raise RuntimeError("No active session")

        self._state = SessionState.BUSY

        sql_prefixes = (
            "SELECT",
            "CREATE",
            "INSERT",
            "DROP",
            "ALTER",
            "USE",
            "SHOW",
            "DESCRIBE",
            "EXPLAIN",
            "SET",
            "WITH",
            "MERGE",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
        )
        code_upper = code.strip().upper()
        if not any(code_upper.startswith(prefix) for prefix in sql_prefixes):
            self._state = SessionState.IDLE
            raise RuntimeError(
                f"Only SQL statements are supported. Code must start with one of: {', '.join(sql_prefixes)}"
            )

        result = self._spark.sql(code).collect()
        output = {"data": [list(row) for row in result]}

        self._metrics.statements_executed += 1
        self._state = SessionState.IDLE

        return output

    def get_session_info(self) -> dict[str, Any]:
        if self._spark is None:
            return {"state": "not_started"}

        return {
            "state": self._state.value,
            "session_id": self._metrics.session_id,
            "protocol": "databricks_connect",
            "spark_version": self._spark.version if self._spark else None,
        }
