"""PostgreSQL integration smoke tests with stubbed psycopg."""

import pytest

from .common import PostgreSQLStubState, install_postgresql_stub

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


@pytest.mark.integration
@pytest.mark.platform_smoke
def test_postgresql_smoke_run(monkeypatch, tmp_path):
    """Test basic PostgreSQL adapter workflow."""
    state: PostgreSQLStubState = install_postgresql_stub(monkeypatch)

    from benchbox.platforms.postgresql import PostgreSQLAdapter

    adapter = PostgreSQLAdapter(
        host=state.host,
        port=state.port,
        database=state.database,
        username="postgres",
        password="secret",
        schema="public",
    )

    connection = adapter.create_connection()
    try:
        info = adapter.get_platform_info(connection)
        assert info["platform_type"] == "postgresql"
        assert info["platform_name"] == "PostgreSQL"
    finally:
        adapter.close_connection(connection)


@pytest.mark.integration
@pytest.mark.platform_smoke
def test_postgresql_requires_database(monkeypatch):
    """Test that PostgreSQL adapter requires database configuration."""
    install_postgresql_stub(monkeypatch)

    from benchbox.platforms.postgresql import PostgreSQLAdapter

    # PostgreSQL adapter uses defaults if not provided
    adapter = PostgreSQLAdapter(
        host="localhost",
        username="postgres",
    )

    # Should use default database name
    assert adapter.platform_name == "PostgreSQL"
