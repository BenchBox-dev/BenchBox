"""Automated insight generation for benchmark comparisons.

Generates human-readable insights, summaries, and recommendations
from benchmark comparison results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from benchbox.core.analysis.models import (
    ComparisonReport,
    CostPerformanceAnalysis,
)


@dataclass
class InsightConfig:
    """Configuration for insight generation.

    Attributes:
        include_executive_summary: Generate executive summary
        include_key_findings: Generate key findings list
        include_recommendations: Generate recommendations
        include_query_highlights: Highlight notable queries
        max_insights_per_category: Maximum insights per category
        performance_threshold: Ratio threshold for "significantly faster" (default 1.5)
        win_rate_threshold: Win rate to consider "dominant" (default 70%)
    """

    include_executive_summary: bool = True
    include_key_findings: bool = True
    include_recommendations: bool = True
    include_query_highlights: bool = True
    max_insights_per_category: int = 5
    performance_threshold: float = 1.5  # 1.5x faster = significant
    win_rate_threshold: float = 70.0  # 70% win rate = dominant


@dataclass
class InsightReport:
    """Collection of generated insights.

    Attributes:
        executive_summary: One-paragraph executive summary
        key_findings: Bulleted key findings
        winner_announcement: Winner declaration statement
        performance_insights: Performance-related insights
        cost_insights: Cost-related insights
        recommendations: Platform recommendations
        query_highlights: Notable query-specific insights
        blog_snippet: Ready-to-use paragraph for blog posts
        metadata: Generation metadata
    """

    executive_summary: str = ""
    key_findings: list[str] = field(default_factory=list)
    winner_announcement: str = ""
    performance_insights: list[str] = field(default_factory=list)
    cost_insights: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    query_highlights: list[str] = field(default_factory=list)
    blog_snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "executive_summary": self.executive_summary,
            "key_findings": self.key_findings,
            "winner_announcement": self.winner_announcement,
            "performance_insights": self.performance_insights,
            "cost_insights": self.cost_insights,
            "recommendations": self.recommendations,
            "query_highlights": self.query_highlights,
            "blog_snippet": self.blog_snippet,
            "metadata": self.metadata,
        }

    def to_markdown(self) -> str:
        """Convert insights to markdown format."""
        sections = []

        if self.executive_summary:
            sections.append("## Executive Summary\n\n" + self.executive_summary)

        if self.winner_announcement:
            sections.append("## Winner\n\n" + self.winner_announcement)

        if self.key_findings:
            sections.append("## Key Findings\n\n" + "\n".join(f"- {f}" for f in self.key_findings))

        if self.performance_insights:
            sections.append("## Performance Insights\n\n" + "\n".join(f"- {i}" for i in self.performance_insights))

        if self.cost_insights:
            sections.append("## Cost Analysis\n\n" + "\n".join(f"- {i}" for i in self.cost_insights))

        if self.recommendations:
            sections.append("## Recommendations\n\n" + "\n".join(f"- {r}" for r in self.recommendations))

        if self.query_highlights:
            sections.append("## Query Highlights\n\n" + "\n".join(f"- {h}" for h in self.query_highlights))

        return "\n\n".join(sections)


class InsightGenerator:
    """Generates automated insights from comparison results.

    Example:
        >>> from benchbox.core.analysis import InsightGenerator
        >>>
        >>> generator = InsightGenerator()
        >>> insights = generator.generate(comparison_report)
        >>> emit(insights.executive_summary)
        >>> emit(insights.to_markdown())
    """

    def __init__(self, config: Optional[InsightConfig] = None) -> None:
        """Initialize the insight generator.

        Args:
            config: Configuration options for insight generation
        """
        self.config = config or InsightConfig()

    def generate(self, report: ComparisonReport) -> InsightReport:
        """Generate comprehensive insights from a comparison report.

        Args:
            report: ComparisonReport to analyze

        Returns:
            InsightReport with all generated insights
        """
        insights = InsightReport(
            metadata={
                "benchmark_name": report.benchmark_name,
                "scale_factor": report.scale_factor,
                "platforms_compared": len(report.platforms),
                "queries_compared": len(report.query_comparisons),
            }
        )

        # Generate winner announcement
        insights.winner_announcement = self._generate_winner_announcement(report)

        # Generate executive summary
        if self.config.include_executive_summary:
            insights.executive_summary = self._generate_executive_summary(report)

        # Generate key findings
        if self.config.include_key_findings:
            insights.key_findings = self._generate_key_findings(report)

        # Generate performance insights
        insights.performance_insights = self._generate_performance_insights(report)

        # Generate cost insights
        if report.cost_analysis:
            insights.cost_insights = self._generate_cost_insights(report.cost_analysis)

        # Generate recommendations
        if self.config.include_recommendations:
            insights.recommendations = self._generate_recommendations(report)

        # Generate query highlights
        if self.config.include_query_highlights:
            insights.query_highlights = self._generate_query_highlights(report)

        # Generate blog snippet
        insights.blog_snippet = self._generate_blog_snippet(report, insights)

        return insights

    def _generate_winner_announcement(self, report: ComparisonReport) -> str:
        """Generate winner announcement statement.

        Args:
            report: Comparison report

        Returns:
            Winner announcement string
        """
        if not report.rankings:
            return "No clear winner could be determined."

        winner = report.rankings[0]

        if len(report.rankings) == 1:
            return f"{winner.platform} is the only platform tested."

        runner_up = report.rankings[1]

        # Calculate speedup
        if runner_up.geometric_mean_time > 0:
            speedup = runner_up.geometric_mean_time / winner.geometric_mean_time
        else:
            speedup = 1.0

        # Check statistical significance
        sig_str = ""
        if report.statistical_summary.get("significant_percent", 0) > 50:
            sig_str = " (statistically significant)"

        if speedup >= self.config.performance_threshold:
            return (
                f"**{winner.platform}** is the clear winner, "
                f"{speedup:.2f}x faster than {runner_up.platform} "
                f"on {report.benchmark_name} at SF{report.scale_factor}{sig_str}."
            )
        elif speedup > 1.1:
            return (
                f"**{winner.platform}** edges out {runner_up.platform}, "
                f"performing {speedup:.2f}x faster on {report.benchmark_name} at SF{report.scale_factor}."
            )
        else:
            return (
                f"**{winner.platform}** and {runner_up.platform} show comparable performance "
                f"on {report.benchmark_name} at SF{report.scale_factor}, "
                f"with {winner.platform} having a slight edge."
            )

    def _generate_executive_summary(self, report: ComparisonReport) -> str:
        """Generate executive summary paragraph.

        Args:
            report: Comparison report

        Returns:
            Executive summary string
        """
        if not report.rankings:
            return "Insufficient data for executive summary."

        platforms_str = ", ".join(report.platforms)
        num_queries = len(report.query_comparisons)
        winner = report.rankings[0]

        # Base summary
        summary_parts = [
            f"This comparison analyzes {len(report.platforms)} database platforms "
            f"({platforms_str}) on {report.benchmark_name} at scale factor {report.scale_factor}, "
            f"executing {num_queries} queries."
        ]

        # Winner info
        if winner.win_rate >= self.config.win_rate_threshold:
            summary_parts.append(
                f"{winner.platform} emerges as the dominant performer, winning {winner.win_rate:.0f}% of queries."
            )
        else:
            summary_parts.append(f"{winner.platform} ranks first with a win rate of {winner.win_rate:.0f}%.")

        # Cost info if available
        if report.cost_analysis:
            best_value = report.cost_analysis.best_value
            if best_value != winner.platform:
                summary_parts.append(f"However, {best_value} offers the best price-performance ratio.")

        # Statistical significance
        sig_pct = report.statistical_summary.get("significant_percent", 0)
        if sig_pct > 0:
            summary_parts.append(
                f"Statistical testing confirms {sig_pct:.0f}% of performance differences are significant."
            )

        return " ".join(summary_parts)

    def _generate_key_findings(self, report: ComparisonReport) -> list[str]:
        """Generate key findings list.

        Args:
            report: Comparison report

        Returns:
            List of key finding strings
        """
        findings = []

        if not report.rankings:
            return findings

        winner = report.rankings[0]

        # Finding 1: Winner
        findings.append(
            f"{winner.platform} achieves the fastest geometric mean query time ({winner.geometric_mean_time:.2f}ms)"
        )

        # Finding 2: Win/loss
        if winner.win_rate >= self.config.win_rate_threshold:
            findings.append(f"{winner.platform} wins {winner.win_rate:.0f}% of individual query matchups")

        # Finding 3: Head-to-head
        for h2h in report.head_to_head[:2]:  # Top 2 most interesting
            if h2h.winner and h2h.performance_ratio > 1.2:
                slower = h2h.platform_a if h2h.performance_ratio > 1 else h2h.platform_b
                faster = h2h.platform_b if h2h.performance_ratio > 1 else h2h.platform_a
                ratio = h2h.performance_ratio if h2h.performance_ratio > 1 else 1 / h2h.performance_ratio
                findings.append(f"{faster} is {ratio:.2f}x faster than {slower} overall")

        # Finding 4: Consistency
        for ranking in report.rankings:
            wl = report.win_loss_matrix.get(ranking.platform)
            if wl and wl.ties > wl.total * 0.5:
                findings.append(f"{ranking.platform} shows highly consistent performance across queries")
                break

        # Finding 5: Cost (if available)
        if report.cost_analysis:
            findings.append(f"{report.cost_analysis.best_value} delivers the best value (highest queries per dollar)")

        return findings[: self.config.max_insights_per_category]

    def _generate_performance_insights(self, report: ComparisonReport) -> list[str]:
        """Generate performance-specific insights.

        Args:
            report: Comparison report

        Returns:
            List of performance insights
        """
        insights = []

        # Analyze rankings
        for i, ranking in enumerate(report.rankings):
            if i == 0:
                insights.append(
                    f"{ranking.platform} ranks #1 with geometric mean of {ranking.geometric_mean_time:.2f}ms"
                )
            elif ranking.geometric_mean_time > report.rankings[0].geometric_mean_time * 2:
                insights.append(
                    f"{ranking.platform} is significantly slower, "
                    f"ranking #{ranking.rank} at {ranking.geometric_mean_time:.2f}ms"
                )

        # Analyze query variance
        for qc in list(report.query_comparisons.values())[:5]:
            if len(qc.platforms) >= 2:
                max_ratio = max(qc.performance_ratios.values())
                if max_ratio > 2.0:
                    slowest = max(qc.performance_ratios.keys(), key=lambda p: qc.performance_ratios[p])
                    insights.append(f"Query {qc.query_id}: {qc.winner} is {max_ratio:.1f}x faster than {slowest}")

        # Statistical significance
        sig_count = report.statistical_summary.get("significant_count", 0)
        total_tests = report.statistical_summary.get("total_tests", 0)
        if sig_count > 0:
            insights.append(f"{sig_count}/{total_tests} query comparisons show statistically significant differences")

        return insights[: self.config.max_insights_per_category]

    def _generate_cost_insights(
        self,
        cost_analysis: CostPerformanceAnalysis,
    ) -> list[str]:
        """Generate cost-specific insights.

        Args:
            cost_analysis: Cost analysis results

        Returns:
            List of cost insights
        """
        insights = []

        # Best value
        insights.append(f"{cost_analysis.best_value} offers the best price/performance ratio")

        # Cost rankings
        if len(cost_analysis.cost_rankings) >= 2:
            cheapest = cost_analysis.cost_rankings[0]
            most_expensive = cost_analysis.cost_rankings[-1]
            insights.append(
                f"{cheapest} is the most cost-effective option, while {most_expensive} has the highest costs"
            )

        # Potential savings
        for platform, savings in cost_analysis.potential_savings.items():
            if savings > 0 and platform == cost_analysis.cost_rankings[0]:
                most_expensive = cost_analysis.cost_rankings[-1]
                insights.append(
                    f"Switching from {most_expensive} to {platform} could save ${savings:.2f} per benchmark run"
                )
                break

        # Cost per query
        if cost_analysis.cost_per_query:
            min_cpq = min(cost_analysis.cost_per_query.values())
            max_cpq = max(cost_analysis.cost_per_query.values())
            if max_cpq > min_cpq * 2:
                insights.append(f"Cost per query varies {max_cpq / min_cpq:.1f}x between platforms")

        return insights[: self.config.max_insights_per_category]

    def _generate_recommendations(self, report: ComparisonReport) -> list[str]:
        """Generate platform recommendations.

        Args:
            report: Comparison report

        Returns:
            List of recommendation strings
        """
        recommendations = []

        if not report.rankings:
            return recommendations

        winner = report.rankings[0]

        # Performance-focused recommendation
        recommendations.append(f"For maximum performance: Choose {winner.platform}")

        # Cost-focused recommendation
        if report.cost_analysis:
            if report.cost_analysis.best_value != winner.platform:
                recommendations.append(
                    f"For best value: Consider {report.cost_analysis.best_value} (better price/performance)"
                )

        # Consistency recommendation
        most_consistent = None
        for ranking in report.rankings:
            # Find platform with most ties (consistent across queries)
            wl = report.win_loss_matrix.get(ranking.platform)
            if wl and wl.ties > wl.total * 0.4:
                most_consistent = ranking.platform
                break

        if most_consistent and most_consistent != winner.platform:
            recommendations.append(f"For predictable performance: {most_consistent} shows consistent query times")

        # Scale factor consideration
        sf = report.scale_factor
        if sf <= 1:
            recommendations.append("Test at larger scale factors (SF10+) for production-relevant insights")

        return recommendations[: self.config.max_insights_per_category]

    def _generate_query_highlights(self, report: ComparisonReport) -> list[str]:
        """Generate notable query-specific highlights.

        Args:
            report: Comparison report

        Returns:
            List of query highlight strings
        """
        highlights = self._find_gap_highlights(report.query_comparisons, self.config.performance_threshold)
        highlights += self._find_surprising_win_highlights(report.query_comparisons, report.rankings, report.platforms)
        return highlights[: self.config.max_insights_per_category]

    def _find_gap_highlights(
        self,
        query_comparisons: dict[str, Any],
        threshold: float,
    ) -> list[str]:
        """Find queries with largest performance gaps between platforms.

        Args:
            query_comparisons: Mapping of query ID to QueryComparison
            threshold: Minimum performance ratio to consider noteworthy

        Returns:
            List of gap highlight strings (up to 3)
        """
        highlights = []
        gap_queries = []
        for query_id, qc in query_comparisons.items():
            if len(qc.performance_ratios) >= 2:
                max_ratio = max(qc.performance_ratios.values())
                gap_queries.append((query_id, qc, max_ratio))

        gap_queries.sort(key=lambda x: x[2], reverse=True)

        for query_id, qc, max_ratio in gap_queries[:3]:
            if max_ratio > threshold:
                slowest = max(qc.performance_ratios.keys(), key=lambda p: qc.performance_ratios[p])
                highlights.append(f"Query {query_id}: {qc.winner} excels ({max_ratio:.1f}x faster than {slowest})")

        return highlights

    def _find_surprising_win_highlights(
        self,
        query_comparisons: dict[str, Any],
        rankings: list[Any],
        platforms: list[str],
    ) -> list[str]:
        """Find queries where a non-leader platform wins unexpectedly.

        Args:
            query_comparisons: Mapping of query ID to QueryComparison
            rankings: Platform rankings (first entry is overall winner)
            platforms: List of platform names in the comparison

        Returns:
            List of surprising win highlight strings
        """
        if not rankings:
            return []

        overall_winner = rankings[0].platform
        alt_winner_counts: dict[str, int] = {}
        for _query_id, qc in query_comparisons.items():
            if qc.winner != overall_winner and qc.winner in platforms:
                alt_winner_counts[qc.winner] = alt_winner_counts.get(qc.winner, 0) + 1

        highlights = []
        for platform, count in sorted(alt_winner_counts.items(), key=lambda x: -x[1])[:1]:
            if count >= 3:
                highlights.append(f"{platform} wins {count} queries despite ranking behind {overall_winner} overall")

        return highlights

    def _generate_blog_snippet(
        self,
        report: ComparisonReport,
        insights: InsightReport,
    ) -> str:
        """Generate ready-to-use blog post snippet.

        Args:
            report: Comparison report
            insights: Generated insights

        Returns:
            Blog-ready paragraph
        """
        if not report.rankings:
            return ""

        winner = report.rankings[0]
        platforms_str = (
            ", ".join(report.platforms[:-1]) + f" and {report.platforms[-1]}"
            if len(report.platforms) > 1
            else report.platforms[0]
        )

        snippet_parts = []

        # Opening
        snippet_parts.append(
            f"In our head-to-head benchmark comparison of {platforms_str} "
            f"using {report.benchmark_name} at scale factor {report.scale_factor}, "
            f"**{winner.platform}** emerges as the performance leader."
        )

        # Key finding
        if len(report.rankings) > 1:
            runner_up = report.rankings[1]
            speedup = runner_up.geometric_mean_time / winner.geometric_mean_time
            if speedup > 1.1:
                snippet_parts.append(
                    f"With a geometric mean query time of {winner.geometric_mean_time:.2f}ms, "
                    f"{winner.platform} outperforms {runner_up.platform} by {speedup:.2f}x."
                )

        # Win rate
        if winner.win_rate >= 60:
            snippet_parts.append(
                f"{winner.platform} wins {winner.win_rate:.0f}% of individual query comparisons, "
                f"demonstrating consistent superiority across diverse query patterns."
            )

        # Cost consideration
        if report.cost_analysis and report.cost_analysis.best_value != winner.platform:
            snippet_parts.append(
                f"However, for cost-conscious deployments, {report.cost_analysis.best_value} "
                f"offers the best price/performance ratio."
            )

        return " ".join(snippet_parts)


def generate_comparison_narrative(
    report: ComparisonReport,
    config: Optional[InsightConfig] = None,
) -> str:
    """Generate a complete narrative from comparison results.

    Convenience function that creates an InsightGenerator and returns
    the markdown-formatted insights.

    Args:
        report: ComparisonReport to analyze
        config: Optional InsightConfig

    Returns:
        Markdown-formatted narrative string
    """
    generator = InsightGenerator(config)
    insights = generator.generate(report)
    return insights.to_markdown()


def generate_blog_snippet(
    report: ComparisonReport,
    config: Optional[InsightConfig] = None,
) -> str:
    """Generate a blog-ready snippet from comparison results.

    Convenience function that creates an InsightGenerator and returns
    just the blog snippet.

    Args:
        report: ComparisonReport to analyze
        config: Optional InsightConfig

    Returns:
        Blog-ready paragraph string
    """
    generator = InsightGenerator(config)
    insights = generator.generate(report)
    return insights.blog_snippet
