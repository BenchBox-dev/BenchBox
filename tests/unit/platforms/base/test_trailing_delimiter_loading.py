"""Regression tests for trailing delimiter handling in DuckDB pipe-delimited loader.

Tests that DuckDBNativeHandler.load_table() correctly handles both:
- Files WITH trailing delimiters (TPC-H .tbl format)
- Files WITHOUT trailing delimiters (newer TPC-DS .dat format)

Also tests CLI exit code propagation on benchmark failure.
"""

import sys
import sys as _sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.base.data_loading import DuckDBNativeHandler

# benchbox.cli.commands.__init__ re-exports `run` (a Click Command) under the
# same name as the run submodule.  On Python 3.10 mock's string-based patch()
# resolves the target via getattr(benchbox.cli.commands, "run"), which returns
# the Command object, not the submodule.  Seeding sys.modules here via
# __import__ and using patch.object() avoids the ambiguity on all Python
# versions.
__import__("benchbox.cli.commands.run")
_run_module = _sys.modules["benchbox.cli.commands.run"]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_pipe_file(tmp_path: Path, filename: str, lines: list[str]) -> Path:
    """Write pipe-delimited lines to a file."""
    file_path = tmp_path / filename
    file_path.write_text("\n".join(lines) + "\n")
    return file_path


def _make_handler() -> DuckDBNativeHandler:
    """Create a DuckDBNativeHandler with pipe delimiter."""
    adapter = Mock()
    adapter.dry_run_mode = False
    benchmark = Mock(spec=[])
    return DuckDBNativeHandler(delimiter="|", adapter=adapter, benchmark=benchmark)


def _make_connection(col_names: list[str], row_count: int = 3) -> Mock:
    """Create a mock DuckDB connection that returns schema info.

    Call sequence for pipe-delimited tables:
      [0] pragma_table_info  -> fetchall -> col_names
      [1] COUNT(*) before    -> fetchone -> (0,)           (empty table)
      [2] INSERT             -> no fetch
      [3] COUNT(*) after     -> fetchone -> (row_count,)
    """
    connection = Mock()

    pragma_result = Mock()
    pragma_result.fetchall.return_value = [(name,) for name in col_names]

    before_result = Mock()
    before_result.fetchone.return_value = (0,)

    insert_result = Mock()

    after_result = Mock()
    after_result.fetchone.return_value = (row_count,)

    connection.execute.side_effect = [pragma_result, before_result, insert_result, after_result]
    return connection


