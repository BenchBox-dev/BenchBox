"""Tests for TPC-H streams module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from benchbox.core.tpch.streams import TPCHStreamRunner, TPCHStreams

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Permutation matrix tests
# ---------------------------------------------------------------------------
class TestPermutationMatrix:
    """Tests for the TPC-H permutation matrix."""

    def test_matrix_has_41_rows(self):
        assert len(TPCHStreams.PERMUTATION_MATRIX) == 41

    def test_each_row_has_22_queries(self):
        for i, row in enumerate(TPCHStreams.PERMUTATION_MATRIX):
            assert len(row) == 22, f"Row {i} has {len(row)} entries, expected 22"

    def test_each_row_is_permutation_of_1_to_22(self):
        """Every row must be a permutation of integers 1-22."""
        expected = set(range(1, 23))
        for i, row in enumerate(TPCHStreams.PERMUTATION_MATRIX):
            assert set(row) == expected, f"Row {i} is not a permutation of 1-22"

    def test_first_row_matches_spec(self):
        """Spot-check the first permutation row from the TPC-H spec."""
        expected = [14, 2, 9, 20, 6, 17, 18, 8, 21, 13, 3, 22, 16, 4, 11, 15, 1, 10, 19, 5, 7, 12]
        assert TPCHStreams.PERMUTATION_MATRIX[0] == expected

    def test_last_row_matches_spec(self):
        """Spot-check the last (41st) permutation row from the TPC-H spec."""
        expected = [13, 15, 17, 1, 22, 11, 3, 4, 7, 20, 14, 21, 9, 8, 2, 18, 16, 6, 10, 12, 5, 19]
        assert TPCHStreams.PERMUTATION_MATRIX[40] == expected


# ---------------------------------------------------------------------------
# Stream permutation retrieval
# ---------------------------------------------------------------------------
class TestGetStreamPermutation:
    """Tests for _get_stream_permutation."""

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_stream_0_returns_first_permutation(self, mock_templates):
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=1, verbose=0)
        perm = streams._get_stream_permutation(0)
        assert perm == TPCHStreams.PERMUTATION_MATRIX[0]

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_stream_permutation_wraps_around(self, mock_templates):
        """Stream IDs beyond 40 wrap around using modulo."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=100, verbose=0)

        # Stream 41 should wrap to index 0
        perm41 = streams._get_stream_permutation(41)
        perm0 = streams._get_stream_permutation(0)
        assert perm41 == perm0

        # Stream 82 should also wrap to index 0
        perm82 = streams._get_stream_permutation(82)
        assert perm82 == perm0

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_stream_permutation_returns_copy(self, mock_templates):
        """Returned list is a copy, not a reference."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=1, verbose=0)

        perm1 = streams._get_stream_permutation(0)
        perm2 = streams._get_stream_permutation(0)
        assert perm1 == perm2
        assert perm1 is not perm2

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_different_streams_different_permutations(self, mock_templates):
        """Different stream IDs produce different permutations."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=3, verbose=0)

        perm0 = streams._get_stream_permutation(0)
        perm1 = streams._get_stream_permutation(1)
        perm2 = streams._get_stream_permutation(2)
        assert perm0 != perm1
        assert perm1 != perm2

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_permutation_always_22_elements(self, mock_templates):
        """Every permutation has exactly 22 query IDs."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=50, verbose=0)

        for stream_id in range(50):
            perm = streams._get_stream_permutation(stream_id)
            assert len(perm) == 22


# ---------------------------------------------------------------------------
# TPCHStreams initialization
# ---------------------------------------------------------------------------
class TestTPCHStreamsInit:
    """Tests for TPCHStreams initialization."""

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_default_values(self, mock_templates):
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(verbose=0)

        assert streams.num_streams == 1
        assert streams.scale_factor == 1.0
        assert streams.rng_seed == 1
        assert streams.query_count == 22

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_custom_values(self, mock_templates):
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(
            num_streams=4,
            scale_factor=10.0,
            output_dir="/tmp/test_streams",
            rng_seed=42,
            verbose=0,
        )

        assert streams.num_streams == 4
        assert streams.scale_factor == 10.0
        assert streams.output_dir == Path("/tmp/test_streams")
        assert streams.rng_seed == 42

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_default_output_dir(self, mock_templates):
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(verbose=0)
        assert streams.output_dir == Path.cwd() / "tpch_streams"

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_none_seed_defaults_to_1(self, mock_templates):
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(rng_seed=None, verbose=0)
        assert streams.rng_seed == 1


# ---------------------------------------------------------------------------
# Stream info
# ---------------------------------------------------------------------------
class TestGetStreamInfo:
    """Tests for get_stream_info and get_all_streams_info."""

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_stream_info_structure(self, mock_templates):
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=3, scale_factor=2.0, rng_seed=10, verbose=0)

        info = streams.get_stream_info(0)
        assert info["stream_id"] == 0
        assert info["scale_factor"] == 2.0
        assert info["rng_seed"] == 10  # base_seed + stream_id = 10 + 0
        assert info["query_count"] == 22
        assert info["permutation_index"] == 0
        assert len(info["query_order"]) == 22
        assert info["output_file"] == streams.output_dir / "stream_0.sql"

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_stream_info_seed_per_stream(self, mock_templates):
        """Each stream gets rng_seed + stream_id as its seed."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=5, rng_seed=100, verbose=0)

        info0 = streams.get_stream_info(0)
        info3 = streams.get_stream_info(3)

        assert info0["rng_seed"] == 100
        assert info3["rng_seed"] == 103

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_stream_info_invalid_stream_id(self, mock_templates):
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=2, verbose=0)

        with pytest.raises(ValueError, match="Invalid stream ID"):
            streams.get_stream_info(2)

        with pytest.raises(ValueError, match="Invalid stream ID"):
            streams.get_stream_info(5)

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_get_all_streams_info(self, mock_templates):
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=3, verbose=0)

        all_info = streams.get_all_streams_info()
        assert len(all_info) == 3
        assert all_info[0]["stream_id"] == 0
        assert all_info[1]["stream_id"] == 1
        assert all_info[2]["stream_id"] == 2

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_stream_info_permutation_index_wraps(self, mock_templates):
        """permutation_index wraps at 41."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=50, verbose=0)

        info0 = streams.get_stream_info(0)
        info41 = streams.get_stream_info(41)
        assert info0["permutation_index"] == 0
        assert info41["permutation_index"] == 0

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_stream_info_query_order_matches_permutation(self, mock_templates):
        """query_order should match the correct permutation matrix row."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(num_streams=10, verbose=0)

        for sid in range(10):
            info = streams.get_stream_info(sid)
            expected_row = TPCHStreams.PERMUTATION_MATRIX[sid % 41]
            assert info["query_order"] == expected_row


