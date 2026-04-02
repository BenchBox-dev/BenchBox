"""Sample data generation for AI/ML function benchmarks.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SampleText:
    """A sample text for AI/ML function testing."""

    id: int
    text_content: str
    category: str
    sentiment_label: str
    word_count: int
    language: str = "en"


@dataclass
class LongText:
    """A longer text for summarization testing."""

    id: int
    long_text: str
    topic: str
    word_count: int


class AIMLDataGenerator:
    """Generator for AI/ML function benchmark sample data."""

    # Sample review texts with known sentiments
    POSITIVE_TEXTS = [
        "This product exceeded all my expectations! The quality is outstanding and delivery was super fast.",
        "Absolutely love this service. Customer support was incredibly helpful and resolved my issue immediately.",
        "Best purchase I've made this year. The features are exactly what I needed and the price was reasonable.",
        "Amazing experience from start to finish. Highly recommend to anyone looking for quality.",
        "The team went above and beyond to help me. Couldn't be happier with the results!",
        "Exceptional quality and attention to detail. This company really knows how to deliver value.",
        "I'm thoroughly impressed with the performance. It works even better than advertised.",
        "Outstanding product with excellent customer service. Will definitely buy again.",
        "Five stars aren't enough! This has completely transformed my workflow for the better.",
        "Brilliant execution on every front. The design is elegant and functionality is flawless.",
    ]

    NEGATIVE_TEXTS = [
        "Terrible experience. The product arrived damaged and customer service was unhelpful.",
        "Complete waste of money. Does not work as advertised and return process is a nightmare.",
        "Very disappointed with the quality. Broke after just two weeks of normal use.",
        "Worst customer service I've ever encountered. Still waiting for a response after 3 weeks.",
        "Do not buy this product. It's overpriced and underperforms compared to competitors.",
        "Extremely frustrating experience. Multiple issues with delivery and product quality.",
        "I regret this purchase entirely. The product is cheaply made and falls apart easily.",
        "Horrible quality control. Received a defective item and replacement was even worse.",
        "Save your money and look elsewhere. This product is not worth even half the price.",
        "Deeply disappointed. The marketing promises were completely misleading and false.",
    ]

    NEUTRAL_TEXTS = [
        "The product works as described. Nothing special but gets the job done adequately.",
        "Average experience overall. Some features are good, others need improvement.",
        "Delivered on time and works fine. Packaging could be better but no major issues.",
        "Standard product for the price range. Meets basic expectations but doesn't exceed them.",
        "It's okay for what it is. I've seen better but also seen worse at this price point.",
        "Functional but unremarkable. Does what it says but nothing more than that.",
        "Middle of the road product. Some positive aspects balanced by a few negatives.",
        "Neither great nor terrible. It serves its purpose without any standout features.",
        "Basic product that works. Wouldn't rave about it but wouldn't complain either.",
        "Acceptable quality for the price. No complaints but no particular praise either.",
    ]

    # Category-specific texts for classification testing
    CATEGORY_TEXTS = {
        "Technology": [
            "The new AI chip delivers unprecedented performance gains for machine learning workloads.",
            "Cloud computing adoption continues to accelerate across enterprise organizations.",
            "Quantum computing breakthrough enables solving previously impossible calculations.",
            "Cybersecurity threats are evolving rapidly with new AI-powered attack vectors.",
            "The latest smartphone features revolutionary camera technology and faster processors.",
        ],
        "Finance": [
            "Stock markets reached all-time highs driven by strong corporate earnings reports.",
            "The Federal Reserve announced interest rate decisions affecting global markets.",
            "Cryptocurrency volatility continues as institutional investors adjust positions.",
            "Banking sector shows resilience despite economic headwinds and regulatory changes.",
            "Investment strategies are shifting toward sustainable and ESG-focused portfolios.",
        ],
        "Healthcare": [
            "New cancer treatment shows promising results in clinical trials across multiple centers.",
            "Telemedicine adoption has permanently changed how patients access healthcare services.",
            "Breakthrough in gene therapy offers hope for previously untreatable genetic conditions.",
            "Hospital systems are implementing AI tools to improve diagnostic accuracy and speed.",
            "Mental health awareness initiatives are expanding access to treatment and support.",
        ],
        "Entertainment": [
            "The streaming platform announced a slate of new original content for next quarter.",
            "Box office revenues exceeded expectations with strong summer movie releases.",
            "Gaming industry continues rapid growth with mobile and cloud gaming innovations.",
            "Music streaming services are competing for exclusive content and artist partnerships.",
            "Virtual reality entertainment is finding new audiences in theme parks and venues.",
        ],
        "Sports": [
            "The championship game drew record viewership with an exciting overtime finish.",
            "Player transfer deals are reshaping team rosters across major leagues worldwide.",
            "Olympic preparations are underway with athletes training for upcoming competitions.",
            "Sports analytics are transforming how teams evaluate performance and make decisions.",
            "Youth sports participation is increasing with new community programs and facilities.",
        ],
    }

    # Long texts for summarization testing
    LONG_TEXT_TEMPLATES = [
        """The evolution of artificial intelligence in enterprise applications has fundamentally transformed how organizations approach business operations and decision-making. Over the past decade, we have witnessed a remarkable shift from theoretical discussions about AI capabilities to practical implementations that deliver measurable value across industries.