class TestTrailingDelimiterWithPipe:
    """Test pipe-delimited loading with and without trailing delimiters."""

    def test_load_with_trailing_delimiter(self, tmp_path):
        """Files WITH trailing pipe (TPC-H style) should add dummy column and project schema cols."""
        col_names = ["r_regionkey", "r_name", "r_comment"]
        # TPC-H region.tbl format: trailing pipe after last field
        data_file = _make_pipe_file(
            tmp_path,
            "region.tbl",
            [
                "0|AFRICA|special deposits|",
                "1|AMERICA|furiously even|",
                "2|ASIA|carefully regular|",
            ],
        )

        handler = _make_handler()
        connection = _make_connection(col_names)

        result = handler.load_table("region", data_file, connection, Mock(), Mock())

        assert result == 3
        # Verify the INSERT SQL was executed
        calls = connection.execute.call_args_list
        # Call sequence: [0] pragma_table_info, [1] COUNT(*) before, [2] INSERT, [3] COUNT(*) after
        insert_call = calls[2][0][0]
        # Should project explicit columns, not SELECT *
        assert '"r_regionkey"' in insert_call
        assert '"r_name"' in insert_call
        assert '"r_comment"' in insert_call
        assert "SELECT *" not in insert_call
        # Should include dummy column in names parameter
        assert "_trailing_delimiter_" in insert_call
        # Should keep null_padding
        assert "null_padding=true" in insert_call

    def test_load_without_trailing_delimiter(self, tmp_path):
        """Files WITHOUT trailing pipe (newer TPC-DS style) should NOT add dummy column."""
        col_names = ["t_time_sk", "t_time_id", "t_time"]
        # TPC-DS newer format: no trailing pipe
        data_file = _make_pipe_file(
            tmp_path,
            "time_dim.dat",
            [
                "0|AAAAAAAABAAAAAAA|0",
                "1|AAAAAAAACAAAAAAA|1",
                "2|AAAAAAAADAAAAAAA|2",
            ],
        )

        handler = _make_handler()
        connection = _make_connection(col_names)

        result = handler.load_table("time_dim", data_file, connection, Mock(), Mock())

        assert result == 3
        calls = connection.execute.call_args_list
        insert_call = calls[2][0][0]
        # Should project explicit columns
        assert '"t_time_sk"' in insert_call
        assert '"t_time_id"' in insert_call
        assert '"t_time"' in insert_call
        assert "SELECT *" not in insert_call
        # Should NOT include dummy column
        assert "_trailing_delimiter_" not in insert_call
        # Should still keep null_padding for safety
        assert "null_padding=true" in insert_call

    def test_load_without_trailing_no_binder_error(self, tmp_path):
        """Confirm the exact regression: no _trailing_delimiter_ in EXCLUDE clause."""
        col_names = ["ws_sold_date_sk", "ws_item_sk", "ws_order_number"]
        data_file = _make_pipe_file(
            tmp_path,
            "web_sales.dat",
            [
                "2450816|1234|5678",
                "2450817|2345|6789",
            ],
        )

        handler = _make_handler()
        connection = _make_connection(col_names, row_count=2)

        handler.load_table("web_sales", data_file, connection, Mock(), Mock())

        calls = connection.execute.call_args_list
        insert_call = calls[2][0][0]
        # The regression was: SELECT * EXCLUDE (_trailing_delimiter_) failed
        # when the column didn't exist. Verify EXCLUDE is never used.
        assert "EXCLUDE" not in insert_call

    def test_load_zst_compressed_without_trailing(self, tmp_path):
        """Compressed .dat.zst files without trailing delimiter should work.

        Creates a real zstd-compressed file and verifies has_trailing_delimiter
        correctly reads through the compression layer.
        """
        col_names = ["ss_sold_date_sk", "ss_item_sk"]
        lines = "2450816|1234\n2450817|2345\n"

        # Write a real zstd-compressed file
        zst_path = tmp_path / "store_sales_1_2.dat.zst"
        try:
            import zstandard as zstd

            cctx = zstd.ZstdCompressor()
            zst_path.write_bytes(cctx.compress(lines.encode()))
        except ImportError:
            pytest.skip("zstandard not installed")

        handler = _make_handler()
        connection = _make_connection(col_names, row_count=2)

        result = handler.load_table("store_sales", zst_path, connection, Mock(), Mock())

        assert result == 2
        calls = connection.execute.call_args_list
        insert_call = calls[2][0][0]
        assert "_trailing_delimiter_" not in insert_call
        assert '"ss_sold_date_sk"' in insert_call

    def test_fallback_when_no_columns_detected(self, tmp_path):
        """When pragma_table_info returns empty, fall back to auto_detect."""
        data_file = _make_pipe_file(tmp_path, "unknown.dat", ["a|b|c"])

        handler = _make_handler()
        connection = Mock()

        # Sequence: [0] pragma (fetchall=[]), [1] COUNT before, [2] INSERT, [3] COUNT after
        pragma_result = Mock()
        pragma_result.fetchall.return_value = []

        before_result = Mock()
        before_result.fetchone.return_value = (0,)

        insert_result = Mock()

        after_result = Mock()
        after_result.fetchone.return_value = (1,)

        connection.execute.side_effect = [pragma_result, before_result, insert_result, after_result]

        handler.load_table("unknown_table", data_file, connection, Mock(), Mock())

        calls = connection.execute.call_args_list
        insert_call = calls[2][0][0]
        assert "auto_detect=true" in insert_call
        assert "SELECT *" in insert_call

    def test_multishard_row_count_not_inflated(self, tmp_path):
        """Multi-shard loading must return per-shard row counts, not cumulative totals.

        Regression test for the triangular-series inflation bug where load_table()
        queried COUNT(*) of the whole table after each shard insert. With N shards
        the caller summed 1+2+...+N rows instead of the actual N*rows_per_shard.

        With the before/after fix each call returns only the rows it inserted.
        """
        col_names = ["o_orderkey", "o_custkey", "o_orderstatus"]
        handler = _make_handler()

        # Simulate loading 3 shards into the same table.
        # The table grows: 0->500->1000->1500.
        shard_rows = 500
        table_counts = [0, 500, 1000, 1500]

        total = 0
        for i, (before_count, after_count) in enumerate(zip(table_counts, table_counts[1:])):
            shard_file = _make_pipe_file(
                tmp_path,
                f"orders.tbl.{i + 1}",
                [f"{j}|{j}|O" for j in range(shard_rows)],
            )

            # Wire the mock for this shard's call sequence.
            pragma_result = Mock()
            pragma_result.fetchall.return_value = [(name,) for name in col_names]

            before_result = Mock()
            before_result.fetchone.return_value = (before_count,)

            insert_result = Mock()

            after_result = Mock()
            after_result.fetchone.return_value = (after_count,)

            connection = Mock()
            connection.execute.side_effect = [pragma_result, before_result, insert_result, after_result]

            rows = handler.load_table("orders", shard_file, connection, Mock(), Mock())
            assert rows == shard_rows, f"Shard {i + 1}: expected {shard_rows}, got {rows}"
            total += rows

        assert total == 1500, f"Total rows should be 1500, got {total}"


