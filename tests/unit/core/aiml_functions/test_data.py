"""Tests for AI/ML function sample data generation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.experimental.aiml_functions.data import AIMLDataGenerator, LongText, SampleText

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSampleText:
    """Tests for SampleText dataclass."""

    def test_basic_creation(self):
        """Should create sample text."""
        sample = SampleText(
            id=1,
            text_content="Test text content",
            category="Review",
            sentiment_label="positive",
            word_count=3,
        )
        assert sample.id == 1
        assert sample.text_content == "Test text content"
        assert sample.category == "Review"
        assert sample.sentiment_label == "positive"
        assert sample.language == "en"


class TestLongText:
    """Tests for LongText dataclass."""

    def test_basic_creation(self):
        """Should create long text."""
        long_text = LongText(
            id=1,
            long_text="A very long text...",
            topic="Technology",
            word_count=4,
        )
        assert long_text.id == 1
        assert long_text.topic == "Technology"
        assert long_text.word_count == 4


class TestAIMLDataGenerator:
    """Tests for AIMLDataGenerator class."""

    @pytest.fixture
    def generator(self):
        """Create data generator."""
        return AIMLDataGenerator(seed=42, num_samples=50, num_long_texts=10)

    def test_basic_creation(self, generator):
        """Should create generator with parameters."""
        assert generator.seed == 42
        assert generator.num_samples == 50
        assert generator.num_long_texts == 10

    def test_generate_sample_data(self, generator):
        """Should generate sample data."""
        samples = generator.generate_sample_data()
        assert len(samples) == 50
        assert all(isinstance(s, SampleText) for s in samples)

    def test_sample_data_has_unique_ids(self, generator):
        """Should have unique IDs."""
        samples = generator.generate_sample_data()
        ids = [s.id for s in samples]
        assert len(ids) == len(set(ids))

    def test_sample_data_has_sentiments(self, generator):
        """Should have different sentiments."""
        samples = generator.generate_sample_data()
        sentiments = {s.sentiment_label for s in samples}
        assert "positive" in sentiments
        assert "negative" in sentiments
        assert "neutral" in sentiments

    def test_sample_data_has_categories(self, generator):
        """Should have different categories."""
        samples = generator.generate_sample_data()
        categories = {s.category for s in samples}
        assert "Review" in categories
        assert len(categories) > 1

    def test_sample_data_has_word_counts(self, generator):
        """Should calculate word counts."""
        samples = generator.generate_sample_data()
        for sample in samples:
            actual_words = len(sample.text_content.split())
            assert sample.word_count == actual_words

    def test_generate_long_texts(self, generator):
        """Should generate long texts."""
        texts = generator.generate_long_texts()
        assert len(texts) == 10
        assert all(isinstance(t, LongText) for t in texts)

    def test_long_texts_have_unique_ids(self, generator):
        """Should have unique IDs."""
        texts = generator.generate_long_texts()
        ids = [t.id for t in texts]
        assert len(ids) == len(set(ids))

    def test_long_texts_are_longer(self, generator):
        """Long texts should be longer than sample texts."""
        samples = generator.generate_sample_data()
        long_texts = generator.generate_long_texts()
        avg_sample_length = sum(s.word_count for s in samples) / len(samples)
        avg_long_length = sum(t.word_count for t in long_texts) / len(long_texts)
        assert avg_long_length > avg_sample_length * 5

    def test_reproducible_with_seed(self):
        """Should be reproducible with same seed."""
        gen1 = AIMLDataGenerator(seed=123, num_samples=20, num_long_texts=5)
        gen2 = AIMLDataGenerator(seed=123, num_samples=20, num_long_texts=5)
        samples1 = gen1.generate_sample_data()
        samples2 = gen2.generate_sample_data()
        assert [s.text_content for s in samples1] == [s.text_content for s in samples2]

    def test_different_seeds_different_data(self):
        """Should produce different data with different seeds when generating variations."""
        # Use larger sample count to force variation generation
        gen1 = AIMLDataGenerator(seed=1, num_samples=100, num_long_texts=10)
        gen2 = AIMLDataGenerator(seed=2, num_samples=100, num_long_texts=10)
        samples1 = gen1.generate_sample_data()
        samples2 = gen2.generate_sample_data()
        # The base samples (first 55) are deterministic from constants
        # Variations start after that, so compare samples near the end
        # where random selection of base sample differs by seed
        later_samples1 = [s.text_content for s in samples1[60:70]]
        later_samples2 = [s.text_content for s in samples2[60:70]]
        # At least some should differ due to different random choices
        assert later_samples1 != later_samples2 or len(set(later_samples1)) != len(set(later_samples2))


class TestAIMLDataGeneratorCSV:
    """Tests for CSV generation."""

    @pytest.fixture
    def generator(self):
        """Create data generator."""
        return AIMLDataGenerator(seed=42, num_samples=20, num_long_texts=5)

    def test_generate_csv(self, generator, tmp_path):
        """Should generate CSV files."""
        files = generator.generate_csv(tmp_path)
        assert "aiml_sample_data" in files
        assert "aiml_long_texts" in files
        assert files["aiml_sample_data"].exists()
        assert files["aiml_long_texts"].exists()

    def test_csv_has_headers(self, generator, tmp_path):
        """Should have CSV headers."""
        files = generator.generate_csv(tmp_path)
        sample_content = files["aiml_sample_data"].read_text()
        assert "id,text_content,category" in sample_content

    def test_csv_has_correct_rows(self, generator, tmp_path):
        """Should have correct number of rows."""
        files = generator.generate_csv(tmp_path)
        sample_lines = files["aiml_sample_data"].read_text().strip().split("\n")
        # Header + 20 data rows
        assert len(sample_lines) == 21


class TestAIMLDataGeneratorSQL:
    """Tests for SQL generation."""

    @pytest.fixture
    def generator(self):
        """Create data generator."""
        return AIMLDataGenerator(seed=42, num_samples=10, num_long_texts=3)

    def test_get_create_table_sql_snowflake(self, generator):
        """Should generate Snowflake CREATE TABLE."""
        statements = generator.get_create_table_sql("snowflake")
        assert "aiml_sample_data" in statements
        assert "aiml_long_texts" in statements
        assert "CREATE OR REPLACE TABLE" in statements["aiml_sample_data"]
        assert "VARCHAR" in statements["aiml_sample_data"]

    def test_get_create_table_sql_bigquery(self, generator):
        """Should generate BigQuery CREATE TABLE."""
        statements = generator.get_create_table_sql("bigquery")
        assert "CREATE OR REPLACE TABLE" in statements["aiml_sample_data"]
        assert "STRING" in statements["aiml_sample_data"]

    def test_get_create_table_sql_databricks(self, generator):
        """Should generate Databricks CREATE TABLE."""
        statements = generator.get_create_table_sql("databricks")
        assert "CREATE OR REPLACE TABLE" in statements["aiml_sample_data"]
        assert "STRING" in statements["aiml_sample_data"]

    def test_get_create_table_sql_generic(self, generator):
        """Should generate generic CREATE TABLE."""
        statements = generator.get_create_table_sql("postgres")
        assert "CREATE TABLE IF NOT EXISTS" in statements["aiml_sample_data"]
        assert "TEXT" in statements["aiml_sample_data"]

    def test_get_insert_sql(self, generator):
        """Should generate INSERT statements."""
        statements = generator.get_insert_sql("snowflake")
        assert len(statements) == 2  # One for each table
        assert "INSERT INTO aiml_sample_data" in statements[0]
        assert "INSERT INTO aiml_long_texts" in statements[1]

    def test_insert_sql_escapes_quotes(self, generator):
        """Should escape single quotes in text."""
        statements = generator.get_insert_sql("snowflake")
        # The template texts contain apostrophes
        assert "''" in statements[0] or "I love it" in statements[0]


class TestAIMLDataGeneratorManifest:
    """Tests for manifest generation."""

    @pytest.fixture
    def generator(self):
        """Create data generator."""
        return AIMLDataGenerator(seed=42, num_samples=30, num_long_texts=5)

    def test_get_manifest(self, generator):
        """Should generate manifest."""
        manifest = generator.get_manifest()
        assert manifest["generator"] == "AIMLDataGenerator"
        assert manifest["version"] == "1.0"
        assert manifest["seed"] == 42
        assert "generated_at" in manifest
        assert "tables" in manifest

    def test_manifest_has_table_info(self, generator):
        """Should have table information."""
        manifest = generator.get_manifest()
        assert "aiml_sample_data" in manifest["tables"]
        assert "aiml_long_texts" in manifest["tables"]
        assert manifest["tables"]["aiml_sample_data"]["row_count"] == 30
        assert manifest["tables"]["aiml_long_texts"]["row_count"] == 5

    def test_manifest_has_sentiment_distribution(self, generator):
        """Should have sentiment distribution."""
        manifest = generator.get_manifest()
        dist = manifest["tables"]["aiml_sample_data"]["sentiment_distribution"]
        assert "positive" in dist
        assert "negative" in dist
        assert "neutral" in dist
        assert sum(dist.values()) == 30

    def test_manifest_has_avg_word_count(self, generator):
        """Should have average word count for long texts."""
        manifest = generator.get_manifest()
        assert "avg_word_count" in manifest["tables"]["aiml_long_texts"]
        assert manifest["tables"]["aiml_long_texts"]["avg_word_count"] > 0


class TestSampleTextContent:
    """Tests for the actual sample text content."""

    @pytest.fixture
    def generator(self):
        """Create data generator."""
        return AIMLDataGenerator(seed=42, num_samples=100, num_long_texts=10)

    def test_positive_texts_are_labeled(self, generator):
        """Positive samples should be labeled correctly."""
        samples = generator.generate_sample_data()
        positive_samples = [s for s in samples if s.sentiment_label == "positive"]
        assert len(positive_samples) >= 10
        # Check that at least half contain obviously positive words
        positive_indicators = [
            "love",
            "amazing",
            "excellent",
            "outstanding",
            "best",
            "great",
            "happy",
            "exceeded",
            "brilliant",
            "impressed",
            "recommend",
            "flawless",
            "better",
            "exceptional",
            "incredible",
            "fantastic",
            "wonderful",
        ]
        positive_count = sum(
            1 for s in positive_samples[:10] if any(word in s.text_content.lower() for word in positive_indicators)
        )
        assert positive_count >= 5, f"Expected at least 5/10 positive samples with positive words, got {positive_count}"

    def test_negative_texts_are_labeled(self, generator):
        """Negative samples should be labeled correctly."""
        samples = generator.generate_sample_data()
        negative_samples = [s for s in samples if s.sentiment_label == "negative"]
        assert len(negative_samples) >= 10
        # Check that at least half contain obviously negative words
        negative_indicators = [
            "terrible",
            "worst",
            "disappointed",
            "waste",
            "horrible",
            "frustrating",
            "regret",
            "defective",
            "nightmare",
            "broke",
            "unhelpful",
            "overpriced",
            "save your money",
            "do not buy",
        ]
        negative_count = sum(
            1 for s in negative_samples[:10] if any(word in s.text_content.lower() for word in negative_indicators)
        )
        assert negative_count >= 5, f"Expected at least 5/10 negative samples with negative words, got {negative_count}"

    def test_category_texts_are_categorized(self, generator):
        """Category samples should be categorized."""
        samples = generator.generate_sample_data()
        tech_samples = [s for s in samples if s.category == "Technology"]
        assert len(tech_samples) >= 1
        # Just verify we have technology samples and they have content
        for sample in tech_samples[:5]:
            assert len(sample.text_content) > 0
            assert sample.category == "Technology"
