# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-DS specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import logging
from typing import Optional, Union

from .c_tools import DSQGenBinary, TPCDSError

_log = logging.getLogger(__name__)


class TPCDSQueryManager:
    def __init__(self) -> None:
        self._initialization_error: Optional[Exception] = None
        try:
            self.dsqgen = DSQGenBinary()
            self.available = True
        except Exception as exc:
            self.dsqgen = None
            self.available = False
            self._initialization_error = exc

    def _ensure_available(self) -> None:
        if not getattr(self, "available", False) or self.dsqgen is None:
            message = (
                "TPC-DS query templates and dsqgen binary are not available. "
                "Install the TPC-DS toolkit or point BenchBox at compiled binaries."
            )
            if self._initialization_error:
                message += f" Details: {self._initialization_error}"
            raise RuntimeError(message)

    def get_query(
        self,
        query_id: int,
        *,
        seed: Optional[int] = None,
        scale_factor: float = 1.0,
        stream_id: Optional[int] = None,
        dialect: str = "netezza",
    ) -> str:
        self._ensure_available()

        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 99):
            raise ValueError(f"Query ID must be 1-99, got {query_id}")

        if scale_factor is not None:
            if not isinstance(scale_factor, (int, float)):
                raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
            if scale_factor <= 0:
                raise ValueError(f"scale_factor must be positive, got {scale_factor}")

        if seed is not None and not isinstance(seed, int):
            raise TypeError(f"seed must be an integer, got {type(seed).__name__}")

        if stream_id is not None and not isinstance(stream_id, int):
            raise TypeError(f"stream_id must be an integer, got {type(stream_id).__name__}")

        return self.dsqgen.generate(
            query_id,
            seed=seed,
            scale_factor=scale_factor,
            stream_id=stream_id,
            dialect=dialect,
        )

    def get_all_queries(self, **kwargs: Union[int, float, str]) -> dict[int, str]:
        self._ensure_available()

        queries = {}
        failed_ids: list[int] = []

        for query_id in range(1, 100):
            try:
                queries[query_id] = self.get_query(query_id, **kwargs)
            except (TPCDSError, ValueError) as exc:
                failed_ids.append(query_id)
                _log.warning("dsqgen failed for query %d: %s", query_id, exc)
                continue

        if not queries:
            raise RuntimeError(
                f"dsqgen failed for all {len(failed_ids)} TPC-DS queries - "
                "check that the dsqgen binary is available and functional. "
                f"First failed query ID: {failed_ids[0] if failed_ids else 'unknown'}"
            )

        return queries

    def get_query_variations(self, query_id: int) -> list[str]:
        self._ensure_available()

        return self.dsqgen.get_query_variations(query_id)

    def validate_query_id(self, query_id: Union[int, str]) -> bool:
        self._ensure_available()

        return self.dsqgen.validate_query_id(query_id)

    def generate_with_parameters(
        self,
        query_id: int,
        parameters: dict[str, Union[str, int, float]],
        *,
        scale_factor: float = 1.0,
        dialect: str = "netezza",
    ) -> str:
        self._ensure_available()

        return self.dsqgen.generate_with_parameters(query_id, parameters, scale_factor=scale_factor, dialect=dialect)