class TestDuckDBNativeHandlerBulk:
    """Tests for DuckDBNativeHandler.load_table_bulk() multi-file array syntax."""

    def _make_bulk_connection(self, col_names: list[str], total_rows: int) -> Mock:
        """Mock connection for a single bulk-load call.

        Call sequence: [0] pragma, [1] COUNT before, [2] bulk INSERT, [3] COUNT after
        """
        connection = Mock()

        pragma_result = Mock()
        pragma_result.fetchall.return_value = [(name,) for name in col_names]

        before_result = Mock()
        before_result.fetchone.return_value = (0,)

        insert_result = Mock()

        after_result = Mock()
        after_result.fetchone.return_value = (total_rows,)

        connection.execute.side_effect = [pragma_result, before_result, insert_result, after_result]
        return connection

    def test_bulk_load_trailing_delimiter_uses_array_syntax(self, tmp_path):
        """3 shards with trailing delimiter must produce a single read_csv([array]) INSERT."""
        col_names = ["l_orderkey", "l_partkey", "l_suppkey"]
        shards = [_make_pipe_file(tmp_path, f"lineitem.tbl.{i}", [f"{i}|{i}|{i}|"]) for i in range(1, 4)]

        handler = _make_handler()
        connection = self._make_bulk_connection(col_names, total_rows=3000)

        result = handler.load_table_bulk("lineitem", shards, connection, Mock(), Mock())

        assert result == 3000
        # Single INSERT call only (after pragma + COUNT_before)
        calls = connection.execute.call_args_list
        assert connection.execute.call_count == 4  # pragma, COUNT_before, INSERT, COUNT_after
        insert_sql = calls[2][0][0]
        # Must use array syntax: read_csv([...])
        assert "read_csv([" in insert_sql
        # All shard paths present
        for shard in shards:
            assert str(shard) in insert_sql
        # Schema columns projected
        for col in col_names:
            assert f'"{col}"' in insert_sql
        # Trailing delimiter dummy column
        assert "_trailing_delimiter_" in insert_sql

    def test_bulk_load_no_trailing_delimiter_uses_array_syntax(self, tmp_path):
        """3 shards without trailing delimiter must produce array SQL without dummy column."""
        col_names = ["t_time_sk", "t_time_id", "t_time"]
        shards = [_make_pipe_file(tmp_path, f"time_dim.dat.{i}", [f"{i}|AAAA|{i}"]) for i in range(1, 4)]

        handler = _make_handler()
        connection = self._make_bulk_connection(col_names, total_rows=1500)

        result = handler.load_table_bulk("time_dim", shards, connection, Mock(), Mock())

        assert result == 1500
        calls = connection.execute.call_args_list
        insert_sql = calls[2][0][0]
        assert "read_csv([" in insert_sql
        assert "_trailing_delimiter_" not in insert_sql
        for col in col_names:
            assert f'"{col}"' in insert_sql

    def test_bulk_load_dry_run_captures_sql_and_returns_placeholder(self, tmp_path):
        """Dry-run mode must capture SQL and return 1000 * N without executing."""
        col_names = ["o_orderkey", "o_custkey"]
        shards = [_make_pipe_file(tmp_path, f"orders.tbl.{i}", [f"{i}|{i}|"]) for i in range(1, 4)]

        adapter = Mock()
        adapter.dry_run_mode = True
        adapter.capture_sql = Mock()
        benchmark = Mock(spec=[])
        handler = DuckDBNativeHandler(delimiter="|", adapter=adapter, benchmark=benchmark)

        connection = Mock()
        pragma_result = Mock()
        pragma_result.fetchall.return_value = [(c,) for c in col_names]
        connection.execute.return_value = pragma_result

        result = handler.load_table_bulk("orders", shards, connection, Mock(), Mock())

        assert result == 3000
        adapter.capture_sql.assert_called_once()
        # No COUNT or INSERT executed on real connection
        assert connection.execute.call_count == 1  # only pragma

    def test_bulk_load_single_shard_delegates_to_load_table(self, tmp_path):
        """Single-element list must produce same result as load_table()."""
        col_names = ["r_regionkey", "r_name", "r_comment"]
        shard = _make_pipe_file(tmp_path, "region.tbl", ["0|AFRICA|desc|"])

        handler = _make_handler()
        connection = self._make_bulk_connection(col_names, total_rows=5)

        result = handler.load_table_bulk("region", [shard], connection, Mock(), Mock())

        assert result == 5


