"""StarRocks integration smoke tests with stubbed pymysql."""

import pytest

from .common import StarRocksStubState, install_starrocks_stub

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


@pytest.mark.integration
@pytest.mark.platform_smoke
def test_starrocks_smoke_basic(monkeypatch, tmp_path):
    """Test basic StarRocks adapter workflow."""
    state: StarRocksStubState = install_starrocks_stub(monkeypatch)

    from benchbox.platforms.starrocks import StarRocksAdapter

    adapter = StarRocksAdapter(
        host=state.host,
        port=state.port,
        database="benchbox_smoke",
    )

    connection = adapter.create_connection()
    try:
        info = adapter.get_platform_info(connection)
        assert info["platform_type"] == "starrocks"
        assert info["platform_name"] == "StarRocks"
    finally:
        adapter.close_connection(connection)


@pytest.mark.integration
@pytest.mark.platform_smoke
def test_starrocks_smoke_query_execution(monkeypatch, tmp_path):
    """Test StarRocks query execution."""
    state: StarRocksStubState = install_starrocks_stub(monkeypatch)

    from benchbox.platforms.starrocks import StarRocksAdapter

    adapter = StarRocksAdapter(
        host=state.host,
        port=state.port,
        database="benchbox_smoke",
    )

    connection = adapter.create_connection()
    try:
        result = adapter.execute_query(
            connection,
            "SELECT COUNT(*) FROM lineitem",
            "q1",
        )
        assert result["status"] == "SUCCESS"
        assert isinstance(result["execution_time_seconds"], float)
    finally:
        adapter.close_connection(connection)
