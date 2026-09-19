"""Fact table generation mixin for TPC-DI."""

from __future__ import annotations

import csv
import hashlib
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from benchbox.utils.printing import emit

# Version of the deterministic FactTrade row algorithm below. Bump when the
# row layout or per-record randomness changes; the version is recorded in
# output metadata so consumers can tell comparable datasets apart.
FACT_TRADE_GENERATION_ALGORITHM_VERSION = 1


def _trade_record_rng(generation_seed: int, trade_id: int) -> random.Random:
    """Derive an independent RNG for one logical trade record.

    The stream depends only on the generation seed and the stable logical
    record identity (trade_id) -- never on worker count, chunk boundaries,
    task completion order, or process scheduling. Each instance is used by a
    single thread for a single record, so nothing mutable is shared across
    workers and the process-global random generator is never touched.

    Args:
        generation_seed: Explicit generation seed from the generation request.
        trade_id: Stable logical record identity (1-based trade sequence number).

    Returns:
        Dedicated random.Random instance for this record.
    """
    digest = hashlib.sha256(f"{generation_seed}:FactTrade:{trade_id}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


class FactGenerationMixin:
    """Generate fact table datasets for the TPC-DI benchmark."""

    def _generate_facttrade_data(self) -> str:
        """Generate the FactTrade fact table data with optimized chunked processing."""
        file_path = self.output_dir / "FactTrade.tbl"
        num_trades = int(self.base_trades * self.scale_factor)
        num_accounts = int(self.base_accounts * self.scale_factor)
        num_securities = int(self.base_securities * self.scale_factor)
        num_customers = int(self.base_customers * self.scale_factor)
        num_companies = int(self.base_companies * self.scale_factor)

        # For large scale factors, use multiple workers
        if num_trades > 100000 and self.max_workers > 1:
            return self._generate_facttrade_parallel(
                file_path,
                num_trades,
                num_accounts,
                num_securities,
                num_customers,
                num_companies,
            )

        with open(file_path, "w", newline="", buffering=self.buffer_size, encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="|")

            # Process in chunks for better memory management
            for chunk_start in range(1, num_trades + 1, self.chunk_size):
                chunk_end = min(chunk_start + self.chunk_size, num_trades + 1)
                chunk_rows = []

                for i in range(chunk_start, chunk_end):
                    rng = _trade_record_rng(self.generation_seed, i)
                    chunk_rows.append(
                        self._build_trade_row(
                            i,
                            rng,
                            num_accounts,
                            num_securities,
                            num_customers,
                            num_companies,
                        )
                    )

                writer.writerows(chunk_rows)
                # Simple progress logging
                if self.enable_progress:
                    self.logger.info(f"FactTrade: generated {chunk_end - 1:,} of {num_trades:,} records")
                self.generation_stats["chunks_processed"] += 1

                # Memory management for large datasets
                if self._check_memory_usage():
                    self._cleanup_memory()

        self.generation_stats["records_generated"] += num_trades
        file_path = self.compress_existing_file(file_path, remove_original=True)
        return str(file_path)

    def _generate_facttrade_parallel(
        self,
        file_path: Path,
        num_trades: int,
        num_accounts: int,
        num_securities: int,
        num_customers: int,
        num_companies: int,
    ) -> str:
        """Generate FactTrade data using parallel processing for large datasets."""
        if self.enable_progress:
            self.logger.info(f"Using parallel generation with {self.max_workers} workers")

        # Fixed logical partitions derived from chunk_size alone, never from
        # worker count: every worker count (including more workers than
        # partitions) schedules the same partitions, and per-record
        # randomness makes even the partition boundaries irrelevant to content.
        chunks = [(i, min(i + self.chunk_size, num_trades + 1)) for i in range(1, num_trades + 1, self.chunk_size)]

        # Generate chunks in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_chunk = {}

            for chunk_start, chunk_end in chunks:
                future = executor.submit(
                    self._generate_trade_chunk,
                    chunk_start,
                    chunk_end,
                    num_accounts,
                    num_securities,
                    num_customers,
                    num_companies,
                )
                future_to_chunk[future] = (chunk_start, chunk_end)

            # Collect results and write to file
            with open(file_path, "w", newline="", buffering=self.buffer_size, encoding="utf-8") as f:
                writer = csv.writer(f, delimiter="|")

                completed_chunks = []
                for future in as_completed(future_to_chunk):
                    chunk_start, chunk_end = future_to_chunk[future]
                    try:
                        chunk_data = future.result()
                        completed_chunks.append((chunk_start, chunk_data))
                    except Exception as e:
                        emit(f"Error generating chunk {chunk_start}-{chunk_end}: {e}")
                        raise

                # Sort chunks by start position and write in order
                completed_chunks.sort(key=lambda x: x[0])
                for _, chunk_data in completed_chunks:
                    writer.writerows(chunk_data)

        self.generation_stats["records_generated"] += num_trades
        file_path = self.compress_existing_file(file_path, remove_original=True)
        return str(file_path)

    def _generate_trade_chunk(
        self,
        start_id: int,
        end_id: int,
        num_accounts: int,
        num_securities: int,
        num_customers: int,
        num_companies: int,
    ) -> list[list]:
        """Generate a chunk of trade data.

        Rows are built with the same deterministic per-record algorithm as
        the serial path, so chunk boundaries and scheduling never affect
        content.
        """
        chunk_data = []

        for i in range(start_id, end_id):
            rng = _trade_record_rng(self.generation_seed, i)
            chunk_data.append(
                self._build_trade_row(
                    i,
                    rng,
                    num_accounts,
                    num_securities,
                    num_customers,
                    num_companies,
                )
            )

        return chunk_data

    def _build_trade_row(
        self,
        trade_id: int,
        rng: random.Random,
        num_accounts: int,
        num_securities: int,
        num_customers: int,
        num_companies: int,
    ) -> list:
        """Build one FactTrade row from its dedicated per-record RNG.

        This is the single deterministic row algorithm shared by serial and
        parallel generation: identical (seed, trade_id, dimension sizes)
        always yields an identical row.

        Args:
            trade_id: Stable logical record identity (1-based).
            rng: Dedicated RNG derived from the generation seed and trade_id.
            num_accounts: Account dimension size bound.
            num_securities: Security dimension size bound.
            num_customers: Customer dimension size bound.
            num_companies: Company dimension size bound.

        Returns:
            The trade row as a list of column values.
        """
        sk_broker_id = rng.randint(1, 100)
        sk_create_date_id = rng.randint(1, 5844)  # Assuming DimDate has ~16 years
        sk_create_time_id = rng.randint(1, 288)  # 24 hours * 12 (5-min intervals)
        sk_close_date_id = sk_create_date_id + rng.randint(0, 5)
        sk_close_time_id = rng.randint(1, 288)

        status = rng.choices(["Completed", "Pending", "Cancelled"], weights=[0.8, 0.1, 0.1])[0]
        trade_type = rng.choice(self._trade_types)
        cash_flag = rng.choice([True, False])
        sk_security_id = rng.randint(1, num_securities)
        sk_company_id = rng.randint(1, num_companies)
        quantity = rng.randint(1, 10000)
        bid_price = round(rng.uniform(10.0, 500.0), 2)
        sk_customer_id = rng.randint(1, num_customers)
        sk_account_id = rng.randint(1, num_accounts)
        executed_by = f"Broker{rng.randint(1, 100)}"
        trade_price = round(bid_price * rng.uniform(0.98, 1.02), 2)
        fee = round(rng.uniform(5.0, 50.0), 2)
        commission = round(trade_price * quantity * 0.001, 2)  # 0.1% commission
        tax = round(trade_price * quantity * 0.01, 2) if status == "Completed" else 0.0
        batch_id = 1

        return [
            trade_id,
            sk_broker_id,
            sk_create_date_id,
            sk_create_time_id,
            sk_close_date_id,
            sk_close_time_id,
            status,
            trade_type,
            cash_flag,
            sk_security_id,
            sk_company_id,
            quantity,
            bid_price,
            sk_customer_id,
            sk_account_id,
            executed_by,
            trade_price,
            fee,
            commission,
            tax,
            batch_id,
        ]

    def _generate_factcashbalances_data(self) -> str:
        """Generate FactCashBalances data with realistic cash balance patterns."""
        file_path = self.output_dir / "FactCashBalances.tbl"
        num_customers = int(self.base_customers * self.scale_factor)
        num_accounts = int(self.base_accounts * self.scale_factor)

        # Generate balances for a subset of date/customer/account combinations
        num_records = min(num_accounts * 30, 100000)  # ~30 days per account, cap at 100k

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="|")

            for _i in range(num_records):
                sk_customer_id = random.randint(1, num_customers)
                sk_account_id = random.randint(1, num_accounts)
                sk_date_id = random.randint(1, 5844)  # Date range

                # Generate realistic cash balance based on customer tier
                customer_tier = self.financial_patterns.generate_customer_tier()
                if customer_tier == 1:
                    cash_balance = round(random.uniform(10000, 500000), 2)
                elif customer_tier == 2:
                    cash_balance = round(random.uniform(1000, 50000), 2)
                else:
                    cash_balance = round(random.uniform(100, 10000), 2)

                batch_id = 1

                row = [
                    sk_customer_id,
                    sk_account_id,
                    sk_date_id,
                    cash_balance,
                    batch_id,
                ]
                writer.writerow(row)

        self.generation_stats["records_generated"] += num_records
        file_path = self.compress_existing_file(file_path, remove_original=True)
        return str(file_path)

    def _generate_factholdings_data(self) -> str:
        """Generate FactHoldings data with realistic position data."""
        file_path = self.output_dir / "FactHoldings.tbl"
        num_customers = int(self.base_customers * self.scale_factor)
        num_accounts = int(self.base_accounts * self.scale_factor)
        num_securities = int(self.base_securities * self.scale_factor)
        num_companies = int(self.base_companies * self.scale_factor)

        # Generate holdings for a subset of combinations
        num_records = min(num_accounts * 10, 50000)  # ~10 holdings per account

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="|")

            for _i in range(num_records):
                sk_customer_id = random.randint(1, num_customers)
                sk_account_id = random.randint(1, num_accounts)
                sk_security_id = random.randint(1, num_securities)
                sk_company_id = random.randint(1, num_companies)
                sk_date_id = random.randint(1, 5844)
                sk_time_id = random.randint(1, 288)

                # Generate realistic current price and holdings
                current_price = round(self.financial_patterns.generate_security_price(), 2)

                # Generate realistic holdings quantity
                customer_tier = self.financial_patterns.generate_customer_tier()
                current_holding = self.financial_patterns.generate_trade_quantity(customer_tier, current_price)

                batch_id = 1

                row = [
                    sk_customer_id,
                    sk_account_id,
                    sk_security_id,
                    sk_company_id,
                    sk_date_id,
                    sk_time_id,
                    current_price,
                    current_holding,
                    batch_id,
                ]
                writer.writerow(row)

        self.generation_stats["records_generated"] += num_records
        file_path = self.compress_existing_file(file_path, remove_original=True)
        return str(file_path)

    def _generate_factmarkethistory_data(self) -> str:
        """Generate FactMarketHistory data with realistic market data."""
        file_path = self.output_dir / "FactMarketHistory.tbl"
        num_securities = int(self.base_securities * self.scale_factor)
        num_companies = int(self.base_companies * self.scale_factor)

        # Generate market history for securities over time
        # Roughly 252 trading days per year * num_securities
        days_of_data = min(252, int(252 * self.scale_factor))
        num_records = min(num_securities * days_of_data, 100000)

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="|")

            # Track prices for price evolution
            security_prices = {}

            for _i in range(num_records):
                sk_security_id = random.randint(1, num_securities)
                sk_company_id = random.randint(1, num_companies)
                sk_date_id = random.randint(1, 5844)

                # Generate or evolve security price
                if sk_security_id not in security_prices:
                    base_price = self.financial_patterns.generate_security_price()
                    security_prices[sk_security_id] = base_price
                else:
                    base_price = security_prices[sk_security_id]
                    # Evolve price slightly
                    base_price = self.financial_patterns.generate_security_price(base_price)
                    security_prices[sk_security_id] = base_price

                close_price = round(base_price, 2)
                day_high = round(base_price * random.uniform(1.0, 1.05), 2)
                day_low = round(base_price * random.uniform(0.95, 1.0), 2)

                # Generate other market metrics
                pe_ratio = round(random.uniform(5, 50), 2) if random.random() > 0.1 else None
                dividend_yield = round(random.uniform(0, 0.08), 4)

                # 52-week high/low (simplified)
                fifty_two_week_high = round(close_price * random.uniform(1.1, 2.0), 2)
                fifty_two_week_low = round(close_price * random.uniform(0.5, 0.9), 2)
                sk_52week_high_date = random.randint(1, 5844)
                sk_52week_low_date = random.randint(1, 5844)

                dividend_per_share = round(close_price * dividend_yield / 4, 4)  # Quarterly
                volume = self.financial_patterns.generate_trading_volume()
                batch_id = 1

                row = [
                    sk_security_id,
                    sk_company_id,
                    sk_date_id,
                    pe_ratio,
                    dividend_yield,
                    fifty_two_week_high,
                    sk_52week_high_date,
                    fifty_two_week_low,
                    sk_52week_low_date,
                    dividend_per_share,
                    close_price,
                    day_high,
                    day_low,
                    volume,
                    batch_id,
                ]
                writer.writerow(row)

        self.generation_stats["records_generated"] += num_records
        file_path = self.compress_existing_file(file_path, remove_original=True)
        return str(file_path)

    def _generate_factwatches_data(self) -> str:
        """Generate FactWatches data for customer watch lists."""
        file_path = self.output_dir / "FactWatches.tbl"
        num_customers = int(self.base_customers * self.scale_factor)
        num_securities = int(self.base_securities * self.scale_factor)

        # Generate watch list entries (each customer watches ~5 securities on average)
        num_records = min(int(num_customers * 5 * self.scale_factor), 25000)

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="|")

            for _i in range(num_records):
                sk_customer_id = random.randint(1, num_customers)
                sk_security_id = random.randint(1, num_securities)
                sk_date_placed = random.randint(1, 5844)

                # Some watches are removed (30% chance)
                sk_date_removed = random.randint(sk_date_placed, 5844) if random.random() < 0.3 else None

                batch_id = 1

                row = [
                    sk_customer_id,
                    sk_security_id,
                    sk_date_placed,
                    sk_date_removed,
                    batch_id,
                ]
                writer.writerow(row)

        self.generation_stats["records_generated"] += num_records
        file_path = self.compress_existing_file(file_path, remove_original=True)
        return str(file_path)


__all__ = ["FactGenerationMixin"]
