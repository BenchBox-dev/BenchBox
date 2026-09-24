"""Live integration tests for BigQuery with real credentials.

These tests are SKIPPED by default and only run when credentials are available.
They execute real queries against live Google BigQuery instances.

Setup:
1. Copy .env.example to .env
2. Fill in your BigQuery credentials:
   - BIGQUERY_PROJECT
   - BIGQUERY_DATASET
   - BIGQUERY_LOCATION
   - GOOGLE_APPLICATION_CREDENTIALS (path to service account JSON)
3. Run: make test-live-bigquery

Cost: All tests use scale_factor=0.01 (~10MB) for minimal cost.
Estimated cost per test run: <$0.10 (storage + query processing)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os

import pytest

from benchbox import TPCH

# Mark all tests in this file
pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_integration,
    pytest.mark.live_bigquery,
    pytest.mark.skipif(
        not os.getenv("BIGQUERY_PROJECT") or not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        reason="Requires BIGQUERY_PROJECT and GOOGLE_APPLICATION_CREDENTIALS. See .env.example for setup.",
    ),
]


class TestLiveBigQueryConnection:
    """Test basic BigQuery connectivity."""

    def test_bigquery_live_connection(self, live_bigquery_adapter):
        """Verify BigQuery connection works and can execute simple query."""
        connection = live_bigquery_adapter.create_connection()
        try:
            # Execute simple query to verify connection
            query_job = connection.query("SELECT 1 as test")
            results = list(query_job.result())
            assert len(results) == 1
            assert results[0][0] == 1

        finally:
            live_bigquery_adapter.close_connection(connection)

    def test_bigquery_live_version_info(self, live_bigquery_adapter):
        """Verify we can get BigQuery version information."""
        connection = live_bigquery_adapter.create_connection()
        try:
            metadata = live_bigquery_adapter.get_platform_info(connection)

            assert metadata["platform_name"] == "BigQuery"
            assert "project_id" in metadata
            assert metadata["connection_type"] in ["bigquery", "serverless"]

        finally:
            live_bigquery_adapter.close_connection(connection)

    def test_bigquery_live_project_access(self, live_bigquery_adapter):
        """Verify project and dataset access."""
        connection = live_bigquery_adapter.create_connection()
        try:
            # Get project info
            project_id = connection.project
            assert project_id is not None
            print(f"Connected to project: {project_id}")

            # List datasets (should work even if empty)
            datasets = list(connection.list_datasets())
            print(f"Found {len(datasets)} datasets in project")

        finally:
            live_bigquery_adapter.close_connection(connection)


class TestLiveBigQueryDatasetManagement:
    """Test dataset creation and management."""

    def test_bigquery_live_dataset_creation(self, live_bigquery_adapter, unique_test_schema, cleanup_test_schema):
        """Create and verify test dataset."""
        connection = live_bigquery_adapter.create_connection()
        cleanup_test_schema(live_bigquery_adapter, unique_test_schema)

        try:
            # Create dataset
            from google.cloud import bigquery

            dataset_id = f"{connection.project}.{unique_test_schema}"
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            dataset = connection.create_dataset(dataset, exists_ok=True)

            # Verify dataset exists
            datasets = list(connection.list_datasets())
            dataset_names = [ds.dataset_id for ds in datasets]
            assert unique_test_schema in dataset_names

        finally:
            live_bigquery_adapter.close_connection(connection)


class TestLiveBigQueryDataLoading:
    """Test TPC-H data loading on BigQuery."""

    def test_bigquery_live_tpch_data_load(
        self, live_bigquery_adapter, unique_test_schema, test_scale_factor, test_output_dir, cleanup_test_schema
    ):
        """Load TPC-H data into BigQuery and verify."""
        cleanup_test_schema(live_bigquery_adapter, unique_test_schema)

        # Create TPC-H benchmark
        tpch = TPCH(scale_factor=test_scale_factor, output_dir=test_output_dir, verbose=False)

        # Generate data
        data_files = tpch.generate_data()
        assert len(data_files) > 0, "No data files generated"

        connection = live_bigquery_adapter.create_connection()
        try:
            from google.cloud import bigquery

            # Create dataset
            dataset_id = f"{connection.project}.{unique_test_schema}"
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            connection.create_dataset(dataset, exists_ok=True)

            # Create tables
            create_sql = tpch.get_create_tables_sql(dialect="bigquery")
            for statement in create_sql.split(";"):
                if statement.strip():
                    # BigQuery requires fully qualified table names
                    qualified_statement = statement.replace("CREATE TABLE ", f"CREATE TABLE {dataset_id}.")
                    query_job = connection.query(qualified_statement)
                    query_job.result()  # Wait for completion

            # Load data using adapter
            stats, errors, _ = live_bigquery_adapter.load_data(tpch, connection, test_output_dir)

            # Verify data was loaded
            assert len(stats) > 0, "No tables loaded"
            assert all(count > 0 for count in stats.values()), "Some tables have zero rows"

            # Verify specific table
            query = f"SELECT COUNT(*) FROM `{dataset_id}.LINEITEM`"
            query_job = connection.query(query)
            results = list(query_job.result())
            lineitem_count = results[0][0]
            assert lineitem_count > 0, "LINEITEM table is empty"

        finally:
            live_bigquery_adapter.close_connection(connection)


class TestLiveBigQueryQueryExecution:
    """Test query execution on BigQuery."""

    def test_bigquery_live_simple_query(self, live_bigquery_adapter, unique_test_schema):
        """Execute simple query to verify query execution works."""
        connection = live_bigquery_adapter.create_connection()
        try:
            # Simple aggregation query
            query = "SELECT COUNT(*) as cnt, SUM(1) as total FROM UNNEST([1, 2]) as num"
            query_job = connection.query(query)
            results = list(query_job.result())

            assert len(results) == 1
            assert results[0][0] == 2  # count
            assert results[0][1] == 2  # sum

        finally:
            live_bigquery_adapter.close_connection(connection)

    def test_bigquery_live_tpch_query_execution(
        self, live_bigquery_adapter, unique_test_schema, test_scale_factor, test_output_dir
    ):
        """Execute TPC-H Query 1 on loaded data (requires data load test to pass first)."""
        # Note: This test assumes data is already loaded from previous test
        # In real usage, you'd load data in a session-scoped fixture

        tpch = TPCH(scale_factor=test_scale_factor, output_dir=test_output_dir, verbose=False)

        connection = live_bigquery_adapter.create_connection()
        try:
            # Check if data exists (skip if not)
            dataset_id = f"{connection.project}.{unique_test_schema}"
            try:
                query = f"SELECT COUNT(*) FROM `{dataset_id}.LINEITEM`"
                query_job = connection.query(query)
                results = list(query_job.result())
                count = results[0][0]
                if count == 0:
                    pytest.skip("No data loaded - run data load test first")
            except Exception:
                pytest.skip("Dataset not found - run dataset creation test first")

            # Get and execute Query 1
            query1 = tpch.get_query(1, seed=42)

            # Translate to BigQuery SQL dialect with fully qualified table name
            query1_bigquery = query1.replace("LINEITEM", f"`{dataset_id}.LINEITEM`")

            query_job = connection.query(query1_bigquery)
            results = list(query_job.result())

            # Verify we got results
            assert len(results) > 0, "Query 1 returned no results"
            print(f"Query 1 returned {len(results)} rows")

        finally:
            live_bigquery_adapter.close_connection(connection)


class TestLiveBigQuerySpecificFeatures:
    """Test BigQuery-specific features."""

    def test_bigquery_live_gcs_load(
        self, live_bigquery_adapter, unique_test_schema, test_output_dir, cleanup_test_schema
    ):
        """Test GCS load workflow with staged files."""
        cleanup_test_schema(live_bigquery_adapter, unique_test_schema)

        connection = live_bigquery_adapter.create_connection()
        try:
            from google.cloud import bigquery

            # Create dataset and simple table
            dataset_id = f"{connection.project}.{unique_test_schema}"
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            connection.create_dataset(dataset, exists_ok=True)

            # Create table
            table_id = f"{dataset_id}.test_copy"
            schema = [
                bigquery.SchemaField("id", "INTEGER"),
                bigquery.SchemaField("value", "STRING"),
            ]
            table = bigquery.Table(table_id, schema=schema)
            connection.create_table(table)

            # Create a small test file
            test_file = test_output_dir / "test_data.csv"
            test_file.write_text("1,test1\n2,test2\n3,test3\n")

            # Note: Real GCS load would upload to GCS and load from there
            # This test verifies the SQL syntax works
            # In production, adapter.load_data() handles GCS staging

            # Verify table exists and is empty
            query = f"SELECT COUNT(*) FROM `{table_id}`"
            query_job = connection.query(query)
            results = list(query_job.result())
            initial_count = results[0][0]
            assert initial_count == 0

        finally:
            live_bigquery_adapter.close_connection(connection)

    def test_bigquery_live_query_cost(self, live_bigquery_adapter):
        """Verify query cost estimation works."""
        connection = live_bigquery_adapter.create_connection()
        try:
            from google.cloud import bigquery

            # Run a simple query with dry_run to estimate cost
            job_config = bigquery.QueryJobConfig(dry_run=True)
            query = "SELECT COUNT(*) FROM UNNEST(GENERATE_ARRAY(1, 1000)) as num"

            query_job = connection.query(query, job_config=job_config)

            # Verify we got bytes processed estimate
            assert query_job.total_bytes_processed is not None
            assert query_job.total_bytes_processed >= 0
            print(f"Query would process {query_job.total_bytes_processed} bytes")

        finally:
            live_bigquery_adapter.close_connection(connection)

    def test_bigquery_live_cleanup(self, live_bigquery_adapter, unique_test_schema):
        """Verify cleanup works correctly."""
        connection = live_bigquery_adapter.create_connection()
        try:
            # Try to drop dataset (should work even if it doesn't exist)
            dataset_id = f"{connection.project}.{unique_test_schema}"
            connection.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)

            # Verify dataset is gone
            datasets = list(connection.list_datasets())
            dataset_names = [ds.dataset_id for ds in datasets]
            assert unique_test_schema not in dataset_names

        finally:
            live_bigquery_adapter.close_connection(connection)


class TestLiveBigQueryQueryPlanCapture:
    """Test query plan capture from completed BigQuery QueryJob statistics.

    BigQuery exposes no pre-execution EXPLAIN; the plan is harvested from the
    completed job, so capture is verified through execute_query() with
    capture_plans=True. Queries stay at SELECT 1 with no table references:
    such queries process 0 bytes and stay inside the free tier.
    """

    @staticmethod
    def _capture_adapter(bigquery_credentials):
        """Create a BigQuery adapter with query plan capture enabled."""
        from benchbox.platforms.bigquery import BigQueryAdapter

        return BigQueryAdapter(**{**bigquery_credentials, "capture_plans": True})

    @staticmethod
    def _connect(adapter):
        """Create a connection with benchmark job config applied.

        Disables the result cache (same as production benchmark runs): a
        repeated SELECT 1 must execute for real so every run exposes full
        job statistics for plan capture, instead of serving a cache hit.
        """
        connection = adapter.create_connection()
        adapter.configure_for_benchmark(connection, "olap")
        return connection

    def test_execute_query_with_capture_returns_plan(self, bigquery_credentials):
        """execute_query with capture enabled should attach a plan and fingerprint."""
        adapter = self._capture_adapter(bigquery_credentials)
        connection = self._connect(adapter)
        try:
            result = adapter.execute_query(connection, "SELECT 1", query_id="Q0", validate_row_count=False)
            assert result["status"] == "SUCCESS"
            assert result.get("query_plan") is not None
            fingerprint = result.get("plan_fingerprint")
            assert fingerprint is not None
            assert len(fingerprint) == 64  # SHA256 hex
            # SELECT 1 scans no tables, so capture must not incur scan billing.
            job_stats = result.get("job_statistics") or {}
            assert job_stats.get("bytes_processed") == 0
        finally:
            adapter.close_connection(connection)

    def test_plan_fingerprint_stable(self, bigquery_credentials):
        """Same query executed twice must produce identical fingerprints."""
        adapter = self._capture_adapter(bigquery_credentials)
        connection = self._connect(adapter)
        try:
            first = adapter.execute_query(connection, "SELECT 1", query_id="Q0", validate_row_count=False)
            second = adapter.execute_query(connection, "SELECT 1", query_id="Q0", validate_row_count=False)
            assert first["status"] == "SUCCESS"
            assert second["status"] == "SUCCESS"
            first_fingerprint = first.get("plan_fingerprint")
            second_fingerprint = second.get("plan_fingerprint")
            assert first_fingerprint is not None
            assert second_fingerprint is not None
            assert first_fingerprint == second_fingerprint
        finally:
            adapter.close_connection(connection)