# ---------------------------------------------------------------------------
# TPCHStreamRunner
# ---------------------------------------------------------------------------
class TestTPCHStreamRunner:
    """Tests for TPCHStreamRunner initialization."""

    def test_runner_initialization(self):
        runner = TPCHStreamRunner(
            connection_string="duckdb:///:memory:",
            dialect="standard",
            verbose=0,
        )
        assert runner.connection_string == "duckdb:///:memory:"
        assert runner.dialect == "standard"

    def test_runner_default_dialect(self):
        runner = TPCHStreamRunner(
            connection_string="test://conn",
            verbose=0,
        )
        assert runner.dialect == "standard"


# ---------------------------------------------------------------------------
# Run stream (with mock file)
# ---------------------------------------------------------------------------
class TestRunStream:
    """Tests for TPCHStreamRunner.run_stream."""

    def test_run_stream_file_not_found(self):
        """Running a stream with non-existent file sets error."""
        runner = TPCHStreamRunner(connection_string="test://conn", verbose=0)
        result = runner.run_stream(Path("/nonexistent/stream.sql"), stream_id=0)

        assert result["success"] is False
        assert result["error"] is not None
        assert "not found" in result["error"].lower() or "No such file" in result["error"]

    def test_run_stream_with_valid_file(self, tmp_path):
        """Running a stream with a valid file produces correct results."""
        stream_file = tmp_path / "stream_0.sql"
        stream_file.write_text(
            "-- TPC-H Stream 0\n"
            "-- Query 14 (Stream 0, Position 1)\n"
            "SELECT 1;\n\n"
            "-- Query 2 (Stream 0, Position 2)\n"
            "SELECT 2;\n\n"
            "-- Query 9 (Stream 0, Position 3)\n"
            "SELECT 3;\n\n"
        )

        runner = TPCHStreamRunner(connection_string="test://conn", verbose=0)
        result = runner.run_stream(stream_file, stream_id=0)

        assert result["stream_id"] == 0
        assert result["queries_executed"] == 3
        assert result["queries_successful"] == 3
        assert result["queries_failed"] == 0
        assert result["success"] is True
        assert result["duration"] >= 0

    def test_run_stream_empty_file(self, tmp_path):
        """Running a stream with an empty file produces zero queries."""
        stream_file = tmp_path / "stream_empty.sql"
        stream_file.write_text("-- Empty stream\n")

        runner = TPCHStreamRunner(connection_string="test://conn", verbose=0)
        result = runner.run_stream(stream_file, stream_id=0)

        assert result["queries_executed"] == 0
        assert result["success"] is True

    def test_run_stream_timing_fields(self, tmp_path):
        """Result includes correct timing fields."""
        stream_file = tmp_path / "stream_0.sql"
        stream_file.write_text("-- Query 1 (Stream 0, Position 1)\nSELECT 1;\n")

        runner = TPCHStreamRunner(connection_string="test://conn", verbose=0)
        result = runner.run_stream(stream_file, stream_id=0)

        assert result["start_time"] > 0
        assert result["end_time"] >= result["start_time"]
        assert result["duration"] == pytest.approx(
            result["end_time"] - result["start_time"],
            abs=0.01,
        )


