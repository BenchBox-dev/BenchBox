"""Structured error handling for BenchBox MCP server.

Provides standardized error codes, categories, and response formatting
for consistent error handling across all MCP tools.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Driver/adapter exceptions echo back the strings they were built from -
# a DSN, an ATTACH statement, a config assignment - so exception text is a
# credential materialisation channel (the #1333/#1345 family). Scrub
# secret-assignment patterns and URL userinfo before the text leaves the
# server; key-list redaction cannot help here because the secret is already
# embedded in a value.
# Keep the key vocabulary in one pattern so JSON, assignment, and prose forms
# cannot drift apart.
# Expandable keys accept common suffixes (e.g. motherduck_token). Short exact
# keys (pat) must not expand into longer non-secret words such as "path".
_SECRET_KEY_PATTERN = (
    r"(?:(?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|account[_-]?key|"
    r"key[_-]?id|credential|dsn|connection[_-]?string|private[_-]?key|sas)[a-z0-9_-]*|"
    r"pat)"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    rf"(({_SECRET_KEY_PATTERN})\s*=\s*)"
    r"(?:'[^']*'|\"[^\"]*\"|[^&\s,;'\")]+)",
    flags=re.IGNORECASE,
)
# Azure SAS tokens are query-string shaped (sv=...&sig=...); the generic value
# arm stops at ``&`` and would leave signature segments in the clear.
_SECRET_SAS_KEY_PATTERN = r"(?:storage[_-]?sas(?:[_-]?token)?|sas)[a-z0-9_-]*"
_SECRET_SAS_ASSIGNMENT_RE = re.compile(
    rf"(({_SECRET_SAS_KEY_PATTERN})\s*=\s*)"
    r"(?:'[^']*'|\"[^\"]*\"|[^\s,;'\")]+)",
    flags=re.IGNORECASE,
)
# Unquoted PEM / multi-line private keys span whitespace; the generic arm only
# takes the first token and leaves base64 body lines intact. Truncated PEM
# (BEGIN without END) and CRLF-separated base64 continuations must still mask.
_SECRET_PRIVATE_KEY_KEY_PATTERN = r"private[_-]?key[a-z0-9_-]*"
# Body lines are base64-ish; allow ``_`` so truncated PEM / test sentinels are
# not split mid-token (which re-exposes the remainder after the first mask).
_SECRET_PRIVATE_KEY_BODY_LINE = r"[A-Za-z0-9+/=_]+"
_SECRET_PRIVATE_KEY_ASSIGNMENT_RE = re.compile(
    rf"(({_SECRET_PRIVATE_KEY_KEY_PATTERN})\s*=\s*)"
    r"(?:"
    r"'[^']*'"
    r"|\"[^\"]*\""
    r"|-----BEGIN[^\n]*-----[\s\S]*?-----END[^\n]*-----"
    rf"|-----BEGIN[^\n]*-----(?:\r?\n{_SECRET_PRIVATE_KEY_BODY_LINE})*"
    rf"|[^\s,;'\")]+(?:\r?\n{_SECRET_PRIVATE_KEY_BODY_LINE})*"
    r")",
    flags=re.IGNORECASE,
)
_SECRET_QUOTED_ASSIGNMENT_RE = re.compile(
    rf"""(?P<prefix>["']{_SECRET_KEY_PATTERN}["']\s*:\s*)(?P<quote>["'])(?P<value>(?:\\.|(?!(?P=quote)).)*(?P=quote))""",
    flags=re.IGNORECASE,
)
_SECRET_COLON_ASSIGNMENT_RE = re.compile(
    rf"(?P<prefix>{_SECRET_KEY_PATTERN}\s*:\s*)(?P<value>'[^']*'|\"[^\"]*\"|[^&\s,;]+)",
    flags=re.IGNORECASE,
)
_SECRET_PROSE_CONNECTOR_RE = re.compile(
    rf"(?P<prefix>\b{_SECRET_KEY_PATTERN}\s+(?:is|was|equals?|set\s+to|configured\s+as)\s+)"
    r"(?P<value>[^\s,;:()]+)",
    flags=re.IGNORECASE,
)
_SECRET_PROSE_RE = re.compile(
    rf"(?P<prefix>\b{_SECRET_KEY_PATTERN}\s+)(?P<value>[^\s,;:()]+)",
    flags=re.IGNORECASE,
)
_NON_SECRET_SECRET_WORDS = frozenset(
    {
        "blank",
        "configured",
        "empty",
        "expired",
        "failed",
        "field",
        "found",
        "invalid",
        "is",
        "lookup",
        "missing",
        "must",
        "not",
        "null",
        "present",
        "provided",
        "required",
        "set",
        "setting",
        "should",
        "store",
        "undefined",
        "value",
        "was",
    }
)
_URL_USERINFO_RE = re.compile(r"(://)[^/@\s]+@")


def scrub_secret_material(text: str) -> str:
    """Mask secret-assignment values and URL userinfo in free text."""

    def replace_quoted(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{match.group('quote')}****{match.group('quote')}"

    def replace_colon(match: re.Match[str]) -> str:
        value = match.group("value")
        if value.lower() in _NON_SECRET_SECRET_WORDS:
            return match.group(0)
        return f"{match.group('prefix')}****"

    def replace_prose(match: re.Match[str]) -> str:
        value = match.group("value")
        if value.lower() in _NON_SECRET_SECRET_WORDS:
            return match.group(0)
        return f"{match.group('prefix')}****"

    scrubbed = _SECRET_QUOTED_ASSIGNMENT_RE.sub(replace_quoted, text)
    # Specialized arms before the generic assignment so multi-param SAS and
    # multi-line private keys are not truncated at ``&`` / first whitespace.
    scrubbed = _SECRET_PRIVATE_KEY_ASSIGNMENT_RE.sub(r"\1****", scrubbed)
    scrubbed = _SECRET_SAS_ASSIGNMENT_RE.sub(r"\1****", scrubbed)
    scrubbed = _SECRET_ASSIGNMENT_RE.sub(r"\1****", scrubbed)
    scrubbed = _SECRET_COLON_ASSIGNMENT_RE.sub(replace_colon, scrubbed)
    scrubbed = _SECRET_PROSE_CONNECTOR_RE.sub(replace_prose, scrubbed)
    scrubbed = _SECRET_PROSE_RE.sub(replace_prose, scrubbed)
    return _URL_USERINFO_RE.sub(r"\1****@", scrubbed)


class ErrorCode(str, Enum):
    """Standardized error codes for MCP tools.

    Error codes follow a hierarchical naming convention:
    - VALIDATION_*: Client-side input validation errors (4xx-style)
    - PLATFORM_*: Platform-related errors
    - BENCHMARK_*: Benchmark execution errors
    - RESOURCE_*: Resource access errors
    - INTERNAL_*: Server-side errors (5xx-style)
    """

    # Validation errors (client-side, user can fix)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    VALIDATION_UNKNOWN_PLATFORM = "VALIDATION_UNKNOWN_PLATFORM"
    VALIDATION_UNKNOWN_BENCHMARK = "VALIDATION_UNKNOWN_BENCHMARK"
    VALIDATION_INVALID_SCALE_FACTOR = "VALIDATION_INVALID_SCALE_FACTOR"
    VALIDATION_INVALID_QUERY_ID = "VALIDATION_INVALID_QUERY_ID"
    VALIDATION_INVALID_PHASE = "VALIDATION_INVALID_PHASE"
    VALIDATION_INVALID_FORMAT = "VALIDATION_INVALID_FORMAT"
    VALIDATION_UNSUPPORTED_PLATFORM = "VALIDATION_UNSUPPORTED_PLATFORM"
    VALIDATION_UNSUPPORTED_MODE = "VALIDATION_UNSUPPORTED_MODE"

    # Platform errors
    PLATFORM_UNAVAILABLE = "PLATFORM_UNAVAILABLE"
    PLATFORM_DEPENDENCIES_MISSING = "PLATFORM_DEPENDENCIES_MISSING"
    PLATFORM_CREDENTIALS_MISSING = "PLATFORM_CREDENTIALS_MISSING"
    PLATFORM_CONNECTION_FAILED = "PLATFORM_CONNECTION_FAILED"

    # Dependency errors
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"

    # Benchmark errors
    BENCHMARK_EXECUTION_FAILED = "BENCHMARK_EXECUTION_FAILED"
    BENCHMARK_DATA_GENERATION_FAILED = "BENCHMARK_DATA_GENERATION_FAILED"
    BENCHMARK_QUERY_FAILED = "BENCHMARK_QUERY_FAILED"
    BENCHMARK_VALIDATION_FAILED = "BENCHMARK_VALIDATION_FAILED"

    # Resource errors
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_INVALID_FORMAT = "RESOURCE_INVALID_FORMAT"
    RESOURCE_ACCESS_DENIED = "RESOURCE_ACCESS_DENIED"

    # Internal errors (server-side)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INTERNAL_TIMEOUT = "INTERNAL_TIMEOUT"
    INTERNAL_OUT_OF_MEMORY = "INTERNAL_OUT_OF_MEMORY"


class ErrorCategory(str, Enum):
    """Error categories for grouping and routing.

    Categories help clients understand whether errors are:
    - CLIENT: User can fix by changing input
    - PLATFORM: Requires platform configuration/setup
    - EXECUTION: Benchmark-specific runtime errors
    - SERVER: Internal errors, may be transient
    """

    CLIENT = "client"
    PLATFORM = "platform"
    EXECUTION = "execution"
    SERVER = "server"


# Mapping of error codes to categories
ERROR_CATEGORIES: dict[ErrorCode, ErrorCategory] = {
    # Validation errors are client errors
    ErrorCode.VALIDATION_ERROR: ErrorCategory.CLIENT,
    ErrorCode.VALIDATION_UNKNOWN_PLATFORM: ErrorCategory.CLIENT,
    ErrorCode.VALIDATION_UNKNOWN_BENCHMARK: ErrorCategory.CLIENT,
    ErrorCode.VALIDATION_INVALID_SCALE_FACTOR: ErrorCategory.CLIENT,
    ErrorCode.VALIDATION_INVALID_QUERY_ID: ErrorCategory.CLIENT,
    ErrorCode.VALIDATION_INVALID_PHASE: ErrorCategory.CLIENT,
    ErrorCode.VALIDATION_INVALID_FORMAT: ErrorCategory.CLIENT,
    ErrorCode.VALIDATION_UNSUPPORTED_PLATFORM: ErrorCategory.CLIENT,
    ErrorCode.VALIDATION_UNSUPPORTED_MODE: ErrorCategory.CLIENT,
    # Platform errors
    ErrorCode.PLATFORM_UNAVAILABLE: ErrorCategory.PLATFORM,
    ErrorCode.PLATFORM_DEPENDENCIES_MISSING: ErrorCategory.PLATFORM,
    ErrorCode.PLATFORM_CREDENTIALS_MISSING: ErrorCategory.PLATFORM,
    ErrorCode.PLATFORM_CONNECTION_FAILED: ErrorCategory.PLATFORM,
    # Dependency errors
    ErrorCode.DEPENDENCY_MISSING: ErrorCategory.PLATFORM,
    # Benchmark/execution errors
    ErrorCode.BENCHMARK_EXECUTION_FAILED: ErrorCategory.EXECUTION,
    ErrorCode.BENCHMARK_DATA_GENERATION_FAILED: ErrorCategory.EXECUTION,
    ErrorCode.BENCHMARK_QUERY_FAILED: ErrorCategory.EXECUTION,
    ErrorCode.BENCHMARK_VALIDATION_FAILED: ErrorCategory.EXECUTION,
    # Resource errors (usually client errors)
    ErrorCode.RESOURCE_NOT_FOUND: ErrorCategory.CLIENT,
    ErrorCode.RESOURCE_INVALID_FORMAT: ErrorCategory.CLIENT,
    ErrorCode.RESOURCE_ACCESS_DENIED: ErrorCategory.PLATFORM,
    # Internal errors
    ErrorCode.INTERNAL_ERROR: ErrorCategory.SERVER,
    ErrorCode.INTERNAL_TIMEOUT: ErrorCategory.SERVER,
    ErrorCode.INTERNAL_OUT_OF_MEMORY: ErrorCategory.SERVER,
}


@dataclass
class MCPError:
    """Structured error information for MCP responses.

    Attributes:
        code: Standardized error code from ErrorCode enum
        message: Human-readable error message
        details: Additional context about the error
        suggestion: Actionable guidance for resolving the error
        retry_hint: Whether the operation might succeed on retry
    """

    code: ErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    suggestion: str | None = None
    retry_hint: bool = False

    @property
    def category(self) -> ErrorCategory:
        """Get the error category based on error code."""
        return ERROR_CATEGORIES.get(self.code, ErrorCategory.SERVER)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for MCP response.

        Returns:
            Dictionary containing all error information.
        """
        result: dict[str, Any] = {
            "error": True,
            "error_code": self.code.value,
            "error_category": self.category.value,
            "message": self.message,
        }

        if self.details:
            result["details"] = self.details

        if self.suggestion:
            result["suggestion"] = self.suggestion

        if self.retry_hint:
            result["retry_hint"] = True

        return result