In the financial sector, AI systems now analyze millions of transactions in real-time, detecting fraudulent activities with unprecedented accuracy. These systems learn from historical patterns and adapt to new threats, providing a dynamic defense against increasingly sophisticated attacks. Banks and financial institutions report significant reductions in fraud losses while simultaneously improving customer experience through faster transaction processing.

Healthcare organizations are leveraging AI to improve patient outcomes through early disease detection and personalized treatment recommendations. Machine learning models trained on vast datasets of medical records, imaging studies, and genetic information can identify subtle patterns that might escape human observation. This technology is particularly impactful in radiology, where AI-assisted diagnosis helps clinicians catch potential issues earlier in the disease progression.

The manufacturing sector has embraced AI-powered predictive maintenance to reduce equipment downtime and extend asset lifecycles. Sensors throughout production facilities feed continuous data streams to analytical models that predict when components are likely to fail. This proactive approach allows maintenance teams to address issues before they cause costly production interruptions.

Looking ahead, the integration of AI with emerging technologies like quantum computing and advanced robotics promises even greater capabilities. Organizations that invest in building AI expertise and infrastructure today are positioning themselves to capitalize on these future opportunities. However, this journey also requires careful attention to ethical considerations, data privacy, and the changing nature of work.""",
        """Climate change represents one of the most significant challenges facing global society in the 21st century. The scientific consensus is clear: human activities, particularly the burning of fossil fuels, have led to unprecedented increases in atmospheric greenhouse gas concentrations, driving changes in temperature, precipitation patterns, and extreme weather events.

The impacts of these changes are already visible across the planet. Polar ice sheets are melting at accelerating rates, contributing to sea level rise that threatens coastal communities and low-lying island nations. Extreme weather events, including hurricanes, wildfires, and heat waves, have become more frequent and intense, causing billions of dollars in damages and displacing millions of people.

Agricultural systems are under increasing stress as changing climate patterns affect growing seasons, water availability, and pest pressures. Farmers in many regions are experiencing yield reductions and increased variability, threatening food security for vulnerable populations. These challenges are particularly acute in developing countries where adaptive capacity is limited.

The transition to a low-carbon economy requires unprecedented coordination between governments, businesses, and civil society. Renewable energy technologies have made remarkable progress, with solar and wind power now cost-competitive with fossil fuels in many markets. Electric vehicles are gaining market share, and energy efficiency improvements are reducing demand across sectors.

