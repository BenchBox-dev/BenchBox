"""Realistic financial data patterns for TPC-DI benchmark.

This module provides realistic financial data distributions, patterns, and business rules
that align with actual financial services industry data. Used to generate more realistic
TPC-DI benchmark data instead of purely synthetic patterns.

Features:
- Industry-standard financial data distributions
- Realistic customer demographics and tiers
- Market-realistic security prices and trading patterns
- Temporal consistency for financial data
- Business rule validation patterns

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class FinancialConstants:
    """Constants for realistic financial data generation."""

    # Customer tier distributions (based on industry data)
    TIER_1_PERCENTAGE = 0.15  # High net worth (15%)
    TIER_2_PERCENTAGE = 0.25  # Medium net worth (25%)
    TIER_3_PERCENTAGE = 0.60  # Standard customers (60%)

    # Account types and distributions
    TAXABLE_ACCOUNTS_PERCENTAGE = 0.70  # 70% taxable accounts
    TAX_DEFERRED_PERCENTAGE = 0.25  # 25% tax-deferred (401k, IRA)
    TAX_FREE_PERCENTAGE = 0.05  # 5% tax-free (Roth IRA)

    # Trading patterns
    ACTIVE_TRADERS_PERCENTAGE = 0.20  # 20% of customers trade actively
    MODERATE_TRADERS_PERCENTAGE = 0.40  # 40% trade moderately
    PASSIVE_TRADERS_PERCENTAGE = 0.40  # 40% trade infrequently

    # Market hours (US Eastern Time)
    MARKET_OPEN_HOUR = 9
    MARKET_OPEN_MINUTE = 30
    MARKET_CLOSE_HOUR = 16
    MARKET_CLOSE_MINUTE = 0

    # Credit rating ranges
    MIN_CREDIT_SCORE = 300
    MAX_CREDIT_SCORE = 850
    PRIME_CREDIT_THRESHOLD = 660

    # Net worth ranges by tier (in dollars)
    TIER_1_MIN_NET_WORTH = 1000000  # $1M+
    TIER_1_MAX_NET_WORTH = 50000000  # $50M
    TIER_2_MIN_NET_WORTH = 100000  # $100K
    TIER_2_MAX_NET_WORTH = 999999  # $999K
    TIER_3_MIN_NET_WORTH = 1000  # $1K
    TIER_3_MAX_NET_WORTH = 99999  # $99K


class FinancialDataPatterns:
    """Generate realistic financial data patterns for TPC-DI."""

    def __init__(self, seed: int = 42):
        """Initialize with consistent random seed for reproducible data.

        The seed feeds a private random.Random instance owned by this
        object; the process-global random generator is never seeded or
        otherwise mutated here.

        Args:
            seed: Random seed for reproducible generation
        """
        self._rng = random.Random(seed)
        self.constants = FinancialConstants()

        # Pre-define realistic industry classifications
        self.industries = [
            ("01", "Technology", "TECH"),
            ("02", "Healthcare", "HLTH"),
            ("03", "Financial Services", "FINS"),
            ("04", "Manufacturing", "MANF"),
            ("05", "Consumer Discretionary", "COND"),
            ("06", "Consumer Staples", "CONS"),
            ("07", "Energy", "ENRG"),
            ("08", "Utilities", "UTIL"),
            ("09", "Real Estate", "REAL"),
            ("10", "Materials", "MATL"),
            ("11", "Industrials", "INDU"),
            ("12", "Telecommunications", "TELE"),
        ]

        # S&P credit ratings with realistic distributions
        self.sp_ratings = [
            ("AAA", 0.02),  # 2% - Highest grade
            ("AA+", 0.03),  # 3%
            ("AA", 0.05),  # 5%
            ("AA-", 0.08),  # 8%
            ("A+", 0.12),  # 12%
            ("A", 0.15),  # 15%
            ("A-", 0.18),  # 18%
            ("BBB+", 0.15),  # 15%
            ("BBB", 0.12),  # 12%
            ("BBB-", 0.10),  # 10% - Investment grade cutoff
        ]

        # Trade types with market behavior
        self.trade_types = [
            ("TMB", "Market Buy", False, True),  # Market buy
            ("TMS", "Market Sell", True, True),  # Market sell
            ("TLB", "Limit Buy", False, False),  # Limit buy
            ("TLS", "Limit Sell", True, False),  # Limit sell
            ("TSB", "Stop Buy", False, False),  # Stop buy
            ("TSS", "Stop Sell", True, False),  # Stop sell
        ]

        # Status types for various entities
        self.status_types = [
            ("ACTV", "Active"),
            ("INAC", "Inactive"),
            ("SUSP", "Suspended"),
            ("CLOS", "Closed"),
        ]

        # Realistic first and last names for customers
        self.first_names = [
            "James",
            "Mary",
            "John",
            "Patricia",
            "Robert",
            "Jennifer",
            "Michael",
            "Linda",
            "William",
            "Elizabeth",
            "David",
            "Barbara",
            "Richard",
            "Susan",
            "Joseph",
            "Jessica",
            "Thomas",
            "Sarah",
            "Christopher",
            "Karen",
            "Charles",
            "Nancy",
            "Daniel",
            "Lisa",
            "Matthew",
            "Betty",
            "Anthony",
            "Helen",
            "Mark",
            "Sandra",
            "Donald",
            "Donna",
        ]

        self.last_names = [
            "Smith",
            "Johnson",
            "Williams",
            "Brown",
            "Jones",
            "Garcia",
            "Miller",
            "Davis",
            "Rodriguez",
            "Martinez",
            "Hernandez",
            "Lopez",
            "Gonzalez",
            "Wilson",
            "Anderson",
            "Thomas",
            "Taylor",
            "Moore",
            "Jackson",
            "Martin",
            "Lee",
            "Perez",
            "Thompson",
            "White",
            "Harris",
            "Sanchez",
            "Clark",
            "Ramirez",
            "Lewis",
            "Robinson",
            "Walker",
        ]

        # US states with realistic population distributions
        self.us_states = [
            ("CA", 0.12),  # California - 12% of customers
            ("TX", 0.09),  # Texas - 9%
            ("FL", 0.07),  # Florida - 7%
            ("NY", 0.06),  # York - 6%
            ("PA", 0.04),  # Pennsylvania - 4%
            ("IL", 0.04),  # Illinois - 4%
            ("OH", 0.04),  # Ohio - 4%
            ("GA", 0.03),  # Georgia - 3%
            ("NC", 0.03),  # North Carolina - 3%
            ("MI", 0.03),  # Michigan - 3%
        ]

    def generate_customer_tier(self) -> int:
        """Generate customer tier based on realistic wealth distribution.

        Returns:
            Customer tier (1=highest, 3=standard)
        """
        rand = self._rng.random()
        if rand < self.constants.TIER_1_PERCENTAGE:
            return 1
        elif rand < self.constants.TIER_1_PERCENTAGE + self.constants.TIER_2_PERCENTAGE:
            return 2
        else:
            return 3

    def generate_net_worth(self, tier: int) -> int:
        """Generate realistic net worth based on customer tier.

        Args:
            tier: Customer tier (1-3)

        Returns:
            Net worth in dollars
        """
        if tier == 1:
            # High net worth - log-normal distribution
            base = self._rng.uniform(
                math.log(self.constants.TIER_1_MIN_NET_WORTH),
                math.log(self.constants.TIER_1_MAX_NET_WORTH),
            )
            return int(math.exp(base))
        elif tier == 2:
            # Medium net worth - more uniform distribution
            return self._rng.randint(self.constants.TIER_2_MIN_NET_WORTH, self.constants.TIER_2_MAX_NET_WORTH)
        else:
            # Standard customers - lower range
            return self._rng.randint(self.constants.TIER_3_MIN_NET_WORTH, self.constants.TIER_3_MAX_NET_WORTH)

    def generate_credit_rating(self, tier: int, net_worth: int) -> int:
        """Generate realistic credit rating correlated with tier and net worth.

        Args:
            tier: Customer tier (1-3)
            net_worth: Customer net worth

        Returns:
            Credit score (300-850)
        """
        # Higher tier customers tend to have better credit
        if tier == 1:
            base_score = self._rng.randint(750, 850)
        elif tier == 2:
            base_score = self._rng.randint(680, 780)
        else:
            base_score = self._rng.randint(550, 720)

        # Add some correlation with net worth
        net_worth_factor = min(net_worth / 100000, 1.0) * 50  # Up to 50 point bonus
        adjusted_score = base_score + int(net_worth_factor)

        # Clamp to valid range
        return min(
            max(adjusted_score, self.constants.MIN_CREDIT_SCORE),
            self.constants.MAX_CREDIT_SCORE,
        )

    def generate_account_tax_status(self, customer_tier: int) -> int:
        """Generate tax status based on customer tier and realistic distributions.

        Args:
            customer_tier: Customer tier (1-3)

        Returns:
            Tax status (0=Taxable, 1=Tax Deferred, 2=Tax Free)
        """
        # Higher tier customers more likely to have tax-advantaged accounts
        rand = self._rng.random()

        if customer_tier == 1:
            # High net worth - more tax-advantaged accounts
            if rand < 0.50:
                return 0  # Taxable
            elif rand < 0.80:
                return 1  # Tax deferred
            else:
                return 2  # Tax free
        elif customer_tier == 2:
            # Medium net worth - moderate tax-advantaged accounts
            if rand < 0.65:
                return 0  # Taxable
            elif rand < 0.90:
                return 1  # Tax deferred
            else:
                return 2  # Tax free
        else:
            # Standard customers - mostly taxable
            if rand < 0.80:
                return 0  # Taxable
            elif rand < 0.95:
                return 1  # Tax deferred
            else:
                return 2  # Tax free

    def generate_security_price(self, base_price: Optional[float] = None) -> float:
        """Generate realistic security price.

        Args:
            base_price: Optional base price for price evolution

        Returns:
            Security price
        """
        if base_price is None:
            # Initial price - log-normal distribution
            # Most stocks between $10-200, some outliers
            log_price = self._rng.normalvariate(math.log(50), 0.8)
            price = math.exp(log_price)
            return max(1.0, min(price, 1000.0))  # Clamp to reasonable range
        else:
            # Price evolution - small random walk
            change_pct = self._rng.normalvariate(0, 0.02)  # 2% daily volatility
            new_price = base_price * (1 + change_pct)
            return max(0.01, new_price)  # Minimum $0.01

    def generate_trading_volume(self, market_cap_tier: int = 2) -> int:
        """Generate realistic trading volume based on market cap tier.

        Args:
            market_cap_tier: Market cap tier (1=large cap, 2=mid cap, 3=small cap)

        Returns:
            Trading volume (shares)
        """
        if market_cap_tier == 1:
            # Large cap - high volume
            base_volume = self._rng.randint(1000000, 50000000)
        elif market_cap_tier == 2:
            # Mid cap - medium volume
            base_volume = self._rng.randint(100000, 5000000)
        else:
            # Small cap - lower volume
            base_volume = self._rng.randint(10000, 500000)

        # Add some daily variation
        variation = self._rng.uniform(0.5, 2.0)
        return int(base_volume * variation)

    def generate_trade_quantity(self, customer_tier: int, security_price: float) -> int:
        """Generate realistic trade quantity based on customer tier and security price.

        Args:
            customer_tier: Customer tier (1-3)
            security_price: Current security price

        Returns:
            Trade quantity (shares)
        """
        # Higher tier customers make larger trades
        # Also consider typical trade sizes for price ranges

        if customer_tier == 1:
            # High net worth - larger trades
            typical_trade_value = self._rng.randint(50000, 500000)
        elif customer_tier == 2:
            # Medium net worth - medium trades
            typical_trade_value = self._rng.randint(10000, 100000)
        else:
            # Standard customers - smaller trades
            typical_trade_value = self._rng.randint(1000, 25000)

        # Calculate shares based on typical dollar amount
        base_quantity = int(typical_trade_value / security_price)

        # Round to typical lot sizes
        if base_quantity >= 1000:
            # Round to hundreds
            quantity = (base_quantity // 100) * 100
        elif base_quantity >= 100:
            # Round to tens
            quantity = (base_quantity // 10) * 10
        else:
            # Keep as-is for small quantities
            quantity = base_quantity

        return max(1, quantity)  # Minimum 1 share

    def is_market_hours(self, hour: int, minute: int) -> bool:
        """Check if given time is during market hours.

        Args:
            hour: Hour (0-23)
            minute: Minute (0-59)

        Returns:
            True if during market hours
        """
        market_open = self.constants.MARKET_OPEN_HOUR * 60 + self.constants.MARKET_OPEN_MINUTE
        market_close = self.constants.MARKET_CLOSE_HOUR * 60 + self.constants.MARKET_CLOSE_MINUTE
        current_time = hour * 60 + minute

        return market_open <= current_time <= market_close

    def generate_trade_status_distribution(self) -> str:
        """Generate trade status based on realistic completion rates.

        Returns:
            Trade status
        """
        rand = self._rng.random()
        if rand < 0.85:
            return "Completed"  # 85% complete
        elif rand < 0.95:
            return "Pending"  # 10% pending
        else:
            return "Cancelled"  # 5% cancelled

    def generate_company_sp_rating(self, industry_code: str) -> str:
        """Generate S&P rating based on industry and realistic distributions.

        Args:
            industry_code: Industry code

        Returns:
            S&P credit rating
        """
        # Some industries tend to have better credit ratings
        high_quality_industries = [
            "UTIL",
            "CONS",
            "HLTH",
        ]  # Utilities, staples, healthcare

        ratings = [rating for rating, _ in self.sp_ratings]
        weights = [weight for _, weight in self.sp_ratings]

        if industry_code in high_quality_industries:
            # Shift distribution toward higher ratings
            weights = [w * 1.5 if i < 5 else w * 0.7 for i, w in enumerate(weights)]

        # Normalize weights
        total_weight = sum(weights)
        weights = [w / total_weight for w in weights]

        return self._rng.choices(ratings, weights=weights)[0]

    def generate_realistic_dates(self, start_date: date, end_date: date, num_dates: int) -> list[date]:
        """Generate realistic business dates with proper weighting.

        Args:
            start_date: Start date
            end_date: End date
            num_dates: Number of dates to generate

        Returns:
            List of dates with realistic distribution
        """
        dates = []
        date_range = (end_date - start_date).days

        for _ in range(num_dates):
            # Generate random offset
            offset = self._rng.randint(0, date_range)
            candidate_date = start_date + timedelta(days=offset)

            # Bias against weekends (less trading activity)
            if candidate_date.weekday() < 5:  # Monday = 0, Friday = 4
                weight = 1.0
            else:
                weight = 0.1  # Much less weekend activity

            if self._rng.random() < weight:
                dates.append(candidate_date)

        # Remove duplicates and sort
        dates = sorted(set(dates))

        # If we don't have enough dates, fill in more weekdays
        while len(dates) < num_dates:
            offset = self._rng.randint(0, date_range)
            candidate_date = start_date + timedelta(days=offset)
            if candidate_date.weekday() < 5 and candidate_date not in dates:
                dates.append(candidate_date)

        return sorted(dates[:num_dates])

    def get_industry_data(self) -> list[tuple[str, str, str]]:
        """Get industry classification data.

        Returns:
            List of (industry_id, industry_name, sector_code) tuples
        """
        return self.industries.copy()

    def get_status_types(self) -> list[tuple[str, str]]:
        """Get status type data.

        Returns:
            List of (status_id, status_name) tuples
        """
        return self.status_types.copy()

    def get_trade_types(self) -> list[tuple[str, str, bool, bool]]:
        """Get trade type data.

        Returns:
            List of (type_id, type_name, is_sell, is_market) tuples
        """
        return self.trade_types.copy()


def generate_realistic_tax_rates() -> list[tuple[str, str, float]]:
    """Generate realistic tax rate data.

    Returns:
        List of (tax_id, tax_name, tax_rate) tuples
    """
    return [
        ("TX01", "Federal Income Tax", 0.24),
        ("TX02", "State Income Tax CA", 0.093),
        ("TX03", "State Income Tax NY", 0.082),
        ("TX04", "State Income Tax TX", 0.0),
        ("TX05", "State Income Tax FL", 0.0),
        ("TX06", "FICA Social Security", 0.062),
        ("TX07", "FICA Medicare", 0.0145),
        ("TX08", "Short Term Capital Gains", 0.37),
        ("TX09", "Long Term Capital Gains", 0.20),
        ("TX10", "Municipal Bond Interest", 0.0),
    ]