def make_error(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
    suggestion: str | None = None,
    retry_hint: bool = False,
) -> dict[str, Any]:
    """Create a standardized error response.

    This is the primary function for creating error responses in MCP tools.

    Args:
        code: Error code from ErrorCode enum
        message: Human-readable error message
        details: Additional context (optional)
        suggestion: Actionable guidance (optional)
        retry_hint: Whether retry might help (default: False)

    Returns:
        Dictionary suitable for MCP tool response.

    Example:
        return make_error(
            ErrorCode.VALIDATION_UNKNOWN_PLATFORM,
            f"Unknown platform: {platform}",
            details={"available_platforms": available},
            suggestion="Use list_platforms() to see available options"
        )
    """
    error = MCPError(
        code=code,
        message=message,
        details=details or {},
        suggestion=suggestion,
        retry_hint=retry_hint,
    )
    return error.to_dict()


def make_validation_error(
    message: str,
    details: dict[str, Any] | None = None,
    suggestion: str | None = None,
) -> dict[str, Any]:
    """Create a validation error response.

    Convenience function for common validation errors.

    Args:
        message: Error message
        details: Additional context
        suggestion: How to fix the error

    Returns:
        Standardized error response.
    """
    return make_error(
        ErrorCode.VALIDATION_ERROR,
        message,
        details=details,
        suggestion=suggestion,
    )


