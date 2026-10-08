from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from benchbox.core.results.query_plan_models import (
    JoinType,
    LogicalOperator,
    LogicalOperatorType,
)

if TYPE_CHECKING:
    from benchbox.core.results.query_plan_models import QueryPlanDAG


@dataclass
class PlanComplexityScore:
    total_operators: int = 0
    join_count: int = 0
    join_complexity: int = 0
    aggregation_count: int = 0
    subquery_depth: int = 0
    max_tree_depth: int = 0
    scan_count: int = 0
    filter_count: int = 0
    sort_count: int = 0
    overall_score: int = 0
    complexity_level: str = "low"

    def to_dict(self) -> dict:
        return {
            "total_operators": self.total_operators,
            "join_count": self.join_count,
            "join_complexity": self.join_complexity,
            "aggregation_count": self.aggregation_count,
            "subquery_depth": self.subquery_depth,
            "max_tree_depth": self.max_tree_depth,
            "scan_count": self.scan_count,
            "filter_count": self.filter_count,
            "sort_count": self.sort_count,
            "overall_score": self.overall_score,
            "complexity_level": self.complexity_level,
        }


@dataclass
class PlanInsight:
    category: str
    title: str
    description: str
    operator_id: str | None = None
    severity: str = "medium"

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "operator_id": self.operator_id,
            "severity": self.severity,
        }


@dataclass
class PlanAnalysisResult:
    query_id: str
    complexity: PlanComplexityScore
    insights: list[PlanInsight] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query_id": self.query_id,
            "complexity": self.complexity.to_dict(),
            "insights": [i.to_dict() for i in self.insights],
        }


def _get_join_complexity(op: LogicalOperator) -> int:
    if op.join_type == JoinType.CROSS:
        return 3
    if op.join_type in (JoinType.FULL, JoinType.ANTI):
        return 2
    return 1


def _classify_complexity_level(overall_score: int) -> str:
    if overall_score < 20:
        return "low"
    if overall_score < 50:
        return "medium"
    if overall_score < 80:
        return "high"
    return "very_high"


def compute_complexity_score(plan: QueryPlanDAG) -> PlanComplexityScore:
    score = PlanComplexityScore()

    _counter_map = {
        LogicalOperatorType.AGGREGATE: "aggregation_count",
        LogicalOperatorType.SCAN: "scan_count",
        LogicalOperatorType.FILTER: "filter_count",
        LogicalOperatorType.SORT: "sort_count",
    }

    def analyze_node(op: LogicalOperator, depth: int) -> None:
        score.total_operators += 1
        score.max_tree_depth = max(score.max_tree_depth, depth)

        if op.operator_type == LogicalOperatorType.JOIN:
            score.join_count += 1
            score.join_complexity += _get_join_complexity(op)
        elif op.operator_type == LogicalOperatorType.SUBQUERY:
            score.subquery_depth = max(score.subquery_depth, 1)
        elif op.operator_type in _counter_map:
            field_name = _counter_map[op.operator_type]
            setattr(score, field_name, getattr(score, field_name) + 1)

        for child in op.children:
            analyze_node(child, depth + 1)

    if plan.logical_root:
        analyze_node(plan.logical_root, 0)

    score.overall_score = min(
        100,
        (
            score.total_operators * 2
            + score.join_complexity * 8
            + score.aggregation_count * 5
            + score.subquery_depth * 15
            + max(0, score.max_tree_depth - 3) * 3
        ),
    )

    score.complexity_level = _classify_complexity_level(score.overall_score)

    return score


def detect_antipatterns(plan: QueryPlanDAG) -> list[PlanInsight]:
    insights: list[PlanInsight] = []

    if not plan.logical_root:
        return insights

    tables_scanned: dict[str, list[str]] = {}

    def check_node(op: LogicalOperator, depth: int) -> None:
        if op.operator_type == LogicalOperatorType.JOIN:
            if op.join_type == JoinType.CROSS:
                insights.append(
                    PlanInsight(
                        category="warning",
                        title="Cross Join Detected",
                        description="Cross join may produce large intermediate result. "
                        "Ensure this is intentional and not a missing join condition.",
                        operator_id=op.operator_id,
                        severity="high",
                    )
                )

            if not op.join_conditions and op.join_type != JoinType.CROSS:
                insights.append(
                    PlanInsight(
                        category="info",
                        title="Join Without Visible Condition",
                        description="Join operator has no visible join condition. "
                        "This may be normal if condition is handled by filter operator.",
                        operator_id=op.operator_id,
                        severity="low",
                    )
                )

        if op.operator_type == LogicalOperatorType.SCAN and op.table_name:
            if op.table_name not in tables_scanned:
                tables_scanned[op.table_name] = []
            tables_scanned[op.table_name].append(op.operator_id)

        if depth > 8:
            insights.append(
                PlanInsight(
                    category="info",
                    title="Deep Plan Nesting",
                    description=f"Plan has depth of {depth}+ levels. Very deep plans may indicate complex subqueries.",
                    operator_id=op.operator_id,
                    severity="low",
                )
            )

        for child in op.children:
            check_node(child, depth + 1)

    check_node(plan.logical_root, 0)

    for table_name, scan_ops in tables_scanned.items():
        if len(scan_ops) > 1:
            insights.append(
                PlanInsight(
                    category="optimization",
                    title=f"Multiple Scans on {table_name}",
                    description=f"Table {table_name} is scanned {len(scan_ops)} times. "
                    "Consider rewriting query to scan table once.",
                    operator_id=scan_ops[0],
                    severity="medium",
                )
            )

    return insights


def analyze_plan(plan: QueryPlanDAG) -> PlanAnalysisResult:
    complexity = compute_complexity_score(plan)
    insights = detect_antipatterns(plan)

    if complexity.complexity_level == "very_high":
        insights.append(
            PlanInsight(
                category="warning",
                title="Very High Complexity",
                description=f"Query has complexity score of {complexity.overall_score}/100. "
                "Consider breaking into smaller queries or reviewing join strategy.",
                severity="high",
            )
        )

    if complexity.join_count > 5:
        insights.append(
            PlanInsight(
                category="info",
                title="Many Joins",
                description=f"Query has {complexity.join_count} join operations. Verify join order is optimal.",
                severity="medium",
            )
        )

    return PlanAnalysisResult(
        query_id=plan.query_id,
        complexity=complexity,
        insights=insights,
    )
