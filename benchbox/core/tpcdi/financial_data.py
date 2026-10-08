# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-DI specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class FinancialConstants:
    TIER_1_PERCENTAGE = 0.15
    TIER_2_PERCENTAGE = 0.25
    TIER_3_PERCENTAGE = 0.60

    TAXABLE_ACCOUNTS_PERCENTAGE = 0.70
    TAX_DEFERRED_PERCENTAGE = 0.25
    TAX_FREE_PERCENTAGE = 0.05

    ACTIVE_TRADERS_PERCENTAGE = 0.20
    MODERATE_TRADERS_PERCENTAGE = 0.40
    PASSIVE_TRADERS_PERCENTAGE = 0.40

    MARKET_OPEN_HOUR = 9
    MARKET_OPEN_MINUTE = 30
    MARKET_CLOSE_HOUR = 16
    MARKET_CLOSE_MINUTE = 0

    MIN_CREDIT_SCORE = 300
    MAX_CREDIT_SCORE = 850
    PRIME_CREDIT_THRESHOLD = 660

    TIER_1_MIN_NET_WORTH = 1000000
    TIER_1_MAX_NET_WORTH = 50000000
    TIER_2_MIN_NET_WORTH = 100000
    TIER_2_MAX_NET_WORTH = 999999
    TIER_3_MIN_NET_WORTH = 1000
    TIER_3_MAX_NET_WORTH = 99999