def make_not_found_error(
    resource_type: str,
    resource_id: str,
    available: list[str] | None = None,
    suggestion: str | None = None,
) -> dict[str, Any]:
    """Create a resource not found error response.

    Args:
        resource_type: Type of resource (e.g., "benchmark", "platform")
        resource_id: ID/name that was not found
        available: List of available options
        suggestion: Recovery hint. The default is derived from ``resource_type``
            and only names a real tool for resource types whose listing tool is
            ``list_<type>s``; pass an explicit hint for anything else.

    Returns:
        Standardized error response with suggestions.
    """
    details: dict[str, Any] = {
        "resource_type": resource_type,
        "requested": resource_id,
    }
    if available:
        details["available"] = available

    if suggestion is None and resource_type:
        suggestion = f"Use list_{resource_type}s() to see available options"

    return make_error(
        ErrorCode.RESOURCE_NOT_FOUND,
        f"{resource_type.capitalize()} '{resource_id}' not found",
        details=details,
        suggestion=suggestion,
    )


def make_platform_error(
    code: ErrorCode,
    platform: str,
    message: str,
    installation_command: str | None = None,
) -> dict[str, Any]:
    """Create a platform-related error response.

    Args:
        code: Platform error code
        platform: Platform name
        message: Error message
        installation_command: How to install/configure the platform

    Returns:
        Standardized error response.
    """
    details: dict[str, Any] = {"platform": platform}
    suggestion = installation_command if installation_command else None

    return make_error(
        code,
        message,
        details=details,
        suggestion=suggestion,
    )