Despite these encouraging trends, the pace of change must accelerate to meet the goals of the Paris Agreement. Achieving net-zero emissions by mid-century will require massive investments in clean energy infrastructure, changes to industrial processes, and shifts in consumer behavior. The choices made in the coming decade will determine whether humanity can avoid the most catastrophic impacts of climate change.""",
        """The digital transformation of education has accelerated dramatically, fundamentally changing how students learn and teachers instruct. What began as supplementary online resources has evolved into comprehensive learning ecosystems that blend in-person and virtual experiences.

Online learning platforms now offer courses from leading universities to students anywhere in the world, democratizing access to high-quality education. These platforms use sophisticated algorithms to personalize learning paths, adapting content difficulty and pace to individual student needs. Data analytics provide detailed insights into student progress, allowing educators to identify and address learning gaps quickly.

The COVID-19 pandemic forced a rapid shift to remote learning, revealing both the potential and limitations of digital education. Schools that had invested in technology infrastructure and teacher training transitioned more smoothly, while others struggled to maintain educational continuity. These experiences have highlighted the importance of digital literacy and the need to address the digital divide that leaves some students without adequate technology access.

Emerging technologies promise to further transform education. Virtual and augmented reality can create immersive learning experiences that bring abstract concepts to life. Artificial intelligence tutors can provide personalized support at scale, helping students work through problems and concepts at their own pace. Blockchain technology offers new ways to verify credentials and create portable, secure educational records.