# ---------------------------------------------------------------------------
# Compile qgen (mocked)
# ---------------------------------------------------------------------------
class TestCompileQgen:
    """Tests for _compile_qgen with mocked subprocess."""

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    @patch("subprocess.run")
    def test_compile_qgen_failure_returns_none(self, mock_run, mock_templates, tmp_path):
        """When compilation fails, _compile_qgen returns None."""
        import subprocess

        mock_templates.return_value = tmp_path / "templates"
        (tmp_path / "templates").mkdir()

        mock_run.side_effect = subprocess.CalledProcessError(1, "make")

        streams = TPCHStreams(num_streams=1, verbose=0)
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        result = streams._compile_qgen(work_dir)
        assert result is None

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    @patch("subprocess.run")
    def test_compile_qgen_success_returns_path(self, mock_run, mock_templates, tmp_path):
        """When compilation succeeds and exe exists, returns path."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        mock_templates.return_value = templates_dir

        # Mock successful subprocess
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        streams = TPCHStreams(num_streams=1, verbose=0)
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        # Seed the template directory with the expected binary so copytree() carries it into the build dir.
        exe_name = "qgen.exe" if platform.system().lower() == "windows" else "qgen"
        qgen_exe = templates_dir / exe_name
        qgen_exe.write_bytes(b"fake exe")

        result = streams._compile_qgen(work_dir)
        assert result == work_dir / "tpch_tools" / exe_name

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    @patch("subprocess.run")
    def test_compile_qgen_no_exe_after_success(self, mock_run, mock_templates, tmp_path):
        """When subprocess succeeds but exe doesn't exist, returns None."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        mock_templates.return_value = templates_dir

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        streams = TPCHStreams(num_streams=1, verbose=0)
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        # Don't create the exe file
        result = streams._compile_qgen(work_dir)
        assert result is None


# ---------------------------------------------------------------------------
# _compile_qgen platform detection
# ---------------------------------------------------------------------------
class TestCompileQgenPlatform:
    """Tests for platform-specific compilation settings."""

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    @patch("subprocess.run")
    @patch("platform.system", return_value="Linux")
    def test_linux_machine_flag(self, _mock_sys, mock_run, mock_templates, tmp_path):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        mock_templates.return_value = templates_dir
        mock_run.side_effect = __import__("subprocess").CalledProcessError(1, "make")

        streams = TPCHStreams(num_streams=1, verbose=0)
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        streams._compile_qgen(work_dir)

        # Verify the command was called with MACHINE=LINUX
        call_args = mock_run.call_args
        cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
        assert "MACHINE=LINUX" in cmd


