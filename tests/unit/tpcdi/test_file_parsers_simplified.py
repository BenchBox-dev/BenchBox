"""Tests for simplified TPC-DI file parsers.

This module tests the file parsing functionality including:
- ParseResult data structure
- CSV and pipe-delimited parsers
- Fixed-width file parsers
- XML parsers
- Multi-format parser capabilities
- Error handling and validation

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


pytest.importorskip("pandas")
import pandas as pd

from benchbox.core.tpcdi.tools.file_parsers import (
    CSVParser,
    FixedWidthParser,
    MultiFormatParser,
    ParseResult,
    PipeDelimitedParser,
    XMLParser,
    parse_csv_file,
    parse_fixed_width_file,
    parse_pipe_delimited_file,
    parse_xml_file,
)


@pytest.mark.unit
@pytest.mark.tpcdi
class TestParseResult:
    """Test ParseResult data structure."""

    def test_parse_result_creation(self):
        """Test ParseResult creation."""
        data = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
        errors = ["Error 1", "Error 2"]
        schema_info = {"columns": ["col1", "col2"], "types": ["int", "str"]}
        quality_metrics = {"completeness": 0.95, "accuracy": 0.98}

        result = ParseResult(
            data=data,
            records_parsed=3,
            records_skipped=2,
            parsing_errors=errors,
            schema_info=schema_info,
            quality_metrics=quality_metrics,
        )

        assert result.records_parsed == 3
        assert result.records_skipped == 2
        assert result.parsing_errors == errors
        assert result.schema_info == schema_info
        assert result.quality_metrics == quality_metrics
        assert pd.testing.assert_frame_equal(result.data, data) is None

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        result = ParseResult(
            data=pd.DataFrame(),
            records_parsed=80,
            records_skipped=20,
        )

        assert result.success_rate == 0.8

        # Test edge case with no records
        empty_result = ParseResult(
            data=pd.DataFrame(),
            records_parsed=0,
            records_skipped=0,
        )
        assert empty_result.success_rate == 0.0

    def test_has_errors_property(self):
        """Test has_errors property."""
        # Result with parsing errors
        result_with_errors = ParseResult(
            data=pd.DataFrame(),
            records_parsed=5,
            parsing_errors=["Error 1"],
        )
        assert result_with_errors.has_errors is True

        # Result with skipped records
        result_with_skipped = ParseResult(
            data=pd.DataFrame(),
            records_parsed=5,
            records_skipped=2,
        )
        assert result_with_skipped.has_errors is True

        # Clean result
        clean_result = ParseResult(
            data=pd.DataFrame(),
            records_parsed=5,
        )
        assert clean_result.has_errors is False


@pytest.mark.unit
@pytest.mark.tpcdi
class TestCSVParser:
    """Test CSV parser functionality."""

    def test_csv_parser_creation(self):
        """Test CSV parser creation with default parameters."""
        parser = CSVParser()

        assert parser.delimiter == ","
        assert parser.quote_char == '"'
        assert parser.escape_char is None
        assert parser.encoding is None
        assert parser.skip_blank_lines is True
        assert parser.header_row == 0

    def test_csv_parser_with_custom_parameters(self):
        """Test CSV parser with custom parameters."""
        parser = CSVParser(
            delimiter=";",
            quote_char="'",
            escape_char="\\",
            encoding="utf-8",
            skip_blank_lines=False,
            header_row=1,
            expected_columns=["col1", "col2"],
            dtype_mapping={"col1": "int64"},
        )

        assert parser.delimiter == ";"
        assert parser.quote_char == "'"
        assert parser.escape_char == "\\"
        assert parser.encoding == "utf-8"
        assert parser.skip_blank_lines is False
        assert parser.header_row == 1
        assert parser.expected_columns == ["col1", "col2"]
        assert parser.dtype_mapping == {"col1": "int64"}

    def test_csv_parse_simple_file(self):
        """Test parsing a simple CSV file."""
        csv_content = "id,name,value\n1,Alice,100\n2,Bob,200\n3,Charlie,300"

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8") as f:
            f.write(csv_content)
            temp_file = Path(f.name)

        try:
            parser = CSVParser()
            result = parser.parse_file(temp_file)

            assert result.records_parsed == 3
            assert result.records_skipped == 0
            assert len(result.parsing_errors) == 0
            assert list(result.data.columns) == ["id", "name", "value"]
            assert result.data.iloc[0]["name"] == "Alice"
            assert result.data.iloc[2]["value"] == 300

        finally:
            temp_file.unlink()

    def test_csv_parse_with_missing_columns(self):
        """Test parsing CSV with missing expected columns."""
        csv_content = "id,name\n1,Alice\n2,Bob"

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8") as f:
            f.write(csv_content)
            temp_file = Path(f.name)

        try:
            parser = CSVParser(expected_columns=["id", "name", "age"])

            with patch.object(parser.logger, "warning") as mock_warning:
                result = parser.parse_file(temp_file)
                mock_warning.assert_called_once()

            assert result.records_parsed == 2
            assert result.records_skipped == 0

        finally:
            temp_file.unlink()

    def test_csv_parse_invalid_file(self):
        """Test parsing nonexistent CSV file."""
        invalid_file = Path("nonexistent_file.csv")
        parser = CSVParser()

        result = parser.parse_file(invalid_file)

        assert result.records_parsed == 0
        assert result.records_skipped == 0
        assert len(result.parsing_errors) > 0
        assert result.data.empty


@pytest.mark.unit
@pytest.mark.tpcdi
class TestPipeDelimitedParser:
    """Test pipe-delimited parser functionality."""

    def test_pipe_parser_creation(self):
        """Test pipe-delimited parser creation."""
        parser = PipeDelimitedParser()
        assert parser.delimiter == "|"

    def test_pipe_parse_file(self):
        """Test parsing a pipe-delimited file."""
        pipe_content = "id|name|value\n1|Alice|100\n2|Bob|200"

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write(pipe_content)
            temp_file = Path(f.name)

        try:
            parser = PipeDelimitedParser()
            result = parser.parse_file(temp_file)

            assert result.records_parsed == 2
            assert list(result.data.columns) == ["id", "name", "value"]
            assert result.data.iloc[0]["name"] == "Alice"

        finally:
            temp_file.unlink()


@pytest.mark.unit
@pytest.mark.tpcdi
class TestFixedWidthParser:
    """Test fixed-width parser functionality."""

    def test_fixed_width_parser_creation(self):
        """Test fixed-width parser creation."""
        field_specs = [("id", 0, 5), ("name", 5, 10), ("value", 15, 8)]
        parser = FixedWidthParser(field_specs)

        assert parser.field_specifications == field_specs
        assert parser.encoding is None
        assert parser.skip_blank_lines is True
        assert parser.header_lines == 0

    def test_fixed_width_parse_file(self):
        """Test parsing a fixed-width file."""
        # Fixed width content: ID(5) NAME(10) VALUE(8)
        fw_content = "00001Alice     00000100\n00002Bob       00000200\n00003Charlie   00000300"

        field_specs = [("id", 0, 5), ("name", 5, 10), ("value", 15, 8)]

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write(fw_content)
            temp_file = Path(f.name)

        try:
            parser = FixedWidthParser(field_specs)
            result = parser.parse_file(temp_file)

            assert result.records_parsed == 3
            assert list(result.data.columns) == ["id", "name", "value"]
            assert str(result.data.iloc[0]["id"]).strip() == "1"  # pandas may convert to int
            assert result.data.iloc[1]["name"].strip() == "Bob"

        finally:
            temp_file.unlink()

    def test_fixed_width_parse_invalid_file(self):
        """Test parsing nonexistent fixed-width file."""
        field_specs = [("id", 0, 5), ("name", 5, 10)]
        parser = FixedWidthParser(field_specs)
        invalid_file = Path("nonexistent_file.txt")

        result = parser.parse_file(invalid_file)

        assert result.records_parsed == 0
        assert len(result.parsing_errors) > 0
        assert result.data.empty


@pytest.mark.unit
@pytest.mark.tpcdi
class TestXMLParser:
    """Test XML parser functionality."""

    def test_xml_parser_creation(self):
        """Test XML parser creation."""
        parser = XMLParser(
            record_tag="record",
            field_mappings={"name": "person_name"},
            attribute_mappings={"id": "record_id"},
        )

        assert parser.record_tag == "record"
        assert parser.field_mappings == {"name": "person_name"}
        assert parser.attribute_mappings == {"id": "record_id"}

    def test_xml_parse_simple_file(self):
        """Test parsing a simple XML file."""
        xml_content = """<?xml version="1.0"?>
        <root>
            <record id="1">
                <name>Alice</name>
                <value>100</value>
            </record>
            <record id="2">
                <name>Bob</name>
                <value>200</value>
            </record>
        </root>"""

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml", encoding="utf-8") as f:
            f.write(xml_content)
            temp_file = Path(f.name)

        try:
            parser = XMLParser(
                record_tag="record",
                attribute_mappings={"id": "record_id"},
            )
            result = parser.parse_file(temp_file)

            assert result.records_parsed == 2
            assert "record_id" in result.data.columns
            assert "name" in result.data.columns
            assert "value" in result.data.columns
            assert result.data.iloc[0]["name"] == "Alice"
            assert result.data.iloc[1]["record_id"] == "2"

        finally:
            temp_file.unlink()

    def test_xml_parse_with_errors(self):
        """Test XML parsing with malformed elements."""
        xml_content = """<?xml version="1.0"?>
        <root>
            <record id="1">
                <name>Alice</name>
                <value>100</value>
            </record>
            <!-- This record is intentionally malformed -->
            <record id="2">
                <name>Bob</name>
                <invalid></invalid>
            </record>
        </root>"""

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml", encoding="utf-8") as f:
            f.write(xml_content)
            temp_file = Path(f.name)

        try:
            parser = XMLParser(record_tag="record", attribute_mappings={"id": "record_id"})
            result = parser.parse_file(temp_file)

            # Should still parse successfully despite the empty element
            assert result.records_parsed == 2
            assert result.records_skipped == 0

        finally:
            temp_file.unlink()

    def test_xml_parse_invalid_file(self):
        """Test parsing invalid XML file."""
        parser = XMLParser(record_tag="record")
        invalid_file = Path("nonexistent_file.xml")

        result = parser.parse_file(invalid_file)

        assert result.records_parsed == 0
        assert len(result.parsing_errors) > 0
        assert result.data.empty


@pytest.mark.unit
@pytest.mark.tpcdi
class TestMultiFormatParser:
    """Test multi-format parser functionality."""

    def test_multi_format_parser_creation(self):
        """Test multi-format parser creation."""
        parser = MultiFormatParser()
        assert hasattr(parser, "_parsers")
        assert ".csv" in parser._parsers
        assert ".xml" in parser._parsers

    def test_get_parser_for_csv(self):
        """Test getting CSV parser."""
        multi_parser = MultiFormatParser()
        csv_file = Path("test.csv")

        parser = multi_parser.get_parser(csv_file)
        assert isinstance(parser, CSVParser)

    def test_get_parser_for_xml(self):
        """Test getting XML parser."""
        multi_parser = MultiFormatParser()
        xml_file = Path("test.xml")

        parser = multi_parser.get_parser(xml_file, {"record_tag": "record"})
        assert isinstance(parser, XMLParser)

    def test_get_parser_unsupported_format(self):
        """Test getting parser for unsupported format."""
        multi_parser = MultiFormatParser()
        unsupported_file = Path("test.json")

        with pytest.raises(ValueError, match="Unsupported file format"):
            multi_parser.get_parser(unsupported_file)

    def test_parse_file_integration(self):
        """Test multi-format parser integration."""
        csv_content = "id,name\n1,Alice\n2,Bob"

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8") as f:
            f.write(csv_content)
            temp_file = Path(f.name)

        try:
            multi_parser = MultiFormatParser()
            result = multi_parser.parse_file(temp_file)

            assert result.records_parsed == 2
            assert list(result.data.columns) == ["id", "name"]

        finally:
            temp_file.unlink()


@pytest.mark.unit
@pytest.mark.tpcdi
class TestConvenienceFunctions:
    """Test convenience parsing functions."""

    def test_parse_csv_file_function(self):
        """Test parse_csv_file convenience function."""
        csv_content = "id,name\n1,Alice\n2,Bob"

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8") as f:
            f.write(csv_content)
            temp_file = Path(f.name)

        try:
            result = parse_csv_file(temp_file)
            assert result.records_parsed == 2
            assert list(result.data.columns) == ["id", "name"]

        finally:
            temp_file.unlink()

    def test_parse_pipe_delimited_file_function(self):
        """Test parse_pipe_delimited_file convenience function."""
        pipe_content = "id|name\n1|Alice\n2|Bob"

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write(pipe_content)
            temp_file = Path(f.name)

        try:
            result = parse_pipe_delimited_file(temp_file)
            assert result.records_parsed == 2
            assert list(result.data.columns) == ["id", "name"]

        finally:
            temp_file.unlink()

    def test_parse_fixed_width_file_function(self):
        """Test parse_fixed_width_file convenience function."""
        fw_content = "00001Alice\n00002Bob  "
        field_specs = [("id", 0, 5), ("name", 5, 5)]

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write(fw_content)
            temp_file = Path(f.name)

        try:
            result = parse_fixed_width_file(temp_file, field_specs)
            assert result.records_parsed == 2
            assert list(result.data.columns) == ["id", "name"]

        finally:
            temp_file.unlink()

    def test_parse_xml_file_function(self):
        """Test parse_xml_file convenience function."""
        xml_content = """<?xml version="1.0"?>
        <root>
            <record>
                <id>1</id>
                <name>Alice</name>
            </record>
        </root>"""

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml", encoding="utf-8") as f:
            f.write(xml_content)
            temp_file = Path(f.name)

        try:
            result = parse_xml_file(temp_file, "record")
            assert result.records_parsed == 1
            assert "id" in result.data.columns
            assert "name" in result.data.columns

        finally:
            temp_file.unlink()


@pytest.mark.unit
@pytest.mark.tpcdi
class TestErrorHandling:
    """Test error handling across all parsers."""

    def test_csv_encoding_detection(self):
        """Test CSV encoding detection."""
        parser = CSVParser()

        # Test with non-existent file
        invalid_file = Path("nonexistent.csv")
        encoding = parser._detect_encoding(invalid_file)
        assert encoding == "utf-8"

    def test_xml_extract_record_data(self):
        """Test XML record data extraction."""
        parser = XMLParser(
            record_tag="record",
            field_mappings={"name": "person_name"},
            attribute_mappings={"id": "record_id"},
        )

        # Create a test XML element
        element = ET.Element("record", {"id": "123"})
        name_elem = ET.SubElement(element, "name")
        name_elem.text = "Alice"

        record = parser._extract_record_data(element)

        assert record["record_id"] == "123"
        assert record["person_name"] == "Alice"