def make_unsupported_mode_error(
    platform: str,
    requested_mode: str,
    supported_modes: list[str],
) -> dict[str, Any]:
    """Create an unsupported execution mode error response.

    Args:
        platform: Platform name
        requested_mode: The mode that was requested but not supported
        supported_modes: List of modes the platform actually supports

    Returns:
        Standardized error response.
    """
    return make_error(
        ErrorCode.VALIDATION_UNSUPPORTED_MODE,
        f"Platform '{platform}' does not support {requested_mode} mode",
        details={
            "platform": platform,
            "requested_mode": requested_mode,
            "supported_modes": supported_modes,
        },
        suggestion=f"Use one of: {', '.join(supported_modes)}" if supported_modes else None,
    )


def make_execution_error(
    message: str,
    execution_id: str | None = None,
    exception: Exception | None = None,
    retry_hint: bool = False,
) -> dict[str, Any]:
    """Create a benchmark execution error response.

    Args:
        message: Error message
        execution_id: Execution ID if available
        exception: Original exception if available
        retry_hint: Whether retry might help

    Returns:
        Standardized error response.
    """
    details: dict[str, Any] = {}
    if execution_id:
        details["execution_id"] = execution_id
    if exception:
        details["exception_type"] = type(exception).__name__
        details["exception_message"] = scrub_secret_material(str(exception))

    return make_error(
        ErrorCode.BENCHMARK_EXECUTION_FAILED,
        scrub_secret_material(message),
        details=details,
        retry_hint=retry_hint,
    )
