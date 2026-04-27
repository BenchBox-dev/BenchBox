"""Unit tests for TPC-DI ETL source data format generators.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]

from benchbox.core.tpcdi.etl.sources import (
    CSVSourceFormat,
    FixedWidthSourceFormat,
    PipeDelimitedSourceFormat,
    SourceDataGenerator,
    XMLSourceFormat,
)


class TestCSVSourceFormat:
    """Test CSV source format generator."""

    def test_initialization(self) -> None:
        """Test CSV format initialization."""
        csv_format = CSVSourceFormat()
        assert csv_format.delimiter == ","
        assert csv_format.quote_char == '"'
        assert csv_format.encoding == "utf-8"

    def test_initialization_with_custom_params(self) -> None:
        """Test CSV format initialization with custom parameters."""
        csv_format = CSVSourceFormat(delimiter="|", quote_char="'", encoding="latin1")
        assert csv_format.delimiter == "|"
        assert csv_format.quote_char == "'"
        assert csv_format.encoding == "latin1"

    def test_generate_data_returns_string(self) -> None:
        """Test that generate_data returns a file path string."""
        csv_format = CSVSourceFormat()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = csv_format.generate_data(
                "Customer",
                1000,
                scale_factor=0.02,
                output_dir=Path(tmpdir),
            )
            assert isinstance(result, str)

    def test_write_to_file(self) -> None:
        """Test writing dataframe to CSV file."""
        csv_format = CSVSourceFormat()
        test_data = pd.DataFrame(
            {
                "id": [1, 2, 3],
                "name": ["Alice", "Bob", "Charlie"],
                "amount": [100.50, 200.75, 300.25],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.csv"
            csv_format.write_to_file(test_data, file_path)

            # Verify file was created and has correct content
            assert file_path.exists()
            loaded_data = pd.read_csv(file_path)
            pd.testing.assert_frame_equal(loaded_data, test_data)

    def test_write_to_file_with_custom_delimiter(self) -> None:
        """Test writing dataframe with custom delimiter."""
        csv_format = CSVSourceFormat(delimiter="|")
        test_data = pd.DataFrame(
            {
                "col1": ["a", "b"],
                "col2": [1, 2],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test_pipe.csv"
            csv_format.write_to_file(test_data, file_path)

            # Verify file has pipe delimiter
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
                assert "|" in content
                assert "," not in content.split("\n")[1]  # Not in data rows


class TestXMLSourceFormat:
    """Test XML source format generator."""

    def test_initialization(self) -> None:
        """Test XML format initialization."""
        xml_format = XMLSourceFormat()
        assert xml_format.root_element == "data"
        assert xml_format.record_element == "record"

    def test_initialization_with_custom_params(self) -> None:
        """Test XML format initialization with custom parameters."""
        xml_format = XMLSourceFormat(root_element="employees", record_element="employee")
        assert xml_format.root_element == "employees"
        assert xml_format.record_element == "employee"

    def test_generate_data_returns_string(self) -> None:
        """Test that generate_data returns a file path string."""
        xml_format = XMLSourceFormat()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = xml_format.generate_data(
                "Employee",
                100,
                scale_factor=0.2,
                output_dir=Path(tmpdir),
            )
            assert isinstance(result, str)

    def test_write_to_file(self) -> None:
        """Test writing dataframe to XML file."""
        xml_format = XMLSourceFormat(root_element="employees", record_element="employee")
        test_data = pd.DataFrame(
            {
                "id": [1, 2],
                "name": ["Alice", "Bob"],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.xml"
            xml_format.write_to_file(test_data, file_path)

            # Verify file was created and is well-formed XML
            assert file_path.exists()
            tree = ET.parse(file_path)
            root = tree.getroot()

            # Verify root element and record elements
            assert root.tag == "employees"
            records = root.findall("employee")
            assert len(records) == len(test_data)


class TestFixedWidthSourceFormat:
    """Test fixed-width source format generator."""

    def test_initialization(self) -> None:
        """Test fixed-width format initialization."""
        field_widths = {"id": 10, "name": 20, "amount": 15}
        fw_format = FixedWidthSourceFormat(field_widths=field_widths)
        assert fw_format.field_widths == field_widths
        assert fw_format.fill_char == " "

    def test_initialization_with_custom_fill_char(self) -> None:
        """Test fixed-width format initialization with custom fill character."""
        fw_format = FixedWidthSourceFormat(field_widths={}, fill_char="0")
        assert fw_format.fill_char == "0"

    def test_generate_data_returns_string(self) -> None:
        """Test that generate_data returns a file path string."""
        fw_format = FixedWidthSourceFormat(field_widths={})
        with tempfile.TemporaryDirectory() as tmpdir:
            result = fw_format.generate_data(
                "Company",
                500,
                scale_factor=0.5,
                output_dir=Path(tmpdir),
            )
            assert isinstance(result, str)

    def test_write_to_file(self) -> None:
        """Test writing dataframe to fixed-width file."""
        field_widths = {"id": 5, "name": 10, "amount": 8}
        fw_format = FixedWidthSourceFormat(field_widths=field_widths)
        test_data = pd.DataFrame(
            {
                "id": [1, 2],
                "name": ["Alice", "Bob"],
                "amount": [100.5, 200.75],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            fw_format.write_to_file(test_data, file_path)

            # Verify file was created
            assert file_path.exists()

            # Verify fixed-width formatting
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()
                # Each line should have length = sum of field widths
                expected_length = sum(field_widths.values())
                for line in lines:
                    assert len(line.rstrip("\n")) == expected_length

    def test_write_to_file_with_custom_fill_char(self) -> None:
        """Test writing fixed-width file with custom fill character."""
        field_widths = {"col1": 10}
        fw_format = FixedWidthSourceFormat(field_widths=field_widths, fill_char="_")
        test_data = pd.DataFrame({"col1": ["test"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test_fill.txt"
            fw_format.write_to_file(test_data, file_path)

            with open(file_path, encoding="utf-8") as f:
                content = f.read()
                assert "_" in content  # Should have padding with underscores


class TestPipeDelimitedSourceFormat:
    """Test pipe-delimited source format generator."""

    def test_initialization(self) -> None:
        """Test pipe-delimited format initialization."""
        pipe_format = PipeDelimitedSourceFormat()
        assert pipe_format.delimiter == "|"
        assert pipe_format.escape_char == "\\"
        assert pipe_format.null_representation == ""

    def test_initialization_with_custom_params(self) -> None:
        """Test pipe-delimited format initialization with custom parameters."""
        pipe_format = PipeDelimitedSourceFormat(escape_char="^", null_representation="NULL")
        assert pipe_format.escape_char == "^"
        assert pipe_format.null_representation == "NULL"

    def test_generate_data_returns_string(self) -> None:
        """Test that generate_data returns a file path string."""
        pipe_format = PipeDelimitedSourceFormat()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = pipe_format.generate_data(
                "Trade",
                1000,
                scale_factor=0.02,
                output_dir=Path(tmpdir),
            )
            assert isinstance(result, str)

    def test_write_to_file(self) -> None:
        """Test writing dataframe to pipe-delimited file."""
        pipe_format = PipeDelimitedSourceFormat()
        test_data = pd.DataFrame(
            {
                "id": [1, 2, 3],
                "name": ["Alice", "Bob", "Charlie"],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            pipe_format.write_to_file(test_data, file_path)

            # Verify file was created
            assert file_path.exists()

            # Verify pipe delimiter
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
                assert "|" in content

    def test_write_to_file_handles_null_values(self) -> None:
        """Test writing pipe-delimited file with null values."""
        pipe_format = PipeDelimitedSourceFormat(null_representation="NULL")
        test_data = pd.DataFrame(
            {
                "col1": [1, None, 3],
                "col2": ["a", "b", None],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test_null.txt"
            pipe_format.write_to_file(test_data, file_path)

            with open(file_path, encoding="utf-8") as f:
                content = f.read()
                assert "NULL" in content


class TestSourceDataGenerator:
    """Test main source data generator."""

    def test_initialization(self) -> None:
        """Test source data generator initialization."""
        generator = SourceDataGenerator(scale_factor=2.0, seed=42)
        assert generator.scale_factor == 2.0
        assert generator.seed == 42
        assert len(generator.formats) == 4  # csv, xml, fixed_width, pipe

    def test_default_formats_registered(self) -> None:
        """Test that default formats are registered."""
        generator = SourceDataGenerator()
        assert "csv" in generator.formats
        assert "xml" in generator.formats
        assert "fixed_width" in generator.formats
        assert "pipe" in generator.formats

    def test_register_format(self) -> None:
        """Test registering a new format."""
        generator = SourceDataGenerator()
        custom_format = CSVSourceFormat(delimiter=";")
        generator.register_format("custom_csv", custom_format)
        assert "custom_csv" in generator.formats
        assert generator.formats["custom_csv"] == custom_format

    def test_generate_historical_data(self) -> None:
        """Test generating historical data."""
        generator = SourceDataGenerator(scale_factor=0.01)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generator.generate_historical_data("csv", Path(tmpdir))
            assert isinstance(result, dict)
            assert len(result) > 0
            # Verify paths are Path objects
            for _key, path in result.items():
                assert isinstance(path, Path)

    def test_generate_incremental_data(self) -> None:
        """Test generating incremental data."""
        generator = SourceDataGenerator(scale_factor=0.01)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generator.generate_incremental_data("csv", Path(tmpdir), batch_number=2)
            assert isinstance(result, dict)
            assert len(result) > 0
            # Verify batch number in keys
            for key in result:
                assert "batch2" in key

    def test_generate_customer_management_data(self) -> None:
        """Test generating customer management data."""
        generator = SourceDataGenerator(scale_factor=0.01)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generator.generate_customer_management_data("csv", Path(tmpdir), batch_number=1)
            assert isinstance(result, Path)

    def test_generate_daily_market_data(self) -> None:
        """Test generating daily market data."""
        generator = SourceDataGenerator(scale_factor=0.01)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generator.generate_daily_market_data("csv", Path(tmpdir), batch_date="2023-01-15")
            assert isinstance(result, Path)

    def test_get_data_statistics_before_generation(self) -> None:
        """Test getting statistics before data generation."""
        generator = SourceDataGenerator(scale_factor=1.5, seed=123)
        stats = generator.get_data_statistics()
        assert stats["scale_factor"] == 1.5
        assert stats["status"] == "not_generated"

    def test_get_data_statistics_after_generation(self) -> None:
        """Test getting statistics after data generation."""
        generator = SourceDataGenerator(scale_factor=0.01)
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate some data
            generator.generate_historical_data("csv", Path(tmpdir))
            stats = generator.get_data_statistics()
            assert stats["scale_factor"] == 0.01
            assert stats["status"] == "generated"
            assert "registered_formats" in stats
            assert len(stats["registered_formats"]) == 4
            assert "file_formats" in stats
