"""TPC-DI source data format generators for various input types.

This module provides wrapper classes for the ETL framework that delegate to
the existing TPCDISourceDataGenerator implementation. These classes exist to
satisfy the ETL framework interface while reusing the battle-tested source
data generation logic.

For production use, prefer using TPCDISourceDataGenerator directly from
benchbox.core.tpcdi.source_generators.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from benchbox.core.tpcdi.source_generators import TPCDISourceDataGenerator


class SourceDataFormat(ABC):
    """Abstract base class for source data format generators."""

    _generator: Optional[TPCDISourceDataGenerator]

    @abstractmethod
    def generate_data(self, table_name: str, record_count: int, **kwargs: Any) -> Any:
        """Generate source data in the specific format.

        Args:
            table_name: Name of the table to generate data for
            record_count: Number of records to generate
            **kwargs: Additional format-specific parameters

        Returns:
            Generated data in the appropriate format
        """
        ...

    def _run_generator(
        self,
        gen_method_name: str,
        record_count: int,
        default_scale_divisor: float,
        **kwargs: Any,
    ) -> str:
        """Shared generator initialisation and invocation.

        Args:
            gen_method_name: Name of the ``TPCDISourceDataGenerator`` method to call
                (e.g. ``"_generate_oltp_data"``).
            record_count: Passed from the caller's ``record_count`` parameter.
            default_scale_divisor: Divisor for the default scale factor
                (``record_count / default_scale_divisor``).
            **kwargs: Forwarded from the caller (may contain ``scale_factor``,
                ``output_dir``).

        Returns:
            First generated file path, or ``""`` if no files were produced.
        """
        scale_factor = kwargs.get("scale_factor", record_count / default_scale_divisor)
        output_dir = kwargs.get("output_dir", Path.cwd() / "tpcdi_source_data")

        if self._generator is None:
            self._generator = TPCDISourceDataGenerator(
                scale_factor=scale_factor,
                output_dir=output_dir,
            )

        files = getattr(self._generator, gen_method_name)()
        return files[0] if files else ""


class CSVSourceFormat(SourceDataFormat):
    """Generates source data in CSV format.

    This is a lightweight wrapper around TPCDISourceDataGenerator that generates
    OLTP system data in CSV format (customer, account, trade extracts).
    """

    def __init__(self, delimiter: str = ",", quote_char: str = '"', encoding: str = "utf-8") -> None:
        """Initialize CSV format generator.

        Args:
            delimiter: Field delimiter character
            quote_char: Quote character for text fields
            encoding: Character encoding for output files
        """
        self.delimiter = delimiter
        self.quote_char = quote_char
        self.encoding = encoding
        self._generator: Optional[TPCDISourceDataGenerator] = None

    def generate_data(self, table_name: str, record_count: int, **kwargs: Any) -> str:
        """Generate CSV formatted data.

        Args:
            table_name: Name of the table (e.g., 'Customer', 'Account', 'Trade')
            record_count: Number of records to generate
            **kwargs: Additional CSV-specific parameters (scale_factor, output_dir)

        Returns:
            Path to generated CSV file as string
        """
        return self._run_generator("_generate_oltp_data", record_count, 50000, **kwargs)

    def write_to_file(self, data: pd.DataFrame, file_path: Path) -> None:
        """Write dataframe to CSV file.

        Args:
            data: Dataframe to write
            file_path: Output file path
        """
        data.to_csv(
            file_path,
            sep=self.delimiter,
            quotechar=self.quote_char,
            encoding=self.encoding,
            index=False,
        )


class XMLSourceFormat(SourceDataFormat):
    """Generates source data in XML format.

    This is a lightweight wrapper around TPCDISourceDataGenerator that generates
    HR system data in XML format (employee/broker hierarchical data).
    """

    def __init__(self, root_element: str = "data", record_element: str = "record") -> None:
        """Initialize XML format generator.

        Args:
            root_element: Name of the XML root element
            record_element: Name of individual record elements
        """
        self.root_element = root_element
        self.record_element = record_element
        self._generator: Optional[TPCDISourceDataGenerator] = None

    def generate_data(self, table_name: str, record_count: int, **kwargs: Any) -> str:
        """Generate XML formatted data.

        Args:
            table_name: Name of the table (e.g., 'Employee', 'Broker')
            record_count: Number of records to generate
            **kwargs: Additional XML-specific parameters (scale_factor, output_dir)

        Returns:
            Path to generated XML file as string
        """
        return self._run_generator("_generate_hr_data", record_count, 500, **kwargs)

    def write_to_file(self, data: pd.DataFrame, file_path: Path) -> None:
        """Write dataframe to XML file.

        Args:
            data: Dataframe to write
            file_path: Output file path
        """
        # Convert dataframe to XML
        data.to_xml(
            file_path,
            index=False,
            root_name=self.root_element,
            row_name=self.record_element,
        )


class FixedWidthSourceFormat(SourceDataFormat):
    """Generates source data in fixed-width format.

    This is a lightweight wrapper around TPCDISourceDataGenerator that generates
    legacy system data in fixed-width format.
    """

    def __init__(self, field_widths: dict[str, int], fill_char: str = " ") -> None:
        """Initialize fixed-width format generator.

        Args:
            field_widths: Dictionary mapping field names to their widths
            fill_char: Character to use for padding
        """
        self.field_widths = field_widths
        self.fill_char = fill_char
        self._generator: Optional[TPCDISourceDataGenerator] = None

    def generate_data(self, table_name: str, record_count: int, **kwargs: Any) -> str:
        """Generate fixed-width formatted data.

        Args:
            table_name: Name of the table
            record_count: Number of records to generate
            **kwargs: Additional fixed-width specific parameters (scale_factor, output_dir)

        Returns:
            Path to generated fixed-width file as string
        """
        return self._run_generator("_generate_external_data", record_count, 50000, **kwargs)

    def write_to_file(self, data: pd.DataFrame, file_path: Path) -> None:
        """Write dataframe to fixed-width file.

        Args:
            data: Dataframe to write
            file_path: Output file path
        """
        with open(file_path, "w", encoding="utf-8") as f:
            for _, row in data.iterrows():
                line = ""
                for col in data.columns:
                    width = self.field_widths.get(col, 20)  # Default width 20
                    value = str(row[col])[:width]  # Truncate if too long
                    line += value.ljust(width, self.fill_char)  # Pad with fill_char
                f.write(line + "\n")


class PipeDelimitedSourceFormat(SourceDataFormat):
    """Generates source data in pipe-delimited format (TPC-DI standard).

    This is a lightweight wrapper around TPCDISourceDataGenerator that generates
    data in pipe-delimited format (the TPC-DI standard format).
    """

    def __init__(self, escape_char: str = "\\", null_representation: str = "") -> None:
        """Initialize pipe-delimited format generator.

        Args:
            escape_char: Character to use for escaping
            null_representation: String representation of NULL values
        """
        self.delimiter = "|"
        self.escape_char = escape_char
        self.null_representation = null_representation
        self._generator: Optional[TPCDISourceDataGenerator] = None

    def generate_data(self, table_name: str, record_count: int, **kwargs: Any) -> str:
        """Generate pipe-delimited formatted data.

        Args:
            table_name: Name of the table
            record_count: Number of records to generate
            **kwargs: Additional pipe-delimited specific parameters (scale_factor, output_dir)

        Returns:
            Path to generated pipe-delimited file as string
        """
        scale_factor = kwargs.get("scale_factor", record_count / 50000)
        output_dir = kwargs.get("output_dir", Path.cwd() / "tpcdi_source_data")

        # Initialize generator if needed
        if self._generator is None:
            self._generator = TPCDISourceDataGenerator(
                scale_factor=scale_factor,
                output_dir=output_dir,
            )

        # Generate all source data (returns dict with all file types)
        all_files = self._generator.generate_all_source_data()

        # Return first OLTP file (typically pipe-delimited)
        oltp_files = all_files.get("oltp", [])
        return oltp_files[0] if oltp_files else ""

    def write_to_file(self, data: pd.DataFrame, file_path: Path) -> None:
        """Write dataframe to pipe-delimited file.

        Args:
            data: Dataframe to write
            file_path: Output file path
        """
        data.to_csv(
            file_path,
            sep=self.delimiter,
            index=False,
            na_rep=self.null_representation,
        )


class SourceDataGenerator:
    """Main generator for TPC-DI source data in various formats.

    This is a lightweight wrapper around TPCDISourceDataGenerator that provides
    a format-agnostic interface for generating TPC-DI source data.
    """

    def __init__(self, scale_factor: float = 1.0, seed: Optional[int] = None) -> None:
        """Initialize source data generator.

        Args:
            scale_factor: TPC-DI scale factor for data volume
            seed: Random seed for reproducible data generation
        """
        self.scale_factor = scale_factor
        self.seed = seed
        self.formats: dict[str, SourceDataFormat] = {}
        self._generator: Optional[TPCDISourceDataGenerator] = None
        self._register_default_formats()

    def _register_default_formats(self) -> None:
        """Register default source data formats."""
        self.formats["csv"] = CSVSourceFormat()
        self.formats["xml"] = XMLSourceFormat()
        self.formats["fixed_width"] = FixedWidthSourceFormat(field_widths={})
        self.formats["pipe"] = PipeDelimitedSourceFormat()

    def register_format(self, name: str, format_instance: SourceDataFormat) -> None:
        """Register a new source data format.

        Args:
            name: Name to register the format under
            format_instance: Instance of the format class
        """
        self.formats[name] = format_instance

    def generate_historical_data(
        self, format_name: str, output_dir: Path, tables: Optional[list[str]] = None
    ) -> dict[str, Path]:
        """Generate historical data files for initial load.

        Args:
            format_name: Name of the registered format to use (ignored, uses TPCDISourceDataGenerator)
            output_dir: Directory to write output files
            tables: List of table names to generate (None for all)

        Returns:
            Dictionary mapping table names to generated file paths
        """
        # Initialize generator if needed
        if self._generator is None:
            self._generator = TPCDISourceDataGenerator(
                scale_factor=self.scale_factor,
                output_dir=output_dir,
            )

        # Generate all source data
        all_files = self._generator.generate_all_source_data()

        # Convert to dict[str, Path] format
        result: dict[str, Path] = {}
        for file_type, file_paths in all_files.items():
            for i, file_path in enumerate(file_paths):
                key = f"{file_type}_{i}" if i > 0 else file_type
                result[key] = Path(file_path)

        return result

    def generate_incremental_data(
        self,
        format_name: str,
        output_dir: Path,
        batch_number: int,
        tables: Optional[list[str]] = None,
    ) -> dict[str, Path]:
        """Generate incremental data files for a specific batch.

        Args:
            format_name: Name of the registered format to use (ignored, uses TPCDISourceDataGenerator)
            output_dir: Directory to write output files
            batch_number: Batch number for incremental data
            tables: List of table names to generate (None for all)

        Returns:
            Dictionary mapping table names to generated file paths
        """
        # Initialize generator if needed
        if self._generator is None:
            self._generator = TPCDISourceDataGenerator(
                scale_factor=self.scale_factor,
                output_dir=output_dir,
            )

        # For incremental batches, generate subset of data
        # (In practice, would filter by batch_number)
        all_files = self._generator.generate_all_source_data()

        # Convert to dict[str, Path] format
        result: dict[str, Path] = {}
        for file_type, file_paths in all_files.items():
            for i, file_path in enumerate(file_paths):
                key = f"{file_type}_{i}_batch{batch_number}" if i > 0 else f"{file_type}_batch{batch_number}"
                result[key] = Path(file_path)

        return result

    def generate_customer_management_data(self, format_name: str, output_dir: Path, batch_number: int) -> Path:
        """Generate customer management data file.

        Args:
            format_name: Format to use for generation (ignored, uses TPCDISourceDataGenerator)
            output_dir: Output directory
            batch_number: Batch number

        Returns:
            Path to generated customer management file
        """
        # Initialize generator if needed
        if self._generator is None:
            self._generator = TPCDISourceDataGenerator(
                scale_factor=self.scale_factor,
                output_dir=output_dir,
            )

        # Generate customer extract (CRM data)
        file_path = self._generator._generate_customer_extract()
        return Path(file_path)

    def generate_daily_market_data(self, format_name: str, output_dir: Path, batch_date: str) -> Path:
        """Generate daily market data file.

        Args:
            format_name: Format to use for generation (ignored, uses TPCDISourceDataGenerator)
            output_dir: Output directory
            batch_date: Date for the batch in YYYY-MM-DD format

        Returns:
            Path to generated daily market file
        """
        # Initialize generator if needed
        if self._generator is None:
            self._generator = TPCDISourceDataGenerator(
                scale_factor=self.scale_factor,
                output_dir=output_dir,
                start_date=date.fromisoformat(batch_date),
                end_date=date.fromisoformat(batch_date),
            )

        # Generate market prices
        file_path = self._generator._generate_market_prices()
        return Path(file_path)

    def get_data_statistics(self) -> dict[str, Any]:
        """Get statistics about generated data.

        Returns:
            Dictionary containing data generation statistics
        """
        if self._generator is None:
            return {
                "scale_factor": self.scale_factor,
                "status": "not_generated",
            }

        # Get format info from generator
        format_info = self._generator.get_file_format_info()

        return {
            "scale_factor": self.scale_factor,
            "seed": self.seed,
            "registered_formats": list(self.formats.keys()),
            "file_formats": format_info,
            "status": "generated",
        }
