"""QGen binary integration validation tests for TPC-H ultra-simplified implementation.

Tests integration with the qgen C binary and validates outputs.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import subprocess
import tempfile

import pytest

from benchbox.core.tpch.queries import QGenBinary, TPCHQueries

pytestmark = pytest.mark.fast



class TestQGenBinaryIntegration:
    """Test QGen binary integration and validation."""

    def test_qgen_binary_discovery(self):
        """Test that qgen binary can be discovered."""
        qgen = QGenBinary()

        # Should find qgen binary
        assert qgen.qgen_path is not None
        assert os.path.exists(qgen.qgen_path)
        assert os.access(qgen.qgen_path, os.X_OK)  # Should be executable

    def test_qgen_templates_directory(self):
        """Test that qgen templates directory exists."""
        qgen = QGenBinary()

        # Should find templates directory
        assert qgen.templates_dir is not None
        assert os.path.exists(qgen.templates_dir)
        assert os.path.isdir(qgen.templates_dir)

    def test_qgen_binary_execution(self):
        """Test direct qgen binary execution."""
        qgen = QGenBinary()

        # Should be able to execute qgen with basic parameters
        result = qgen.generate(1, seed=12345, scale_factor=1.0)

        assert isinstance(result, str)
        assert len(result) > 50
        assert "select" in result.lower() or "with" in result.lower()

    def test_qgen_parameter_passing(self):
        """Test that parameters are correctly passed to qgen."""
        qgen = QGenBinary()

        # Test with different seeds
        result1 = qgen.generate(1, seed=11111)
        result2 = qgen.generate(1, seed=22222)

        # Should be different
        assert result1 != result2

        # Test with same seed
        result3 = qgen.generate(1, seed=11111)
        assert result1 == result3

    def test_qgen_scale_factor_handling(self):
        """Test scale factor handling in qgen."""
        qgen = QGenBinary()

        # Test different scale factors
        result_small = qgen.generate(1, seed=12345, scale_factor=0.1)
        result_large = qgen.generate(1, seed=12345, scale_factor=10.0)

        assert isinstance(result_small, str)
        assert isinstance(result_large, str)
        assert len(result_small) > 50
        assert len(result_large) > 50

    def test_qgen_ansi_mode(self):
        """Test that qgen runs in ANSI mode."""
        qgen = QGenBinary()

        # Generate a query
        result = qgen.generate(1, seed=54321)

        # Should produce ANSI SQL (basic validation)
        assert isinstance(result, str)
        assert "select" in result.lower() or "with" in result.lower()

        # Should not contain obvious dialect-specific constructs
        # (This is basic validation - more thorough dialect testing elsewhere)
        result_lower = result.lower()
        assert "limit" not in result_lower or "order by" in result_lower  # LIMIT should come with ORDER BY

    def test_qgen_output_cleaning(self):
        """Test qgen output cleaning functionality."""
        qgen = QGenBinary()

        # Generate query
        result = qgen.generate(1, seed=99999)

        # Should be cleaned (no leading/trailing whitespace)
        assert result == result.strip()

        # Should not have excessive blank lines
        lines = result.split("\n")
        non_empty_lines = [line for line in lines if line.strip()]
        assert len(non_empty_lines) >= len(lines) // 2  # At least half should be content

    def test_qgen_timeout_handling(self):
        """Test qgen timeout handling."""
        qgen = QGenBinary()

        # Should complete within timeout
        import time

        start_time = time.time()
        result = qgen.generate(1, seed=12345)
        execution_time = time.time() - start_time

        assert execution_time < 5.0  # Should complete within 5 seconds
        assert isinstance(result, str)
        assert len(result) > 50

    def test_qgen_error_handling(self):
        """Test qgen error handling."""
        qgen = QGenBinary()

        # Test with invalid query ID (should raise subprocess.CalledProcessError)
        with pytest.raises(subprocess.CalledProcessError):
            qgen.generate(25, seed=12345)  # Invalid query ID

    def test_qgen_concurrent_execution(self):
        """Test concurrent qgen execution."""
        import threading

        qgen = QGenBinary()
        results = []
        errors = []

        def generate_query(query_id, seed):
            try:
                result = qgen.generate(query_id, seed=seed)
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=generate_query, args=(1, 10000 + i))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Should have no errors
        assert len(errors) == 0, f"Concurrent execution errors: {errors}"
        assert len(results) == 5

        # All results should be valid
        for result in results:
            assert isinstance(result, str)
            assert len(result) > 50

    def test_qgen_all_queries_generation(self):
        """Test that qgen can generate all 22 queries."""
        qgen = QGenBinary()

        for query_id in range(1, 23):
            result = qgen.generate(query_id, seed=77777)
            assert isinstance(result, str), f"Query {query_id} failed"
            assert len(result) > 50, f"Query {query_id} too short"

    def test_qgen_output_consistency(self):
        """Test qgen output consistency."""
        qgen = QGenBinary()

        # Generate same query multiple times
        results = []
        for _ in range(3):
            result = qgen.generate(1, seed=12345, scale_factor=1.0)
            results.append(result)

        # Should be identical
        assert len(set(results)) == 1, "QGen should produce consistent output"

    def test_qgen_working_directory(self):
        """Test qgen working directory handling."""
        qgen = QGenBinary()

        # Should work from templates directory
        result = qgen.generate(1, seed=88888)
        assert isinstance(result, str)
        assert len(result) > 50

        # Should still work after changing working directory
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                result2 = qgen.generate(1, seed=88888)
                assert result == result2
            finally:
                # Restore CWD before TemporaryDirectory cleanup -
                # on Windows, the CWD holds a lock that prevents deletion.
                os.chdir(original_cwd)

    def test_qgen_environment_isolation(self):
        """Test qgen environment isolation."""
        qgen = QGenBinary()

        # Should work regardless of environment variables
        original_env = os.environ.copy()
        try:
            # Modify environment
            os.environ["RANDOM_VAR"] = "test_value"
            os.environ["PATH"] = "/nonexistent:" + os.environ.get("PATH", "")

            result = qgen.generate(1, seed=12345)
            assert isinstance(result, str)
            assert len(result) > 50
        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_qgen_integration_with_tpch_queries(self):
        """Test qgen integration with TPCHQueries class."""
        queries = TPCHQueries()

        # Should use qgen internally
        assert queries.qgen is not None
        assert isinstance(queries.qgen, QGenBinary)

        # Should generate queries through qgen
        result = queries.get_query(1, seed=12345)
        assert isinstance(result, str)
        assert len(result) > 50

    def test_qgen_binary_version_compatibility(self):
        """Test qgen binary version compatibility."""
        qgen = QGenBinary()

        # Should be able to execute basic help/version commands
        # (This is a basic smoke test for binary compatibility)
        try:
            # Try to run qgen with help flag
            result = subprocess.run([qgen.qgen_path, "-h"], capture_output=True, text=True, timeout=5)
            # Should either succeed or fail gracefully
            assert result.returncode in [0, 1]  # 0 = success, 1 = help shown
        except subprocess.TimeoutExpired:
            pytest.skip("QGen binary timeout on help command")

    def test_qgen_output_format_validation(self):
        """Test qgen output format validation."""
        qgen = QGenBinary()

        for query_id in [1, 5, 10, 15, 20]:  # Sample queries
            result = qgen.generate(query_id, seed=12345)

            # Should be valid SQL format
            assert isinstance(result, str)
            assert len(result) > 50

            # Should not contain binary or non-text data
            assert result.isprintable() or all(c in "\t\n\r" for c in result if not c.isprintable())

            # Should contain SQL keywords
            result_lower = result.lower()
            assert "select" in result_lower or "with" in result_lower

    def test_qgen_resource_usage(self):
        """Test qgen resource usage is reasonable."""
        import os
        import time

        import psutil

        qgen = QGenBinary()

        # Monitor resource usage
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss

        start_time = time.time()

        # Generate several queries
        for query_id in range(1, 6):
            result = qgen.generate(query_id, seed=12345)
            assert isinstance(result, str)

        execution_time = time.time() - start_time
        mem_after = process.memory_info().rss

        # Should be reasonably fast and not consume excessive memory
        assert execution_time < 10.0  # Should complete within 10 seconds
        assert (mem_after - mem_before) < 100 * 1024 * 1024  # Less than 100MB additional memory

    def test_qgen_reproducibility(self):
        """Test qgen reproducibility across runs."""
        qgen = QGenBinary()

        # Generate queries in different sessions
        session1_results = []
        session2_results = []

        seed = 12345
        for query_id in [1, 2, 3]:
            session1_results.append(qgen.generate(query_id, seed=seed))

        # Simulate new session by creating new QGenBinary instance
        qgen2 = QGenBinary()
        for query_id in [1, 2, 3]:
            session2_results.append(qgen2.generate(query_id, seed=seed))

        # Should be identical
        assert session1_results == session2_results