class TestCLIExitCodeOnFailure:
    """Test that benchbox run returns non-zero exit code on failure."""

    def test_run_command_exits_nonzero_on_bad_platform(self):
        """An unrecognized platform should cause a non-zero exit."""
        from click.testing import CliRunner

        from benchbox.cli.commands.run import run

        runner = CliRunner()
        result = runner.invoke(run, ["--platform", "nonexistent_platform", "--benchmark", "tpch", "--non-interactive"])
        assert result.exit_code != 0

    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="Click command mock.patch requires Python 3.11+ for attribute access",
    )
    def test_run_command_exits_nonzero_on_failed_validation_status(self):
        """The run CLI must call ctx.exit(1) when result.validation_status is FAILED.

        Mocks _execute_orchestrated_run to return a FAILED result and verifies
        the CLI propagates a non-zero exit code. Invokes through the cli group
        so ctx.obj is properly initialized.
        """
        from click.testing import CliRunner

        from benchbox.cli.app import cli

        # Build a minimal mock result with FAILED status
        mock_result = Mock()
        mock_result.validation_status = "FAILED"
        mock_result.validation_details = "Simulated failure"

        runner = CliRunner()
        with patch.object(_run_module, "_execute_orchestrated_run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["run", "--platform", "duckdb", "--benchmark", "tpch", "--non-interactive", "--phases", "power"],
            )
        # The FAILED path should trigger ctx.exit(1)
        assert result.exit_code != 0, f"Expected non-zero exit but got {result.exit_code}. Output:\n{result.output}"

    def test_run_command_exits_zero_on_help(self):
        """Sanity check: --help should exit 0."""
        from click.testing import CliRunner

        from benchbox.cli.commands.run import run

        runner = CliRunner()
        result = runner.invoke(run, ["--help"])
        assert result.exit_code == 0
