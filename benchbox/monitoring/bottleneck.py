# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .profiler import ResourceTimeline, ResourceType, ResourceUtilization, calculate_utilization


class BottleneckType(str, Enum):
    CPU_BOUND = "cpu_bound"
    MEMORY_BOUND = "memory_bound"
    DISK_READ_BOUND = "disk_read_bound"
    DISK_WRITE_BOUND = "disk_write_bound"
    NETWORK_SEND_BOUND = "network_send_bound"
    NETWORK_RECV_BOUND = "network_recv_bound"
    BALANCED = "balanced"
    UNKNOWN = "unknown"


class BottleneckSeverity(str, Enum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class BottleneckIndicator:
    bottleneck_type: BottleneckType
    severity: BottleneckSeverity
    score: float
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bottleneck_type": self.bottleneck_type.value,
            "severity": self.severity.value,
            "score": self.score,
            "evidence": self.evidence,
            "recommendations": self.recommendations,
        }


@dataclass
class BottleneckAnalysis:
    primary_bottleneck: BottleneckType
    primary_severity: BottleneckSeverity
    indicators: list[BottleneckIndicator] = field(default_factory=list)
    utilizations: dict[ResourceType, ResourceUtilization] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_bottleneck": self.primary_bottleneck.value,
            "primary_severity": self.primary_severity.value,
            "indicators": [i.to_dict() for i in self.indicators],
            "utilizations": {k.value: v.to_dict() for k, v in self.utilizations.items()},
            "summary": self.summary,
        }