However, technology alone cannot solve education's challenges. Effective implementation requires thoughtful integration with proven pedagogical approaches, ongoing professional development for educators, and attention to social-emotional aspects of learning that are difficult to replicate in digital environments. The most successful educational innovations will combine the best of human instruction with the capabilities of digital tools.""",
    ]

    def __init__(
        self,
        seed: int = 42,
        num_samples: int = 100,
        num_long_texts: int = 20,
    ) -> None:
        """Initialize the data generator.

        Args:
            seed: Random seed for reproducibility
            num_samples: Number of sample texts to generate
            num_long_texts: Number of long texts to generate
        """
        self.seed = seed
        self.num_samples = num_samples
        self.num_long_texts = num_long_texts
        random.seed(seed)

    def generate_sample_data(self) -> list[SampleText]:
        """Generate sample text data for benchmarking."""
        samples: list[SampleText] = []
        sample_id = 1

        # Generate positive samples
        for text in self.POSITIVE_TEXTS:
            samples.append(
                SampleText(
                    id=sample_id,
                    text_content=text,
                    category="Review",
                    sentiment_label="positive",
                    word_count=len(text.split()),
                )
            )
            sample_id += 1

        # Generate negative samples
        for text in self.NEGATIVE_TEXTS:
            samples.append(
                SampleText(
                    id=sample_id,
                    text_content=text,
                    category="Review",
                    sentiment_label="negative",
                    word_count=len(text.split()),
                )
            )
            sample_id += 1

        # Generate neutral samples
        for text in self.NEUTRAL_TEXTS:
            samples.append(
                SampleText(
                    id=sample_id,
                    text_content=text,
                    category="Review",
                    sentiment_label="neutral",
                    word_count=len(text.split()),
                )
            )
            sample_id += 1

        # Generate category-specific samples
        for category, texts in self.CATEGORY_TEXTS.items():
            for text in texts:
                samples.append(
                    SampleText(
                        id=sample_id,
                        text_content=text,
                        category=category,
                        sentiment_label="neutral",
                        word_count=len(text.split()),
                    )
                )
                sample_id += 1

        # Generate additional samples by combining
        while len(samples) < self.num_samples:
            base_samples = list(samples)
            sample = random.choice(base_samples)
            # Create variation
            variation = f"{sample.text_content} This is important to note."
            samples.append(
                SampleText(
                    id=sample_id,
                    text_content=variation,
                    category=sample.category,
                    sentiment_label=sample.sentiment_label,
                    word_count=len(variation.split()),
                )
            )
            sample_id += 1

        return samples[: self.num_samples]

    def generate_long_texts(self) -> list[LongText]:
        """Generate long text data for summarization benchmarking."""
        texts: list[LongText] = []
        topics = [
            "Artificial Intelligence",
            "Climate Change",
            "Digital Education",
        ]

        for i, template in enumerate(self.LONG_TEXT_TEMPLATES):
            texts.append(
                LongText(
                    id=i + 1,
                    long_text=template,
                    topic=topics[i % len(topics)],
                    word_count=len(template.split()),
                )
            )

        # Generate variations
        text_id = len(texts) + 1
        while len(texts) < self.num_long_texts:
            base = random.choice(self.LONG_TEXT_TEMPLATES)
            topic = random.choice(topics)
            # Simple variation: add paragraph break
            variation = base.replace("\n\n", "\n\nFurthermore, ")
            texts.append(
                LongText(
                    id=text_id,
                    long_text=variation,
                    topic=topic,
                    word_count=len(variation.split()),
                )
            )
            text_id += 1

        return texts[: self.num_long_texts]

    def generate_csv(self, output_path: Path) -> dict[str, Path]:
        """Generate CSV files for sample data.

        Args:
            output_path: Directory to write CSV files

        Returns:
            Dictionary mapping table names to file paths
        """
        import csv

        output_path.mkdir(parents=True, exist_ok=True)
        files: dict[str, Path] = {}

        # Generate sample data CSV
        sample_file = output_path / "aiml_sample_data.csv"
        samples = self.generate_sample_data()
        with open(sample_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["id", "text_content", "category", "sentiment_label", "word_count", "language"]
            )
            writer.writeheader()
            for sample in samples:
                writer.writerow(
                    {
                        "id": sample.id,
                        "text_content": sample.text_content,
                        "category": sample.category,
                        "sentiment_label": sample.sentiment_label,
                        "word_count": sample.word_count,
                        "language": sample.language,
                    }
                )
        files["aiml_sample_data"] = sample_file

        # Generate long texts CSV
        long_file = output_path / "aiml_long_texts.csv"
        long_texts = self.generate_long_texts()
        with open(long_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "long_text", "topic", "word_count"])
            writer.writeheader()
            for text in long_texts:
                writer.writerow(
                    {
                        "id": text.id,
                        "long_text": text.long_text,
                        "topic": text.topic,
                        "word_count": text.word_count,
                    }
                )
        files["aiml_long_texts"] = long_file

        return files

    def get_create_table_sql(self, platform: str = "snowflake") -> dict[str, str]:
        """Get CREATE TABLE statements for each platform.

        Args:
            platform: Target platform (snowflake, bigquery, databricks)

        Returns:
            Dictionary mapping table names to CREATE TABLE statements
        """
        statements: dict[str, str] = {}

        if platform.lower() == "snowflake":
            statements["aiml_sample_data"] = """
CREATE OR REPLACE TABLE aiml_sample_data (
    id INTEGER,
    text_content VARCHAR,
    category VARCHAR,
    sentiment_label VARCHAR,
    word_count INTEGER,
    language VARCHAR DEFAULT 'en'
)
"""
            statements["aiml_long_texts"] = """
CREATE OR REPLACE TABLE aiml_long_texts (
    id INTEGER,
    long_text VARCHAR,
    topic VARCHAR,
    word_count INTEGER
)
"""
        elif platform.lower() == "bigquery":
            statements["aiml_sample_data"] = """
CREATE OR REPLACE TABLE aiml_sample_data (
    id INT64,
    text_content STRING,
    category STRING,
    sentiment_label STRING,
    word_count INT64,
    language STRING DEFAULT 'en'
)
"""
            statements["aiml_long_texts"] = """
CREATE OR REPLACE TABLE aiml_long_texts (
    id INT64,
    long_text STRING,
    topic STRING,
    word_count INT64
)
"""
        elif platform.lower() == "databricks":
            statements["aiml_sample_data"] = """
CREATE OR REPLACE TABLE aiml_sample_data (
    id INT,
    text_content STRING,
    category STRING,
    sentiment_label STRING,
    word_count INT,
    language STRING DEFAULT 'en'
)
"""
            statements["aiml_long_texts"] = """
CREATE OR REPLACE TABLE aiml_long_texts (
    id INT,
    long_text STRING,
    topic STRING,
    word_count INT
)
"""
        else:
            # Generic SQL
            statements["aiml_sample_data"] = """
CREATE TABLE IF NOT EXISTS aiml_sample_data (
    id INTEGER,
    text_content TEXT,
    category VARCHAR(50),
    sentiment_label VARCHAR(20),
    word_count INTEGER,
    language VARCHAR(10) DEFAULT 'en'
)
"""
            statements["aiml_long_texts"] = """
CREATE TABLE IF NOT EXISTS aiml_long_texts (
    id INTEGER,
    long_text TEXT,
    topic VARCHAR(100),
    word_count INTEGER
)
"""

        return statements

    def get_insert_sql(self, platform: str = "snowflake") -> list[str]:
        """Generate INSERT statements for sample data.

        Args:
            platform: Target platform

        Returns:
            List of INSERT SQL statements
        """
        statements: list[str] = []
        samples = self.generate_sample_data()
        long_texts = self.generate_long_texts()

        # Batch inserts
        if platform.lower() in ("snowflake", "databricks"):
            # Insert sample data
            values = []
            for s in samples:
                text_escaped = s.text_content.replace("'", "''")
                values.append(
                    f"({s.id}, '{text_escaped}', '{s.category}', '{s.sentiment_label}', {s.word_count}, '{s.language}')"
                )
            statements.append(
                "INSERT INTO aiml_sample_data (id, text_content, category, sentiment_label, word_count, language) VALUES\n"
                + ",\n".join(values)
            )

            # Insert long texts
            values = []
            for t in long_texts:
                text_escaped = t.long_text.replace("'", "''")
                values.append(f"({t.id}, '{text_escaped}', '{t.topic}', {t.word_count})")
            statements.append(
                "INSERT INTO aiml_long_texts (id, long_text, topic, word_count) VALUES\n" + ",\n".join(values)
            )

        elif platform.lower() == "bigquery":
            # BigQuery uses different INSERT syntax
            values = []
            for s in samples:
                text_escaped = s.text_content.replace("'", "\\'")
                values.append(
                    f"({s.id}, '{text_escaped}', '{s.category}', '{s.sentiment_label}', {s.word_count}, '{s.language}')"
                )
            statements.append(
                "INSERT INTO aiml_sample_data (id, text_content, category, sentiment_label, word_count, language) VALUES\n"
                + ",\n".join(values)
            )

            values = []
            for t in long_texts:
                text_escaped = t.long_text.replace("'", "\\'")
                values.append(f"({t.id}, '{text_escaped}', '{t.topic}', {t.word_count})")
            statements.append(
                "INSERT INTO aiml_long_texts (id, long_text, topic, word_count) VALUES\n" + ",\n".join(values)
            )

        return statements

    def get_manifest(self) -> dict[str, Any]:
        """Generate a manifest describing the generated data."""
        samples = self.generate_sample_data()
        long_texts = self.generate_long_texts()

        return {
            "generator": "AIMLDataGenerator",
            "version": "1.0",
            "seed": self.seed,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tables": {
                "aiml_sample_data": {
                    "row_count": len(samples),
                    "columns": ["id", "text_content", "category", "sentiment_label", "word_count", "language"],
                    "sentiment_distribution": {
                        "positive": sum(1 for s in samples if s.sentiment_label == "positive"),
                        "negative": sum(1 for s in samples if s.sentiment_label == "negative"),
                        "neutral": sum(1 for s in samples if s.sentiment_label == "neutral"),
                    },
                },
                "aiml_long_texts": {
                    "row_count": len(long_texts),
                    "columns": ["id", "long_text", "topic", "word_count"],
                    "avg_word_count": sum(t.word_count for t in long_texts) / len(long_texts) if long_texts else 0,
                },
            },
        }
