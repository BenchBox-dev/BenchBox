"""Core exception types for BenchBox."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanCaptureError(Exception):
    """Raised when query plan capture fails."""

    reason: str
    platform: str
    query_id: str
    details: str | None = None

    def __str__(self) -> str:
        base = f"{self.platform} plan capture failed for {self.query_id}: {self.reason}"
        if self.details:
            base = f"{base} ({self.details})"
        return base


class SerializationError(Exception):
    """Raised when plan serialization fails or exceeds limits."""


@dataclass
class PlanValidationError(Exception):
    """Raised when plan tree structure validation fails."""

    query_id: str
    validation_errors: list[str] = field(default_factory=list)
    plan_structure: str = ""

    def __str__(self) -> str:
        errors = "\n  - ".join(self.validation_errors)
        msg = f"Plan validation failed for {self.query_id}:\n  - {errors}"
        if self.plan_structure:
            msg = f"{msg}\nStructure: {self.plan_structure}"
        return msg


@dataclass
class PlanParseError(Exception):
    """Raised when parsing EXPLAIN output fails."""

    query_id: str
    platform: str
    error_message: str
    line_number: int | None = None
    explain_sample: str | None = None
    platform_version: str | None = None
    detected_format: str | None = None  # "json", "text", "unknown"
    recovery_hint: str | None = None

    def __str__(self) -> str:
        msg = [f"Failed to parse query plan for {self.query_id} ({self.platform}): {self.error_message}"]

        if self.line_number:
            msg.append(f"  At line: {self.line_number}")

        if self.detected_format:
            msg.append(f"  Detected format: {self.detected_format}")

        if self.explain_sample:
            # Indent the sample for readability
            sample_lines = self.explain_sample.split("\n")[:5]  # First 5 lines
            indented = "\n    ".join(sample_lines)
            msg.append(f"  EXPLAIN output sample:\n    {indented}")

        if self.platform_version:
            msg.append(f"  Platform version: {self.platform_version}")

        if self.recovery_hint:
            msg.append(f"  Hint: {self.recovery_hint}")

        return "\n".join(msg)

    @property
    def diagnostic_info(self) -> dict:
        """Get structured diagnostic information."""
        return {
            "query_id": self.query_id,
            "platform": self.platform,
            "error_message": self.error_message,
            "line_number": self.line_number,
            "detected_format": self.detected_format,
            "platform_version": self.platform_version,
            "has_explain_sample": self.explain_sample is not None,
            "recovery_hint": self.recovery_hint,
        }


class FingerprintIntegrityError(Exception):
    """Raised when plan fingerprint verification fails."""

    def __init__(self, query_id: str, message: str = "Fingerprint mismatch"):
        self.query_id = query_id
        super().__init__(f"{message} for {query_id}. Plan may have been corrupted or modified.")


class ScaleFactorNotSupportedError(ValueError):
    """Raised when scale_factor is not in the benchmark's declared scale_options.

    Subclasses ValueError so existing call sites that catch ValueError keep
    working; new code can catch ScaleFactorNotSupportedError specifically.
    """

    def __init__(self, benchmark_id: str, scale_factor: float, scale_options: list[float]):
        self.benchmark_id = benchmark_id
        self.scale_factor = scale_factor
        self.scale_options = list(scale_options)
        super().__init__(f"{benchmark_id} accepts scale_factor in {self.scale_options}; got {scale_factor}")


__all__ = [
    "PlanCaptureError",
    "SerializationError",
    "PlanValidationError",
    "PlanParseError",
    "FingerprintIntegrityError",
    "ScaleFactorNotSupportedError",
]