class BottleneckDetector:
    def __init__(
        self,
        cpu_high_threshold: float = 80.0,
        cpu_critical_threshold: float = 95.0,
        memory_high_threshold: float = 80.0,
        memory_critical_threshold: float = 95.0,
        disk_iops_high_threshold: float = 1000.0,
        disk_iops_critical_threshold: float = 5000.0,
        network_mbps_high_threshold: float = 100.0,
        network_mbps_critical_threshold: float = 1000.0,
    ):
        self.cpu_high = cpu_high_threshold
        self.cpu_critical = cpu_critical_threshold
        self.memory_high = memory_high_threshold
        self.memory_critical = memory_critical_threshold
        self.disk_iops_high = disk_iops_high_threshold
        self.disk_iops_critical = disk_iops_critical_threshold
        self.network_mbps_high = network_mbps_high_threshold
        self.network_mbps_critical = network_mbps_critical_threshold

    def analyze(self, timeline: ResourceTimeline) -> BottleneckAnalysis:
        if timeline.sample_count == 0:
            return BottleneckAnalysis(
                primary_bottleneck=BottleneckType.UNKNOWN,
                primary_severity=BottleneckSeverity.NONE,
                summary="Insufficient data for analysis",
            )

        utilizations: dict[ResourceType, ResourceUtilization] = {}
        for resource_type in ResourceType:
            utilizations[resource_type] = calculate_utilization(timeline, resource_type)

        indicators: list[BottleneckIndicator] = []
        indicators.append(self._analyze_cpu(utilizations[ResourceType.CPU]))
        indicators.append(self._analyze_memory(utilizations[ResourceType.MEMORY], timeline))
        indicators.append(self._analyze_disk_read(utilizations[ResourceType.DISK_READ]))
        indicators.append(self._analyze_disk_write(utilizations[ResourceType.DISK_WRITE]))
        indicators.append(self._analyze_network_send(utilizations[ResourceType.NETWORK_SEND]))
        indicators.append(self._analyze_network_recv(utilizations[ResourceType.NETWORK_RECV]))

        indicators.sort(key=lambda x: x.score, reverse=True)

        if indicators and indicators[0].score > 0.3:
            primary = indicators[0]
        else:
            primary = BottleneckIndicator(
                bottleneck_type=BottleneckType.BALANCED,
                severity=BottleneckSeverity.NONE,
                score=0.0,
                evidence=["No significant resource constraints detected"],
                recommendations=["System resources are well balanced"],
            )

        summary = self._generate_summary(primary, utilizations)

        return BottleneckAnalysis(
            primary_bottleneck=primary.bottleneck_type,
            primary_severity=primary.severity,
            indicators=indicators,
            utilizations=utilizations,
            summary=summary,
        )

    def _analyze_cpu(self, util: ResourceUtilization) -> BottleneckIndicator:
        evidence = []
        recommendations = []
        severity = BottleneckSeverity.NONE
        score = 0.0

        avg = util.avg_value
        peak = util.max_value

        if peak >= self.cpu_critical:
            severity = BottleneckSeverity.CRITICAL
            score = 0.9
            evidence.append(f"CPU reached {peak:.1f}% (critical threshold: {self.cpu_critical}%)")
            recommendations.append("Consider scaling up to more CPU cores")
            recommendations.append("Profile code for CPU-intensive operations")
        elif avg >= self.cpu_high:
            severity = BottleneckSeverity.HIGH
            score = 0.7
            evidence.append(f"Average CPU at {avg:.1f}% (high threshold: {self.cpu_high}%)")
            recommendations.append("Optimize compute-heavy queries")
        elif peak >= self.cpu_high:
            severity = BottleneckSeverity.MODERATE
            score = 0.5
            evidence.append(f"CPU peaked at {peak:.1f}%")
        elif avg >= self.cpu_high * 0.5:
            severity = BottleneckSeverity.LOW
            score = 0.3
            evidence.append(f"Moderate CPU usage averaging {avg:.1f}%")

        return BottleneckIndicator(
            bottleneck_type=BottleneckType.CPU_BOUND,
            severity=severity,
            score=score,
            evidence=evidence,
            recommendations=recommendations,
        )

    def _analyze_memory(self, util: ResourceUtilization, timeline: ResourceTimeline) -> BottleneckIndicator:
        evidence = []
        recommendations = []
        severity = BottleneckSeverity.NONE
        score = 0.0

        if timeline.samples:
            avg_percent = sum(s.memory_percent for s in timeline.samples) / len(timeline.samples)
            peak_percent = max(s.memory_percent for s in timeline.samples)
        else:
            avg_percent = 0.0
            peak_percent = 0.0

        if peak_percent >= self.memory_critical:
            severity = BottleneckSeverity.CRITICAL
            score = 0.9
            evidence.append(f"Memory reached {peak_percent:.1f}% (critical)")
            recommendations.append("Increase available memory")
            recommendations.append("Reduce batch sizes or result set sizes")
        elif avg_percent >= self.memory_high:
            severity = BottleneckSeverity.HIGH
            score = 0.7
            evidence.append(f"Average memory at {avg_percent:.1f}%")
            recommendations.append("Consider memory optimization")
        elif peak_percent >= self.memory_high:
            severity = BottleneckSeverity.MODERATE
            score = 0.5
            evidence.append(f"Memory peaked at {peak_percent:.1f}%")
        elif avg_percent >= self.memory_high * 0.5:
            severity = BottleneckSeverity.LOW
            score = 0.3
            evidence.append(f"Moderate memory usage at {avg_percent:.1f}%")

        return BottleneckIndicator(
            bottleneck_type=BottleneckType.MEMORY_BOUND,
            severity=severity,
            score=score,
            evidence=evidence,
            recommendations=recommendations,
        )

    def _analyze_disk_read(self, util: ResourceUtilization) -> BottleneckIndicator:
        evidence = []
        recommendations = []
        severity = BottleneckSeverity.NONE
        score = 0.0

        avg = util.avg_value
        peak = util.max_value

        if peak >= self.disk_iops_critical:
            severity = BottleneckSeverity.CRITICAL
            score = 0.85
            evidence.append(f"Disk read IOPS reached {peak:.0f} (critical)")
            recommendations.append("Consider SSD storage or faster disk subsystem")
            recommendations.append("Optimize queries to reduce I/O")
        elif avg >= self.disk_iops_high:
            severity = BottleneckSeverity.HIGH
            score = 0.65
            evidence.append(f"Average disk read IOPS at {avg:.0f}")
            recommendations.append("Consider adding more memory for caching")
        elif peak >= self.disk_iops_high:
            severity = BottleneckSeverity.MODERATE
            score = 0.45
            evidence.append(f"Disk read IOPS peaked at {peak:.0f}")
        elif avg > 0:
            severity = BottleneckSeverity.LOW
            score = avg / self.disk_iops_high * 0.3
            evidence.append(f"Disk read IOPS averaging {avg:.0f}")

        return BottleneckIndicator(
            bottleneck_type=BottleneckType.DISK_READ_BOUND,
            severity=severity,
            score=score,
            evidence=evidence,
            recommendations=recommendations,
        )

    def _analyze_disk_write(self, util: ResourceUtilization) -> BottleneckIndicator:
        evidence = []
        recommendations = []
        severity = BottleneckSeverity.NONE
        score = 0.0

        avg = util.avg_value
        peak = util.max_value

        if peak >= self.disk_iops_critical:
            severity = BottleneckSeverity.CRITICAL
            score = 0.85
            evidence.append(f"Disk write IOPS reached {peak:.0f} (critical)")
            recommendations.append("Consider SSD or NVMe storage")
            recommendations.append("Reduce write amplification")
        elif avg >= self.disk_iops_high:
            severity = BottleneckSeverity.HIGH
            score = 0.65
            evidence.append(f"Average disk write IOPS at {avg:.0f}")
            recommendations.append("Consider write batching or async writes")
        elif peak >= self.disk_iops_high:
            severity = BottleneckSeverity.MODERATE
            score = 0.45
            evidence.append(f"Disk write IOPS peaked at {peak:.0f}")
        elif avg > 0:
            severity = BottleneckSeverity.LOW
            score = avg / self.disk_iops_high * 0.3
            evidence.append(f"Disk write IOPS averaging {avg:.0f}")

        return BottleneckIndicator(
            bottleneck_type=BottleneckType.DISK_WRITE_BOUND,
            severity=severity,
            score=score,
            evidence=evidence,
            recommendations=recommendations,
        )

    def _analyze_network_send(self, util: ResourceUtilization) -> BottleneckIndicator:
        evidence = []
        recommendations = []
        severity = BottleneckSeverity.NONE
        score = 0.0

        avg = util.avg_value
        peak = util.max_value

        if peak >= self.network_mbps_critical:
            severity = BottleneckSeverity.CRITICAL
            score = 0.8
            evidence.append(f"Network send rate reached {peak:.1f} Mbps (critical)")
            recommendations.append("Consider network bandwidth upgrade")
            recommendations.append("Reduce result set sizes or use compression")
        elif avg >= self.network_mbps_high:
            severity = BottleneckSeverity.HIGH
            score = 0.6
            evidence.append(f"Average network send rate at {avg:.1f} Mbps")
            recommendations.append("Consider result pagination or compression")
        elif peak >= self.network_mbps_high:
            severity = BottleneckSeverity.MODERATE
            score = 0.4
            evidence.append(f"Network send rate peaked at {peak:.1f} Mbps")
        elif avg > 0:
            severity = BottleneckSeverity.LOW
            score = min(avg / self.network_mbps_high * 0.3, 0.3)
            evidence.append(f"Network send rate averaging {avg:.1f} Mbps")

        return BottleneckIndicator(
            bottleneck_type=BottleneckType.NETWORK_SEND_BOUND,
            severity=severity,
            score=score,
            evidence=evidence,
            recommendations=recommendations,
        )

    def _analyze_network_recv(self, util: ResourceUtilization) -> BottleneckIndicator:
        evidence = []
        recommendations = []
        severity = BottleneckSeverity.NONE
        score = 0.0

        avg = util.avg_value
        peak = util.max_value

        if peak >= self.network_mbps_critical:
            severity = BottleneckSeverity.CRITICAL
            score = 0.8
            evidence.append(f"Network receive rate reached {peak:.1f} Mbps (critical)")
            recommendations.append("Consider network bandwidth upgrade")
            recommendations.append("Optimize data transfer patterns")
        elif avg >= self.network_mbps_high:
            severity = BottleneckSeverity.HIGH
            score = 0.6
            evidence.append(f"Average network receive rate at {avg:.1f} Mbps")
            recommendations.append("Consider data locality optimization")
        elif peak >= self.network_mbps_high:
            severity = BottleneckSeverity.MODERATE
            score = 0.4
            evidence.append(f"Network receive rate peaked at {peak:.1f} Mbps")
        elif avg > 0:
            severity = BottleneckSeverity.LOW
            score = min(avg / self.network_mbps_high * 0.3, 0.3)
            evidence.append(f"Network receive rate averaging {avg:.1f} Mbps")

        return BottleneckIndicator(
            bottleneck_type=BottleneckType.NETWORK_RECV_BOUND,
            severity=severity,
            score=score,
            evidence=evidence,
            recommendations=recommendations,
        )

    def _generate_summary(
        self,
        primary: BottleneckIndicator,
        utilizations: dict[ResourceType, ResourceUtilization],
    ) -> str:
        if primary.bottleneck_type == BottleneckType.BALANCED:
            return "No significant bottlenecks detected. System resources are balanced."

        if primary.bottleneck_type == BottleneckType.UNKNOWN:
            return "Insufficient data to determine bottlenecks."

        bottleneck_names = {
            BottleneckType.CPU_BOUND: "CPU",
            BottleneckType.MEMORY_BOUND: "Memory",
            BottleneckType.DISK_READ_BOUND: "Disk Read",
            BottleneckType.DISK_WRITE_BOUND: "Disk Write",
            BottleneckType.NETWORK_SEND_BOUND: "Network Send",
            BottleneckType.NETWORK_RECV_BOUND: "Network Receive",
        }

        name = bottleneck_names.get(primary.bottleneck_type, "Unknown")
        severity = primary.severity.value

        parts = [f"Primary bottleneck: {name} ({severity} severity)."]
        if primary.evidence:
            parts.append(primary.evidence[0])
        if primary.recommendations:
            parts.append(f"Recommendation: {primary.recommendations[0]}")

        return " ".join(parts)


def quick_bottleneck_check(timeline: ResourceTimeline) -> BottleneckType:
    if timeline.sample_count == 0:
        return BottleneckType.UNKNOWN

    peak_cpu = timeline.get_peak_cpu()
    timeline.get_peak_memory_mb()
    avg_disk_read = timeline.get_avg_disk_read_iops()
    avg_disk_write = timeline.get_avg_disk_write_iops()
    avg_net_send = timeline.get_avg_network_send_mbps()
    avg_net_recv = timeline.get_avg_network_recv_mbps()

    if timeline.samples:
        peak_mem_pct = max(s.memory_percent for s in timeline.samples)
        if peak_mem_pct > 90:
            return BottleneckType.MEMORY_BOUND

    if peak_cpu > 90:
        return BottleneckType.CPU_BOUND

    if avg_disk_read > 1000:
        return BottleneckType.DISK_READ_BOUND
    if avg_disk_write > 1000:
        return BottleneckType.DISK_WRITE_BOUND

    if avg_net_send > 100 or avg_net_recv > 100:
        if avg_net_send > avg_net_recv:
            return BottleneckType.NETWORK_SEND_BOUND
        return BottleneckType.NETWORK_RECV_BOUND

    return BottleneckType.BALANCED
