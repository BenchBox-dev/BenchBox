"""Tests for the TCO (Total Cost of Ownership) calculator module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.cost.models import BenchmarkCost
from benchbox.core.cost.tco import (
    BudgetAlert,
    BudgetThreshold,
    DiscountConfig,
    DiscountType,
    GrowthConfig,
    GrowthModel,
    TCOCalculator,
    TCOProjection,
    YearlyProjection,
    create_standard_tco_scenarios,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGrowthModel:
    """Tests for GrowthModel enum."""

    def test_growth_model_values(self):

        assert GrowthModel.NONE.value == "none"
        assert GrowthModel.LINEAR.value == "linear"
        assert GrowthModel.COMPOUND.value == "compound"


class TestGrowthConfig:
    """Tests for GrowthConfig dataclass."""

    def test_default_config(self):

        config = GrowthConfig()

        assert config.model == GrowthModel.NONE
        assert config.annual_rate == 0.0
        assert config.data_growth_rate is None

    def test_custom_config(self):

        config = GrowthConfig(
            model=GrowthModel.COMPOUND,
            annual_rate=0.15,
            data_growth_rate=0.20,
        )

        assert config.model == GrowthModel.COMPOUND
        assert config.annual_rate == 0.15
        assert config.data_growth_rate == 0.20

    def test_get_data_growth_rate_with_value(self):

        config = GrowthConfig(annual_rate=0.10, data_growth_rate=0.20)
        assert config.get_data_growth_rate() == 0.20

    def test_get_data_growth_rate_defaults_to_annual(self):

        config = GrowthConfig(annual_rate=0.10)
        assert config.get_data_growth_rate() == 0.10

    def test_calculate_multiplier_no_growth(self):

        config = GrowthConfig(model=GrowthModel.NONE, annual_rate=0.10)

        # All years should return 1.0
        assert config.calculate_multiplier(1) == 1.0
        assert config.calculate_multiplier(2) == 1.0
        assert config.calculate_multiplier(5) == 1.0

    def test_calculate_multiplier_first_year(self):
        """Test multiplier for first year is always 1.0."""
        # Even with growth, year 1 starts at base cost
        config = GrowthConfig(model=GrowthModel.COMPOUND, annual_rate=0.10)
        assert config.calculate_multiplier(1) == 1.0

    def test_calculate_multiplier_linear(self):

        config = GrowthConfig(model=GrowthModel.LINEAR, annual_rate=0.10)

        # Year 1: base (1.0)
        # Year 2: base + 10% = 1.1
        # Year 3: base + 20% = 1.2
        # Year 5: base + 40% = 1.4
        assert config.calculate_multiplier(1) == 1.0
        assert config.calculate_multiplier(2) == pytest.approx(1.1, rel=0.001)
        assert config.calculate_multiplier(3) == pytest.approx(1.2, rel=0.001)
        assert config.calculate_multiplier(5) == pytest.approx(1.4, rel=0.001)

    def test_calculate_multiplier_compound(self):

        config = GrowthConfig(model=GrowthModel.COMPOUND, annual_rate=0.10)

        # Year 1: base (1.0)
        # Year 2: base * 1.1 = 1.1
        # Year 3: base * 1.1^2 = 1.21
        # Year 5: base * 1.1^4 = 1.4641
        assert config.calculate_multiplier(1) == 1.0
        assert config.calculate_multiplier(2) == pytest.approx(1.1, rel=0.001)
        assert config.calculate_multiplier(3) == pytest.approx(1.21, rel=0.001)
        assert config.calculate_multiplier(5) == pytest.approx(1.4641, rel=0.001)


class TestDiscountType:
    """Tests for DiscountType enum."""

    def test_discount_type_values(self):

        assert DiscountType.NONE.value == "none"
        assert DiscountType.RESERVED.value == "reserved"
        assert DiscountType.COMMITTED_USE.value == "committed_use"
        assert DiscountType.ENTERPRISE.value == "enterprise"
        assert DiscountType.VOLUME.value == "volume"


class TestDiscountConfig:
    """Tests for DiscountConfig dataclass."""

    def test_default_config(self):

        config = DiscountConfig()

        assert config.discount_type == DiscountType.NONE
        assert config.discount_percent == 0.0
        assert config.commitment_years == 1
        assert config.effective_start_year == 1

    def test_custom_config(self):

        config = DiscountConfig(
            discount_type=DiscountType.RESERVED,
            discount_percent=0.30,
            commitment_years=3,
            effective_start_year=2,
        )

        assert config.discount_type == DiscountType.RESERVED
        assert config.discount_percent == 0.30
        assert config.commitment_years == 3
        assert config.effective_start_year == 2

    def test_get_discount_multiplier_no_discount(self):

        config = DiscountConfig(discount_type=DiscountType.NONE)

        # All years should return 1.0
        assert config.get_discount_multiplier(1) == 1.0
        assert config.get_discount_multiplier(5) == 1.0

    def test_get_discount_multiplier_with_discount(self):

        config = DiscountConfig(
            discount_type=DiscountType.RESERVED,
            discount_percent=0.20,
        )

        # 20% discount means pay 80%
        assert config.get_discount_multiplier(1) == 0.80
        assert config.get_discount_multiplier(5) == 0.80

    def test_get_discount_multiplier_delayed_start(self):

        config = DiscountConfig(
            discount_type=DiscountType.COMMITTED_USE,
            discount_percent=0.25,
            effective_start_year=2,
        )

        # Year 1: no discount (before effective)
        assert config.get_discount_multiplier(1) == 1.0
        # Year 2+: 25% discount
        assert config.get_discount_multiplier(2) == 0.75
        assert config.get_discount_multiplier(5) == 0.75


class TestBudgetThreshold:
    """Tests for BudgetThreshold dataclass."""

    def test_create_threshold(self):
        """Test creating a budget threshold."""
        threshold = BudgetThreshold(
            name="warning",
            amount=100000.0,
            period="annual",
        )

        assert threshold.name == "warning"
        assert threshold.amount == 100000.0
        assert threshold.period == "annual"

    def test_default_period(self):

        threshold = BudgetThreshold(name="test", amount=50000.0)
        assert threshold.period == "annual"

    def test_is_exceeded_same_period(self):

        threshold = BudgetThreshold(name="test", amount=10000.0, period="annual")

        assert threshold.is_exceeded(5000.0, "annual") is False
        assert threshold.is_exceeded(10000.0, "annual") is False  # Equal is not exceeded
        assert threshold.is_exceeded(10001.0, "annual") is True

    def test_is_exceeded_monthly_to_annual(self):

        threshold = BudgetThreshold(name="test", amount=12000.0, period="annual")

        # $1000/month = $12000/year (at threshold)
        assert threshold.is_exceeded(1000.0, "monthly") is False
        # $1001/month = $12012/year (exceeds)
        assert threshold.is_exceeded(1001.0, "monthly") is True

    def test_is_exceeded_annual_to_monthly(self):

        threshold = BudgetThreshold(name="test", amount=1000.0, period="monthly")

        # $12000/year = $1000/month (at threshold)
        assert threshold.is_exceeded(12000.0, "annual") is False
        # $12012/year = $1001/month (exceeds)
        assert threshold.is_exceeded(12012.0, "annual") is True


class TestBudgetAlert:
    """Tests for BudgetAlert dataclass."""

    def test_create_alert(self):
        """Test creating a budget alert."""
        threshold = BudgetThreshold(name="critical", amount=50000.0)
        alert = BudgetAlert(
            threshold=threshold,
            actual_cost=60000.0,
            year=2,
            period="annual",
            message="Budget exceeded in year 2",
        )

        assert alert.threshold == threshold
        assert alert.actual_cost == 60000.0
        assert alert.year == 2
        assert alert.period == "annual"
        assert "Budget exceeded" in alert.message


class TestYearlyProjection:
    """Tests for YearlyProjection dataclass."""

    def test_create_projection(self):

        projection = YearlyProjection(
            year=1,
            calendar_year=2025,
            base_cost=100000.0,
            growth_multiplier=1.0,
            discount_multiplier=0.85,
            projected_cost=85000.0,
            cumulative_cost=85000.0,
            monthly_cost=7083.33,
        )

        assert projection.year == 1
        assert projection.calendar_year == 2025
        assert projection.projected_cost == 85000.0

    def test_to_dict(self):

        projection = YearlyProjection(
            year=2,
            calendar_year=2026,
            base_cost=100000.0,
            growth_multiplier=1.1,
            discount_multiplier=0.85,
            projected_cost=93500.0,
            cumulative_cost=178500.0,
            monthly_cost=7791.67,
        )

        result = projection.to_dict()

        assert result["year"] == 2
        assert result["calendar_year"] == 2026
        assert result["base_cost"] == 100000.0
        assert result["growth_multiplier"] == 1.1
        assert result["discount_multiplier"] == 0.85
        assert result["projected_cost"] == 93500.0
        assert result["cumulative_cost"] == 178500.0


class TestTCOProjection:
    """Tests for TCOProjection dataclass."""

    def test_default_projection(self):

        projection = TCOProjection(
            platform="snowflake",
            base_annual_cost=100000.0,
        )

        assert projection.platform == "snowflake"
        assert projection.base_annual_cost == 100000.0
        assert projection.currency == "USD"
        assert projection.projection_years == 5
        assert projection.total_tco == 0.0
        assert projection.yearly_projections == []
        assert projection.budget_alerts == []

    def test_to_dict(self):

        projection = TCOProjection(
            platform="bigquery",
            base_annual_cost=50000.0,
            currency="USD",
            projection_years=3,
            start_year=2025,
            total_tco=165000.0,
            average_annual_cost=55000.0,
        )

        result = projection.to_dict()

        assert result["platform"] == "bigquery"
        assert result["base_annual_cost"] == 50000.0
        assert result["currency"] == "USD"
        assert result["projection_years"] == 3
        assert result["start_year"] == 2025
        assert result["total_tco"] == 165000.0
        assert result["average_annual_cost"] == 55000.0


class TestTCOCalculator:
    """Tests for TCOCalculator class."""

    @pytest.fixture
    def sample_benchmark_cost(self) -> BenchmarkCost:
        """Create a sample benchmark cost for testing."""
        return BenchmarkCost(
            total_cost=1000.0,
            currency="USD",
            platform_details={"platform": "snowflake"},
        )

    @pytest.fixture
    def calculator(self) -> TCOCalculator:
        """Create a TCO calculator instance."""
        return TCOCalculator()

    def test_calculate_tco_basic(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=12,  # Monthly runs
            projection_years=5,
        )

        # 12 runs * $1000 = $12000/year base
        assert projection.base_annual_cost == 12000.0
        assert projection.projection_years == 5
        assert projection.platform == "snowflake"
        assert len(projection.yearly_projections) == 5

        # No growth, no discount: 5 * $12000 = $60000
        assert projection.total_tco == pytest.approx(60000.0, rel=0.001)

    def test_calculate_tco_with_growth(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):

        growth_config = GrowthConfig(model=GrowthModel.COMPOUND, annual_rate=0.10)

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=12,
            projection_years=5,
            growth_config=growth_config,
        )

        # Base: $12000/year
        # Year 1: $12000 * 1.0 = $12000
        # Year 2: $12000 * 1.1 = $13200
        # Year 3: $12000 * 1.21 = $14520
        # Year 4: $12000 * 1.331 = $15972
        # Year 5: $12000 * 1.4641 = $17569.20
        # Total: ~$73261.20

        assert projection.yearly_projections[0].growth_multiplier == 1.0
        assert projection.yearly_projections[1].growth_multiplier == pytest.approx(1.1, rel=0.001)
        assert projection.total_tco > 60000.0  # More than flat projection

    def test_calculate_tco_with_discount(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):

        discount_config = DiscountConfig(
            discount_type=DiscountType.RESERVED,
            discount_percent=0.20,
        )

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=12,
            projection_years=5,
            discount_config=discount_config,
        )

        # Base: $12000/year
        # 20% discount: $12000 * 0.8 = $9600/year
        # 5 years: $48000

        assert projection.yearly_projections[0].discount_multiplier == 0.80
        assert projection.total_tco == pytest.approx(48000.0, rel=0.001)

    def test_calculate_tco_with_delayed_discount(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):
        """Test TCO calculation with discount that starts in year 2."""
        discount_config = DiscountConfig(
            discount_type=DiscountType.COMMITTED_USE,
            discount_percent=0.25,
            effective_start_year=2,
        )

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=12,
            projection_years=5,
            discount_config=discount_config,
        )

        # Year 1: $12000 (no discount)
        # Years 2-5: $12000 * 0.75 = $9000/year
        # Total: $12000 + 4 * $9000 = $48000

        assert projection.yearly_projections[0].discount_multiplier == 1.0
        assert projection.yearly_projections[1].discount_multiplier == 0.75
        assert projection.total_tco == pytest.approx(48000.0, rel=0.001)

    def test_calculate_tco_with_growth_and_discount(
        self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost
    ):

        growth_config = GrowthConfig(model=GrowthModel.COMPOUND, annual_rate=0.10)
        discount_config = DiscountConfig(
            discount_type=DiscountType.RESERVED,
            discount_percent=0.20,
        )

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=12,
            projection_years=3,
            growth_config=growth_config,
            discount_config=discount_config,
        )

        # Year 1: $12000 * 1.0 * 0.8 = $9600
        # Year 2: $12000 * 1.1 * 0.8 = $10560
        # Year 3: $12000 * 1.21 * 0.8 = $11616
        # Total: $31776

        assert projection.yearly_projections[0].projected_cost == pytest.approx(9600.0, rel=0.001)
        assert projection.yearly_projections[1].projected_cost == pytest.approx(10560.0, rel=0.001)
        assert projection.yearly_projections[2].projected_cost == pytest.approx(11616.0, rel=0.001)

    def test_calculate_tco_custom_platform(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=1,
            platform="databricks",
        )

        assert projection.platform == "databricks"

    def test_calculate_tco_custom_start_year(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=1,
            start_year=2030,
            projection_years=3,
        )

        assert projection.start_year == 2030
        assert projection.yearly_projections[0].calendar_year == 2030
        assert projection.yearly_projections[1].calendar_year == 2031
        assert projection.yearly_projections[2].calendar_year == 2032

    def test_calculate_tco_metadata(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=12,
        )

        assert "benchmark_run_cost" in projection.metadata
        assert projection.metadata["benchmark_run_cost"] == 1000.0
        assert projection.metadata["annual_runs"] == 12
        assert "generated_at" in projection.metadata

    def test_calculate_tco_from_annual_cost(self, calculator: TCOCalculator):

        projection = calculator.calculate_tco_from_annual_cost(
            annual_cost=50000.0,
            platform="redshift",
            projection_years=3,
        )

        assert projection.base_annual_cost == 50000.0
        assert projection.platform == "redshift"
        assert projection.total_tco == pytest.approx(150000.0, rel=0.001)

    def test_calculate_tco_cumulative_cost(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):

        growth_config = GrowthConfig(model=GrowthModel.LINEAR, annual_rate=0.20)

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=1,
            projection_years=3,
            growth_config=growth_config,
        )

        # Year 1: $1000, cumulative: $1000
        # Year 2: $1200, cumulative: $2200
        # Year 3: $1400, cumulative: $3600

        assert projection.yearly_projections[0].cumulative_cost == pytest.approx(1000.0, rel=0.001)
        assert projection.yearly_projections[1].cumulative_cost == pytest.approx(2200.0, rel=0.001)
        assert projection.yearly_projections[2].cumulative_cost == pytest.approx(3600.0, rel=0.001)
        assert projection.total_tco == projection.yearly_projections[-1].cumulative_cost

    def test_calculate_tco_monthly_cost(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=12,
            projection_years=1,
        )

        # $12000/year / 12 = $1000/month
        assert projection.yearly_projections[0].monthly_cost == pytest.approx(1000.0, rel=0.001)

    def test_calculate_tco_average_annual_cost(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):

        growth_config = GrowthConfig(model=GrowthModel.COMPOUND, annual_rate=0.10)

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=1,
            projection_years=5,
            growth_config=growth_config,
        )

        expected_average = projection.total_tco / 5
        assert projection.average_annual_cost == pytest.approx(expected_average, rel=0.001)


class TestTCOCalculatorBudgetAlerts:
    """Tests for TCO Calculator budget alert functionality."""

    @pytest.fixture
    def calculator(self) -> TCOCalculator:
        """Create a TCO calculator instance."""
        return TCOCalculator()

    @pytest.fixture
    def sample_benchmark_cost(self) -> BenchmarkCost:
        """Create a sample benchmark cost for testing."""
        return BenchmarkCost(
            total_cost=10000.0,
            currency="USD",
            platform_details={"platform": "snowflake"},
        )

    def test_add_budget_threshold(self, calculator: TCOCalculator):
        """Test adding budget thresholds."""
        threshold = BudgetThreshold(name="warning", amount=100000.0)
        calculator.add_budget_threshold(threshold)

        # Access private attribute for testing
        assert len(calculator._budget_thresholds) == 1
        assert calculator._budget_thresholds[0].name == "warning"

    def test_clear_budget_thresholds(self, calculator: TCOCalculator):
        """Test clearing budget thresholds."""
        calculator.add_budget_threshold(BudgetThreshold(name="test1", amount=100.0))
        calculator.add_budget_threshold(BudgetThreshold(name="test2", amount=200.0))

        assert len(calculator._budget_thresholds) == 2

        calculator.clear_budget_thresholds()

        assert len(calculator._budget_thresholds) == 0

    def test_annual_budget_alert_triggered(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):
        """Test that annual budget alert is triggered when exceeded."""
        # Set threshold at $15000/year
        calculator.add_budget_threshold(BudgetThreshold(name="annual_limit", amount=15000.0, period="annual"))

        # With 10% growth, year 2+ will exceed $15000
        growth_config = GrowthConfig(model=GrowthModel.COMPOUND, annual_rate=0.60)

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=1,
            projection_years=3,
            growth_config=growth_config,
        )

        # Year 1: $10000
        # Year 2: $16000 (exceeds $15000)
        assert len(projection.budget_alerts) == 1
        assert projection.budget_alerts[0].threshold.name == "annual_limit"
        assert projection.budget_alerts[0].year == 2

    def test_monthly_budget_alert_triggered(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):
        """Test that monthly budget alert is triggered when exceeded."""
        # Set threshold at $1000/month
        calculator.add_budget_threshold(BudgetThreshold(name="monthly_limit", amount=800.0, period="monthly"))

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=1,
            projection_years=1,
        )

        # $10000/year = $833.33/month > $800
        assert len(projection.budget_alerts) == 1
        assert projection.budget_alerts[0].threshold.name == "monthly_limit"
        assert projection.budget_alerts[0].period == "monthly"

    def test_total_budget_alert_triggered(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):
        """Test that total TCO budget alert is triggered."""
        # Set threshold at $25000 total
        calculator.add_budget_threshold(BudgetThreshold(name="total_limit", amount=25000.0, period="total"))

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=1,
            projection_years=3,
        )

        # 3 years * $10000 = $30000 > $25000
        assert len(projection.budget_alerts) == 1
        assert projection.budget_alerts[0].threshold.name == "total_limit"
        assert projection.budget_alerts[0].period == "total"

    def test_no_alert_when_under_budget(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):
        """Test that no alert is triggered when under budget."""
        # Set high threshold
        calculator.add_budget_threshold(BudgetThreshold(name="high_limit", amount=1000000.0, period="annual"))

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=1,
            projection_years=5,
        )

        assert len(projection.budget_alerts) == 0

    def test_multiple_thresholds(self, calculator: TCOCalculator, sample_benchmark_cost: BenchmarkCost):
        """Test multiple budget thresholds."""
        calculator.add_budget_threshold(BudgetThreshold(name="warning", amount=5000.0, period="annual"))
        calculator.add_budget_threshold(BudgetThreshold(name="critical", amount=8000.0, period="annual"))

        projection = calculator.calculate_tco(
            benchmark_cost=sample_benchmark_cost,
            annual_runs=1,
            projection_years=1,
        )

        # $10000 exceeds both $5000 and $8000
        assert len(projection.budget_alerts) == 2


class TestTCOCalculatorPlatformComparison:
    """Tests for TCO Calculator platform comparison functionality."""

    def test_compare_platforms_basic(self):

        calculator = TCOCalculator()

        # Create projections for different platforms
        projections = [
            TCOProjection(platform="snowflake", base_annual_cost=100000.0, total_tco=500000.0, projection_years=5),
            TCOProjection(platform="bigquery", base_annual_cost=80000.0, total_tco=400000.0, projection_years=5),
            TCOProjection(platform="redshift", base_annual_cost=120000.0, total_tco=600000.0, projection_years=5),
        ]

        comparison = calculator.compare_platforms(projections)

        assert comparison["cheapest_platform"] == "bigquery"
        assert comparison["most_expensive_platform"] == "redshift"
        assert comparison["max_savings"] == 200000.0
        assert len(comparison["rankings"]) == 3
        assert comparison["rankings"][0]["platform"] == "bigquery"
        assert comparison["rankings"][0]["rank"] == 1

    def test_compare_platforms_savings_calculation(self):

        calculator = TCOCalculator()

        projections = [
            TCOProjection(platform="platform_a", base_annual_cost=100.0, total_tco=100.0),
            TCOProjection(platform="platform_b", base_annual_cost=80.0, total_tco=80.0),
        ]

        comparison = calculator.compare_platforms(projections)

        # Platform B is cheaper
        assert comparison["rankings"][0]["platform"] == "platform_b"
        assert comparison["rankings"][0]["savings_vs_max"] == 20.0
        assert comparison["rankings"][0]["savings_percent"] == 20.0

        # Platform A is most expensive
        assert comparison["rankings"][1]["platform"] == "platform_a"
        assert comparison["rankings"][1]["savings_vs_max"] == 0.0

    def test_compare_platforms_empty(self):

        calculator = TCOCalculator()

        comparison = calculator.compare_platforms([])

        assert "error" in comparison

    def test_compare_platforms_single(self):

        calculator = TCOCalculator()

        projections = [TCOProjection(platform="only_one", base_annual_cost=100.0, total_tco=500.0)]

        comparison = calculator.compare_platforms(projections)

        assert comparison["cheapest_platform"] == "only_one"
        assert comparison["most_expensive_platform"] == "only_one"
        assert comparison["max_savings"] == 0.0


class TestCreateStandardTCOScenarios:
    """Tests for the create_standard_tco_scenarios utility function."""

    @pytest.fixture
    def sample_benchmark_cost(self) -> BenchmarkCost:
        """Create a sample benchmark cost for testing."""
        return BenchmarkCost(
            total_cost=1000.0,
            currency="USD",
            platform_details={"platform": "test"},
        )

    def test_creates_three_scenarios(self, sample_benchmark_cost: BenchmarkCost):

        scenarios = create_standard_tco_scenarios(sample_benchmark_cost)

        assert len(scenarios) == 3
        assert "conservative" in scenarios
        assert "moderate" in scenarios
        assert "aggressive" in scenarios

    def test_conservative_scenario(self, sample_benchmark_cost: BenchmarkCost):

        scenarios = create_standard_tco_scenarios(sample_benchmark_cost, annual_runs=12)

        conservative = scenarios["conservative"]

        assert conservative.growth_config.model == GrowthModel.NONE
        assert conservative.discount_config.discount_type == DiscountType.NONE
        # 12 runs * $1000 * 5 years = $60000
        assert conservative.total_tco == pytest.approx(60000.0, rel=0.001)

    def test_moderate_scenario(self, sample_benchmark_cost: BenchmarkCost):

        scenarios = create_standard_tco_scenarios(sample_benchmark_cost, annual_runs=12)

        moderate = scenarios["moderate"]

        assert moderate.growth_config.model == GrowthModel.COMPOUND
        assert moderate.growth_config.annual_rate == 0.10
        assert moderate.discount_config.discount_type == DiscountType.RESERVED
        assert moderate.discount_config.discount_percent == 0.15

    def test_aggressive_scenario(self, sample_benchmark_cost: BenchmarkCost):

        scenarios = create_standard_tco_scenarios(sample_benchmark_cost, annual_runs=12)

        aggressive = scenarios["aggressive"]

        assert aggressive.growth_config.model == GrowthModel.COMPOUND
        assert aggressive.growth_config.annual_rate == 0.25
        assert aggressive.discount_config.discount_type == DiscountType.NONE

        # Should be highest TCO due to high growth
        conservative = scenarios["conservative"]
        assert aggressive.total_tco > conservative.total_tco

    def test_all_scenarios_have_5_year_projection(self, sample_benchmark_cost: BenchmarkCost):
        """Test all scenarios project 5 years."""
        scenarios = create_standard_tco_scenarios(sample_benchmark_cost)

        for scenario in scenarios.values():
            assert scenario.projection_years == 5
            assert len(scenario.yearly_projections) == 5

    def test_custom_annual_runs(self, sample_benchmark_cost: BenchmarkCost):

        scenarios = create_standard_tco_scenarios(sample_benchmark_cost, annual_runs=52)  # Weekly

        # Base should be 52 * $1000 = $52000/year
        assert scenarios["conservative"].base_annual_cost == 52000.0
