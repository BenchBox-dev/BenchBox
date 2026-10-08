# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.base import BaseBenchmark, GeneratorOutputDirMixin
from benchbox.core.amplab.generator import AMPLabDataGenerator
from benchbox.core.amplab.queries import AMPLabQueryManager
from benchbox.core.amplab.schema import TABLES, get_all_create_table_sql
from benchbox.core.benchmark_mixins import DataGenerationMixin
from benchbox.core.query_catalog_base import TranslatableQueryMixin
from benchbox.core.query_utils import get_queries_with_translation
from benchbox.core.simple_benchmark_mixin import SimpleBenchmarkMixin
from benchbox.core.utils.tuning import extract_constraint_flags

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration


class AMPLabBenchmark(
    GeneratorOutputDirMixin, TranslatableQueryMixin, SimpleBenchmarkMixin, DataGenerationMixin, BaseBenchmark
):
    _benchmark_label = "AMPLab"
    _table_load_order = ["rankings", "documents", "uservisits"]

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **config: Any,
    ):

        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, output_dir=output_dir, quiet=quiet, **config)

        self._name = "AMPLab Big Data Benchmark"
        self._version = "1.0"
        self._description = "AMPLab Big Data Benchmark - Tests big data processing systems with web analytics workloads"

        self.query_manager: AMPLabQueryManager = AMPLabQueryManager()
        self.data_generator = AMPLabDataGenerator(
            scale_factor,
            self.output_dir,
            **config,
        )

        self.tables = {}

    def _get_table_schema(self) -> dict[str, dict]:

        return TABLES

    def _get_data_loading_batch_size(self) -> int | None:

        return 10000

    def get_query(self, query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str:

        return self.query_manager.get_query(str(query_id), params)

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:

        return get_queries_with_translation(self.query_manager, dialect, self.translate_query_text)

    def get_all_queries(self) -> dict[str, str]:

        return self.query_manager.get_all_queries()

    def execute_query(
        self,
        query_id: Union[int, str],
        connection: Any,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:

        sql = self.get_query(query_id, params=params)

        if hasattr(connection, "execute"):
            cursor = connection.execute(sql)
            return cursor.fetchall()
        elif hasattr(connection, "cursor"):
            cursor = connection.cursor()
            cursor.execute(sql)
            return cursor.fetchall()
        else:
            raise ValueError("Unsupported connection type")

    def get_schema(self, dialect: str = "standard") -> dict[str, dict]:

        return TABLES

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        tuning_config: Optional["UnifiedTuningConfiguration"] = None,
    ) -> str:

        enable_primary_keys, enable_foreign_keys = extract_constraint_flags(tuning_config)
        return get_all_create_table_sql(dialect, enable_primary_keys, enable_foreign_keys)

    def get_csv_loading_config(self, table_name: str) -> list[str]:

        return ["delim='|'"]
