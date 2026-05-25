"""Resource-heavy StarRocks smoke coverage."""

import pytest

from .common import StarRocksStubState, create_smoke_benchmark, install_starrocks_stub, run_smoke_benchmark

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.resource_heavy,
]


def test_starrocks_smoke_full_workflow(monkeypatch, tmp_path):
    """Test full StarRocks workflow: schema, load, configure, query."""
    state: StarRocksStubState = install_starrocks_stub(monkeypatch)

    from benchbox.platforms.starrocks import StarRocksAdapter

    adapter = StarRocksAdapter(
        host=state.host,
        port=state.port,
        database="benchbox_smoke",
    )

    benchmark = create_smoke_benchmark(tmp_path)
    _table_stats, metadata, _ = run_smoke_benchmark(adapter, benchmark, tmp_path)

    assert metadata["platform_type"] == "starrocks"
    # Schema and load statements should have been executed
    assert len(state.statements) > 0