class FinancialDataPatterns:
    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self.constants = FinancialConstants()

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

        self.sp_ratings = [
            ("AAA", 0.02),
            ("AA+", 0.03),
            ("AA", 0.05),
            ("AA-", 0.08),
            ("A+", 0.12),
            ("A", 0.15),
            ("A-", 0.18),
            ("BBB+", 0.15),
            ("BBB", 0.12),
            ("BBB-", 0.10),
        ]

        self.trade_types = [
            ("TMB", "Market Buy", False, True),
            ("TMS", "Market Sell", True, True),
            ("TLB", "Limit Buy", False, False),
            ("TLS", "Limit Sell", True, False),
            ("TSB", "Stop Buy", False, False),
            ("TSS", "Stop Sell", True, False),
        ]

        self.status_types = [
            ("ACTV", "Active"),
            ("INAC", "Inactive"),
            ("SUSP", "Suspended"),
            ("CLOS", "Closed"),
        ]

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

        self.us_states = [
            ("CA", 0.12),
            ("TX", 0.09),
            ("FL", 0.07),
            ("NY", 0.06),
            ("PA", 0.04),
            ("IL", 0.04),
            ("OH", 0.04),
            ("GA", 0.03),
            ("NC", 0.03),
            ("MI", 0.03),
        ]

    def generate_customer_tier(self) -> int:
        rand = self._rng.random()
        if rand < self.constants.TIER_1_PERCENTAGE:
            return 1
        elif rand < self.constants.TIER_1_PERCENTAGE + self.constants.TIER_2_PERCENTAGE:
            return 2
        else:
            return 3

    def generate_net_worth(self, tier: int) -> int:
        if tier == 1:
            base = self._rng.uniform(
                math.log(self.constants.TIER_1_MIN_NET_WORTH),
                math.log(self.constants.TIER_1_MAX_NET_WORTH),
            )
            return int(math.exp(base))
        elif tier == 2:
            return self._rng.randint(self.constants.TIER_2_MIN_NET_WORTH, self.constants.TIER_2_MAX_NET_WORTH)
        else:
            return self._rng.randint(self.constants.TIER_3_MIN_NET_WORTH, self.constants.TIER_3_MAX_NET_WORTH)

    def generate_credit_rating(self, tier: int, net_worth: int) -> int:
        if tier == 1:
            base_score = self._rng.randint(750, 850)
        elif tier == 2:
            base_score = self._rng.randint(680, 780)
        else:
            base_score = self._rng.randint(550, 720)

        net_worth_factor = min(net_worth / 100000, 1.0) * 50
        adjusted_score = base_score + int(net_worth_factor)

        return min(
            max(adjusted_score, self.constants.MIN_CREDIT_SCORE),
            self.constants.MAX_CREDIT_SCORE,
        )

    def generate_account_tax_status(self, customer_tier: int) -> int:
        rand = self._rng.random()

        if customer_tier == 1:
            if rand < 0.50:
                return 0
            elif rand < 0.80:
                return 1
            else:
                return 2
        elif customer_tier == 2:
            if rand < 0.65:
                return 0
            elif rand < 0.90:
                return 1
            else:
                return 2
        else:
            if rand < 0.80:
                return 0
            elif rand < 0.95:
                return 1
            else:
                return 2

    def generate_security_price(self, base_price: Optional[float] = None) -> float:
        if base_price is None:
            log_price = self._rng.normalvariate(math.log(50), 0.8)
            price = math.exp(log_price)
            return max(1.0, min(price, 1000.0))
        else:
            change_pct = self._rng.normalvariate(0, 0.02)
            new_price = base_price * (1 + change_pct)
            return max(0.01, new_price)

    def generate_trading_volume(self, market_cap_tier: int = 2) -> int:
        if market_cap_tier == 1:
            base_volume = self._rng.randint(1000000, 50000000)
        elif market_cap_tier == 2:
            base_volume = self._rng.randint(100000, 5000000)
        else:
            base_volume = self._rng.randint(10000, 500000)

        variation = self._rng.uniform(0.5, 2.0)
        return int(base_volume * variation)

    def generate_trade_quantity(self, customer_tier: int, security_price: float) -> int:

        if customer_tier == 1:
            typical_trade_value = self._rng.randint(50000, 500000)
        elif customer_tier == 2:
            typical_trade_value = self._rng.randint(10000, 100000)
        else:
            typical_trade_value = self._rng.randint(1000, 25000)

        base_quantity = int(typical_trade_value / security_price)

        if base_quantity >= 1000:
            quantity = (base_quantity // 100) * 100
        elif base_quantity >= 100:
            quantity = (base_quantity // 10) * 10
        else:
            quantity = base_quantity

        return max(1, quantity)

    def is_market_hours(self, hour: int, minute: int) -> bool:
        market_open = self.constants.MARKET_OPEN_HOUR * 60 + self.constants.MARKET_OPEN_MINUTE
        market_close = self.constants.MARKET_CLOSE_HOUR * 60 + self.constants.MARKET_CLOSE_MINUTE
        current_time = hour * 60 + minute

        return market_open <= current_time <= market_close

    def generate_trade_status_distribution(self) -> str:
        rand = self._rng.random()
        if rand < 0.85:
            return "Completed"
        elif rand < 0.95:
            return "Pending"
        else:
            return "Cancelled"

    def generate_company_sp_rating(self, industry_code: str) -> str:
        high_quality_industries = [
            "UTIL",
            "CONS",
            "HLTH",
        ]

        ratings = [rating for rating, _ in self.sp_ratings]
        weights = [weight for _, weight in self.sp_ratings]

        if industry_code in high_quality_industries:
            weights = [w * 1.5 if i < 5 else w * 0.7 for i, w in enumerate(weights)]

        total_weight = sum(weights)
        weights = [w / total_weight for w in weights]

        return self._rng.choices(ratings, weights=weights)[0]

    def generate_realistic_dates(self, start_date: date, end_date: date, num_dates: int) -> list[date]:
        dates = []
        date_range = (end_date - start_date).days

        for _ in range(num_dates):
            offset = self._rng.randint(0, date_range)
            candidate_date = start_date + timedelta(days=offset)

            if candidate_date.weekday() < 5:
                weight = 1.0
            else:
                weight = 0.1

            if self._rng.random() < weight:
                dates.append(candidate_date)

        dates = sorted(set(dates))

        while len(dates) < num_dates:
            offset = self._rng.randint(0, date_range)
            candidate_date = start_date + timedelta(days=offset)
            if candidate_date.weekday() < 5 and candidate_date not in dates:
                dates.append(candidate_date)

        return sorted(dates[:num_dates])

    def get_industry_data(self) -> list[tuple[str, str, str]]:
        return self.industries.copy()

    def get_status_types(self) -> list[tuple[str, str]]:
        return self.status_types.copy()

    def get_trade_types(self) -> list[tuple[str, str, bool, bool]]:
        return self.trade_types.copy()


def generate_realistic_tax_rates() -> list[tuple[str, str, float]]:
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