# ---------------------------------------------------------------------------
# qgen stream file assembly
# ---------------------------------------------------------------------------
class TestGenerateStreamQueriesQgen:
    """Tests for assembling stream files from qgen outputs."""

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_generate_stream_queries_qgen_writes_permuted_stream_file(self, mock_templates, tmp_path):
        """Generated query files should be merged into a permuted stream file."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(output_dir=tmp_path, scale_factor=0.01, rng_seed=7, verbose=2)
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "1.sql").write_text("SELECT 1;")
        (work_dir / "2.sql").write_text("SELECT 2;")

        with (
            patch.object(streams, "_get_stream_permutation", return_value=[2, 1, 3]),
            patch("benchbox.core.tpch.streams.subprocess.run", return_value=Mock(stdout="generated", stderr="")) as run,
            patch.object(streams.logger, "warning") as warning_log,
        ):
            stream_file = streams._generate_stream_queries_qgen(0, Path("/fake/qgen"), work_dir)

        assert stream_file == tmp_path / "stream_0.sql"
        content = stream_file.read_text()
        assert "-- TPC-H Stream 0" in content
        assert "-- Query Order (Permuted): [2, 1, 3]" in content
        assert content.index("-- Query 2") < content.index("-- Query 1")
        warning_log.assert_called_once_with("Query %s not generated by qgen for stream %s", 3, 0)

        run.assert_called_once()
        cmd = run.call_args.args[0]
        assert cmd == [str(Path("/fake/qgen")), "-p", "1", "-s", "0.01", "-r", "7", "-o", str(work_dir)]

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_generate_stream_queries_qgen_wraps_subprocess_failures(self, mock_templates, tmp_path):
        """qgen execution failures should become a runtime error with stderr details."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(output_dir=tmp_path, verbose=0)
        error = subprocess.CalledProcessError(returncode=1, cmd=["qgen"], stderr="compile failed")

        with (
            patch.object(streams, "_get_stream_permutation", return_value=[1]),
            patch("benchbox.core.tpch.streams.subprocess.run", side_effect=error),
            pytest.raises(RuntimeError, match="Failed to generate stream 2 with qgen"),
        ):
            streams._generate_stream_queries_qgen(2, Path("/fake/qgen"), tmp_path)


# ---------------------------------------------------------------------------
# generate_streams orchestration
# ---------------------------------------------------------------------------
class TestGenerateStreams:
    """Tests for end-to-end stream generation orchestration."""

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_generate_streams_skips_failed_streams_and_logs_summary(self, mock_templates, tmp_path):
        """Per-stream failures should be logged while successful streams are returned."""
        mock_templates.return_value = Path("/fake/templates")
        output_dir = tmp_path / "streams"
        streams = TPCHStreams(num_streams=3, output_dir=output_dir, verbose=1)
        generated_files = [output_dir / "stream_0.sql", output_dir / "stream_2.sql"]

        with (
            patch.object(streams, "_compile_qgen", return_value=Path("/fake/qgen")) as compile_qgen,
            patch.object(
                streams,
                "_generate_stream_queries_qgen",
                side_effect=[generated_files[0], RuntimeError("bad stream"), generated_files[1]],
            ) as generate_stream,
            patch.object(streams.logger, "error") as error_log,
            patch.object(streams.logger, "info") as info_log,
        ):
            stream_files = streams.generate_streams()

        assert output_dir.exists()
        assert stream_files == generated_files
        compile_qgen.assert_called_once()
        assert generate_stream.call_count == 3
        error_log.assert_called_once()
        info_log.assert_any_call("Generated %s stream files", 2)

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    def test_generate_streams_wraps_compile_failures(self, mock_templates, tmp_path):
        """Compilation failures should stop generation with build-tool guidance."""
        mock_templates.return_value = Path("/fake/templates")
        streams = TPCHStreams(output_dir=tmp_path, verbose=0)

        with (
            patch.object(streams, "_compile_qgen", side_effect=RuntimeError("missing make")),
            pytest.raises(RuntimeError, match="TPC-H streams generation requires qgen compilation"),
        ):
            streams.generate_streams()


