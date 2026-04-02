"""Coverage tests for TPC-DI dimension/fact generator mixins."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.core.tpcdi.generator.data import TPCDIDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_small_generator(tmp_path: Path) -> TPCDIDataGenerator:
    gen = TPCDIDataGenerator(
        scale_factor=1.0,
        output_dir=tmp_path,
        chunk_size=7,
        buffer_size=512,
        max_workers=2,
        enable_progress=True,
        compression="none",
    )
    # Keep datasets small so tests stay fast.
    gen.base_customers = 12
    gen.base_companies = 8
    gen.base_securities = 15
    gen.base_accounts = 20
    gen.base_trades = 50
    # Keep output paths stable without compression side effects.
    gen.compress_existing_file = lambda path, remove_original=True: path  # type: ignore[method-assign]
    return gen


def test_dimension_generators_cover_all_dimension_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    gen = _make_small_generator(tmp_path)

    # Force memory-check/cleanup branch in DimCompany once.
    state = {"calls": 0}

    def _mem_check() -> bool:
        state["calls"] += 1
        return state["calls"] == 1

    cleanup_calls: list[bool] = []
    monkeypatch.setattr(gen, "_check_memory_usage", _mem_check)
    monkeypatch.setattr(gen, "_cleanup_memory", lambda: cleanup_calls.append(True))

    dim_files = [
        gen._generate_dimdate_data(),
        gen._generate_dimtime_data(),
        gen._generate_dimcompany_data(),
        gen._generate_dimsecurity_data(),
        gen._generate_dimcustomer_data(),
        gen._generate_dimaccount_data(),
        gen._generate_industry_data(),
        gen._generate_statustype_data(),
        gen._generate_taxrate_data(),
        gen._generate_tradetype_data(),
        gen._generate_dimbroker_data(),
    ]

    for file_path in dim_files:
        p = Path(file_path)
        assert p.exists()
        assert p.stat().st_size > 0

    assert cleanup_calls  # memory-management branch executed
    assert gen.generation_stats["records_generated"] > 0
    assert gen.generation_stats["chunks_processed"] > 0


def test_fact_generators_cover_sequential_parallel_and_chunk_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    gen = _make_small_generator(tmp_path)

    cleanup_calls: list[bool] = []
    monkeypatch.setattr(gen, "_check_memory_usage", lambda: True)
    monkeypatch.setattr(gen, "_cleanup_memory", lambda: cleanup_calls.append(True))

    # Sequential branch.
    facttrade_seq = Path(gen._generate_facttrade_data())
    assert facttrade_seq.exists()
    assert facttrade_seq.stat().st_size > 0

    # Parallel decision branch in _generate_facttrade_data (without huge output cost).
    gen.base_trades = 100001
    delegated: dict[str, int] = {}

    def _parallel_stub(
        file_path: Path,
        num_trades: int,
        num_accounts: int,
        num_securities: int,
        num_customers: int,
        num_companies: int,
    ) -> str:
        delegated["num_trades"] = num_trades
        file_path.write_text("1|1|1\n", encoding="utf-8")
        return str(file_path)

    monkeypatch.setattr(gen, "_generate_facttrade_parallel", _parallel_stub)
    facttrade_parallel = Path(gen._generate_facttrade_data())
    assert facttrade_parallel.exists()
    assert delegated["num_trades"] > 100000

    # Direct parallel implementation path with manageable size.
    real_parallel = Path(
        gen._generate_facttrade_parallel(
            tmp_path / "FactTradeParallel.tbl",
            num_trades=30,
            num_accounts=10,
            num_securities=10,
            num_customers=10,
            num_companies=5,
        )
    )
    assert real_parallel.exists()
    assert real_parallel.stat().st_size > 0

    # Trade chunk helper.
    chunk = gen._generate_trade_chunk(
        start_id=1,
        end_id=5,
        num_accounts=10,
        num_securities=10,
        num_customers=10,
        num_companies=5,
    )
    assert len(chunk) == 4

    # Remaining fact tables.
    other_facts = [
        Path(gen._generate_factcashbalances_data()),
        Path(gen._generate_factholdings_data()),
        Path(gen._generate_factmarkethistory_data()),
        Path(gen._generate_factwatches_data()),
    ]
    for p in other_facts:
        assert p.exists()
        assert p.stat().st_size > 0

    assert cleanup_calls
    assert gen.generation_stats["records_generated"] > 0