# ---------------------------------------------------------------------------
# Additional runner behavior
# ---------------------------------------------------------------------------
class TestTPCHStreamRunnerAdditional:
    """Additional branch coverage for TPCHStreamRunner."""

    def test_run_stream_logs_success_when_verbose(self, tmp_path):
        """Verbose mode should log query success counts for a completed stream."""
        runner = TPCHStreamRunner(connection_string="duckdb:///:memory:", verbose=1)
        stream_file = tmp_path / "stream.sql"
        stream_file.write_text("-- Query 1 (Stream 0, Position 1)\nSELECT 1;\n")

        with patch.object(runner.logger, "info") as info_log:
            result = runner.run_stream(stream_file, stream_id=0)

        assert result["success"] is True
        info_log.assert_any_call("Stream %s completed: %s/%s queries successful", 0, 1, 1)

    def test_run_concurrent_streams_uses_factory_and_restores_executor_config(self, tmp_path):
        """Concurrent execution should build stream executors and restore config afterwards."""
        runner = TPCHStreamRunner(connection_string="duckdb:///:memory:", verbose=1)
        stream_file = tmp_path / "stream_0.sql"
        stream_file.write_text("-- Query 1 (Stream 0, Position 1)\nSELECT 1;\n")
        concurrent_result = Mock(
            stream_results=[{"success": True, "queries_executed": 1, "queries_successful": 1}],
            queries_executed=1,
            queries_successful=1,
            queries_failed=0,
            success=True,
            errors=[],
        )
        executor = Mock()
        executor.config = {"enabled": False}

        def fake_execute(factory, num_streams):
            stream_executor = factory(0)
            assert stream_executor.run() == {"success": True}
            with pytest.raises(ValueError, match="exceeds available stream files"):
                factory(1)
            assert num_streams == 1
            return concurrent_result

        executor.execute_concurrent_queries.side_effect = fake_execute

        with (
            patch("benchbox.utils.execution_manager.ConcurrentQueryExecutor", return_value=executor),
            patch.object(runner, "run_stream", return_value={"success": True}) as run_stream,
            patch.object(runner.logger, "info") as info_log,
        ):
            result = runner.run_concurrent_streams([stream_file])

        run_stream.assert_called_once_with(stream_file, 0)
        assert executor.config["enabled"] is False
        assert result["streams_successful"] == 1
        info_log.assert_any_call("Concurrent streams completed: %s/%s streams successful", 1, 1)
        info_log.assert_any_call("Total queries: %s/%s successful", 1, 1)

    def test_run_concurrent_streams_handles_executor_failures(self, tmp_path):
        """Executor failures should surface as unsuccessful concurrent runs."""
        runner = TPCHStreamRunner(connection_string="duckdb:///:memory:", verbose=0)
        stream_file = tmp_path / "stream_0.sql"
        stream_file.write_text("-- Query 1 (Stream 0, Position 1)\nSELECT 1;\n")
        executor = Mock()
        executor.config = {"enabled": False}
        executor.execute_concurrent_queries.side_effect = RuntimeError("executor blew up")

        with patch("benchbox.utils.execution_manager.ConcurrentQueryExecutor", return_value=executor):
            result = runner.run_concurrent_streams([stream_file])

        assert executor.config["enabled"] is False
        assert result["success"] is False
        assert result["errors"] == ["executor blew up"]

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    @patch("subprocess.run")
    @patch("platform.system", return_value="Windows")
    def test_windows_machine_flag(self, _mock_sys, mock_run, mock_templates, tmp_path):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        mock_templates.return_value = templates_dir
        mock_run.side_effect = __import__("subprocess").CalledProcessError(1, "make")

        streams = TPCHStreams(num_streams=1, verbose=0)
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        streams._compile_qgen(work_dir)

        call_args = mock_run.call_args
        cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
        assert "MACHINE=WIN32" in cmd

    @patch("benchbox.utils.tpc_compilation.get_tpc_templates_dir")
    @patch("subprocess.run")
    @patch("platform.system", return_value="SomeOS")
    def test_unknown_os_defaults_to_linux(self, _mock_sys, mock_run, mock_templates, tmp_path):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        mock_templates.return_value = templates_dir
        mock_run.side_effect = __import__("subprocess").CalledProcessError(1, "make")

        streams = TPCHStreams(num_streams=1, verbose=0)
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        streams._compile_qgen(work_dir)

        call_args = mock_run.call_args
        cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
        assert "MACHINE=LINUX" in cmd
