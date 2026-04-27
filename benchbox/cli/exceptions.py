"""Standardized CLI exceptions and error handling.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

from rich.console import Console
from rich.markup import escape

from benchbox.core.exceptions import ConfigurationError as CoreConfigurationError
from benchbox.utils.dependencies import get_install_command
from benchbox.utils.printing import QuietConsoleProxy, quiet_console

try:
    from benchbox.utils.version import (
        check_version_consistency,
        format_version_report,
        get_version_info,
    )
except ImportError:
    format_version_report: Callable[[], str] | None = None
    check_version_consistency: Callable[[], None] | None = None
    get_version_info: Callable[[], dict[str, Any]] | None = None


class BenchboxCLIError(Exception):
    """Base exception for all CLI errors."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None, include_version: bool = True):
        super().__init__(message)
        self.message = message
        self.details = details or {}

        # Capture source location (file, line, function) where error was raised
        import inspect
        import sys

        try:
            # Try to get traceback from current exception first
            tb = sys.exc_info()[2]
            if tb is not None:
                # Walk up the traceback to find the first frame outside this file
                while tb.tb_next is not None:
                    frame = tb.tb_frame
                    filename = frame.f_code.co_filename
                    # Skip frames in this exceptions.py file
                    if not filename.endswith("exceptions.py"):
                        break
                    tb = tb.tb_next

                frame = tb.tb_frame
                self.source_file = frame.f_code.co_filename
                self.source_line = tb.tb_lineno
                self.source_function = frame.f_code.co_name
            else:
                # No active exception - use inspect to find caller
                # Get the stack frames and find first frame outside exceptions.py
                stack = inspect.stack()
                for frame_info in stack[1:]:  # Skip this __init__ frame
                    if not frame_info.filename.endswith("exceptions.py"):
                        self.source_file = frame_info.filename
                        self.source_line = frame_info.lineno
                        self.source_function = frame_info.function
                        break
                else:
                    # Fallback: use immediate caller
                    if len(stack) > 1:
                        self.source_file = stack[1].filename
                        self.source_line = stack[1].lineno
                        self.source_function = stack[1].function
                    else:
                        self.source_file = None
                        self.source_line = None
                        self.source_function = None
        except Exception:
            # If we can't get source location, that's ok
            self.source_file = None
            self.source_line = None
            self.source_function = None

        # Add version information to error details for debugging
        if include_version and get_version_info:
            try:
                info = get_version_info()
                self.details.setdefault("benchbox_version", info.get("benchbox_version"))
                self.details.setdefault("release_tag", info.get("release_tag"))
                self.details.setdefault("version_consistent", info.get("version_consistent"))
                self.details.setdefault("version_message", info.get("version_message"))
                self.details.setdefault("version_expected", info.get("expected_version"))

                # Add version consistency info if there are issues
                if not info.get("version_consistent", True):
                    self.details.setdefault("version_warning", info.get("version_message"))
                    self.details.setdefault("version_details", info.get("version_sources"))
            except Exception:
                # Gracefully handle any issues with version reporting
                pass


class ConfigurationError(CoreConfigurationError, BenchboxCLIError):
    """Error in benchmark or system configuration.

    Extends the core ConfigurationError with CLI-specific features:
    - Version information tracking
    - Source location tracking
    - Rich error context for better debugging

    Inherits from both:
    - CoreConfigurationError: Base exception used by platform adapters
    - BenchboxCLIError: CLI-specific error handling with metadata
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None, include_version: bool = True):
        """Initialize CLI configuration error.

        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
            include_version: Whether to include version information in error details
        """
        # Initialize core exception (sets message and details)
        CoreConfigurationError.__init__(self, message, details)
        # Initialize CLI exception (adds version info and source tracking)
        BenchboxCLIError.__init__(self, message, details, include_version)


class DatabaseError(BenchboxCLIError):
    """Error related to database operations."""


class ExecutionError(BenchboxCLIError):
    """Error during benchmark execution."""


class ValidationError(BenchboxCLIError):
    """Error in input validation."""


class CloudStorageError(BenchboxCLIError):
    """Error related to cloud storage operations."""


class PlatformError(BenchboxCLIError):
    """Error related to platform adapter operations."""


@dataclass
class ErrorContext:
    """Context information for error handling."""

    operation: str
    stage: str
    benchmark_name: Optional[str] = None
    database_type: Optional[str] = None
    user_input: Optional[dict[str, Any]] = None
    system_info: Optional[dict[str, Any]] = None
    include_version_info: bool = True
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    source_function: Optional[str] = None

    def __post_init__(self):
        """Add version information to system_info if requested."""
        if self.include_version_info and self.system_info is None:
            self.system_info = {}

        if self.include_version_info and get_version_info:
            try:
                info = get_version_info()
                self.system_info["benchbox_version"] = info.get("benchbox_version")
                self.system_info["release_tag"] = info.get("release_tag")
                self.system_info["version_consistent"] = info.get("version_consistent")
                self.system_info.setdefault("expected_version", info.get("expected_version"))
                self.system_info.setdefault("version_message", info.get("version_message"))
                if not info.get("version_consistent", True):
                    self.system_info["version_warning"] = info.get("version_message")
                    self.system_info["version_details"] = info.get("version_sources")
                else:
                    self.system_info.setdefault("documentation_versions", info.get("documentation_versions"))
            except Exception:
                # Gracefully handle version info failures
                pass


class ErrorHandler:
    """Centralized error handling and reporting."""

    def __init__(self, console: Union[Console, QuietConsoleProxy, None] = None):
        self.console = console or quiet_console
        self.logger = logging.getLogger(__name__)

    def handle_error(
        self,
        error: Exception,
        context: Optional[ErrorContext] = None,
        show_traceback: bool = False,
    ) -> None:
        """Handle and display errors with context."""

        # Log the error
        self.logger.error(f"Error in {context.operation if context else 'unknown'}: {str(error)}")

        if isinstance(error, BenchboxCLIError):
            self._handle_cli_error(error, context, show_traceback)
        else:
            self._handle_generic_error(error, context, show_traceback)

    def _handle_cli_error(
        self,
        error: BenchboxCLIError,
        context: Optional[ErrorContext],
        show_traceback: bool,
    ) -> None:
        """Handle BenchBox CLI specific errors."""

        # Transfer source location from error to context if not already set
        if context and hasattr(error, "source_file"):
            if not context.source_file and error.source_file:
                context.source_file = error.source_file
                context.source_line = error.source_line
                context.source_function = error.source_function

        # Error type → (header label, help method name); checked in order (subclasses first).
        _ERROR_DISPATCH = [
            (ConfigurationError, "Configuration Error", "_show_configuration_help"),
            (DatabaseError, "Database Error", "_show_database_help"),
            (ExecutionError, "Execution Error", "_show_execution_help"),
            (ValidationError, "Input Validation Error", "_show_validation_help"),
            (CloudStorageError, "Cloud Storage Error", "_show_cloud_storage_help"),
            (PlatformError, "Platform Error", "_show_platform_help"),
        ]
        matched = next(((label, fn) for t, label, fn in _ERROR_DISPATCH if isinstance(error, t)), None)
        if matched:
            label, fn = matched
            self.console.print(f"\n[red]❌ {label}[/red]")
            getattr(self, fn)(error, context)
        else:
            self.console.print("\n[red]❌ Error[/red]")

        # Show the error message
        self.console.print(f"[red]{error.message}[/red]")

        # Show details if available
        if error.details:
            self.console.print("\n[yellow]Details:[/yellow]")
            for key, value in error.details.items():
                if key == "version_warning":
                    self.console.print(f"  [orange1]⚠️️  {key}: {value}[/orange1]")
                elif key.startswith("version"):
                    self.console.print(f"  [dim]{key}: {value}[/dim]")
                else:
                    self.console.print(f"  {key}: {value}")

        # Show context if available
        if context:
            self._show_context_info(context)

        # Show traceback if requested
        if show_traceback:
            import traceback

            self.console.print("\n[dim]Traceback:[/dim]")
            self.console.print(f"[dim]{traceback.format_exc()}[/dim]")

    def _handle_generic_error(self, error: Exception, context: Optional[ErrorContext], show_traceback: bool) -> None:
        """Handle generic Python exceptions."""

        self.console.print("\n[red]❌ Unexpected Error[/red]")
        self.console.print(f"[red]{str(error)}[/red]")

        if context:
            self._show_context_info(context)

        if show_traceback:
            import traceback

            self.console.print("\n[dim]Traceback:[/dim]")
            self.console.print(f"[dim]{traceback.format_exc()}[/dim]")

        # Show version information for bug reports
        if format_version_report:
            try:
                self.console.print("\n[dim]Version Information:[/dim]")
                # Get version report but make it more compact for error display
                version_info = format_version_report()
                # Extract just the version lines for error display
                for line in version_info.split("\n"):
                    if line.strip() and ("Version:" in line or "Consistency:" in line or "Release" in line):
                        self.console.print(f"[dim]  {line.strip()}[/dim]")
            except Exception:
                # Fallback to basic version if detailed report fails
                try:
                    import benchbox

                    self.console.print(f"[dim]  BenchBox Version: {benchbox.__version__}[/dim]")
                except Exception:
                    pass

        # Suggest reporting the issue
        self.console.print("\n[yellow]This appears to be an unexpected error.[/yellow]")
        self.console.print("Please report this issue at: [blue]https://github.com/joeharris76/benchbox/issues[/blue]")
        self.console.print("[dim]Include the version information above in your report.[/dim]")

    def _show_configuration_help(self, error: BenchboxCLIError, context: Optional[ErrorContext]) -> None:
        """Show configuration-specific help."""
        self.console.print("\n[yellow]Configuration Help:[/yellow]")
        self.console.print("• Check benchmark name and scale factor")
        self.console.print("• Verify output directory permissions")
        self.console.print("• Review benchmark-specific configuration options")

    def _show_database_help(self, error: BenchboxCLIError, context: Optional[ErrorContext]) -> None:
        """Show database-specific help."""
        self.console.print("\n[yellow]Database Help:[/yellow]")
        self.console.print("• Verify database is installed and accessible")
        self.console.print("• Check connection parameters")
        self.console.print("• Ensure database supports OLAP operations (for analytical benchmarks)")

        if context and context.database_type:
            if context.database_type.lower() == "duckdb":
                self.console.print("• DuckDB is recommended for OLAP benchmarks")
            elif context.database_type.lower() in ["postgresql", "mysql"]:
                self.console.print("• Ensure database server is running and accessible")

    def _show_execution_help(self, error: BenchboxCLIError, context: Optional[ErrorContext]) -> None:
        """Show execution-specific help."""
        self.console.print("\n[yellow]Execution Help:[/yellow]")
        self.console.print("• Check available memory and disk space")
        self.console.print("• Verify benchmark data generation completed successfully")
        self.console.print("• Consider using smaller scale factor for testing")

        if context and context.benchmark_name and context.benchmark_name.lower() in ["tpch", "tpcds"]:
            self.console.print("• TPC benchmarks require significant resources")
            self.console.print("• Consider scale factors: 0.01 (test), 0.1 (small), 1.0 (medium)")

    def _show_validation_help(self, error: BenchboxCLIError, context: Optional[ErrorContext]) -> None:
        """Show validation-specific help."""
        self.console.print("\n[yellow]Input Validation Help:[/yellow]")
        self.console.print("• Check command line arguments and options")
        self.console.print("• Verify file paths exist and are accessible")
        self.console.print("• Ensure numeric values are within valid ranges")

    def _show_cloud_storage_help(self, error: BenchboxCLIError, context: Optional[ErrorContext]) -> None:
        """Show cloud storage-specific help."""
        self.console.print("\n[yellow]Cloud Storage Help:[/yellow]")
        self.console.print("• Verify cloud credentials are configured")
        self.console.print("• Check bucket/container permissions")
        install_cmd = escape(get_install_command("cloudstorage"))
        self.console.print(f"• Ensure cloudpathlib is installed: {install_cmd}")

        # Show provider-specific help
        if error.details and "provider" in error.details:
            provider = error.details["provider"]
            if provider == "s3":
                self.console.print("• AWS S3 credentials (any of the following):")
                self.console.print("    - Run: aws configure")
                self.console.print("    - Or set: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
                self.console.print("    - Or use: AWS_PROFILE=your-profile")
                self.console.print("    - Or use IAM role (EC2/ECS/Lambda)")
            elif provider in ["gs", "gcs"]:
                self.console.print("• Google Cloud: Set GOOGLE_APPLICATION_CREDENTIALS")
            elif provider in ["abfss", "azure"]:
                self.console.print("• Azure: Set AZURE_STORAGE_ACCOUNT_NAME and AZURE_STORAGE_ACCOUNT_KEY")

    def _show_platform_help(self, error: BenchboxCLIError, context: Optional[ErrorContext]) -> None:
        """Show platform-specific help."""
        self.console.print("\n[yellow]Platform Help:[/yellow]")
        self.console.print("• Verify database drivers are installed")
        self.console.print("• Check platform adapter compatibility")
        self.console.print("• Ensure database service is running")

    def _show_context_info(self, context: ErrorContext) -> None:
        """Show context information."""
        self.console.print("\n[dim]Context:[/dim]")
        self.console.print(f"[dim]  Operation: {context.operation}[/dim]")
        self.console.print(f"[dim]  Stage: {context.stage}[/dim]")

        if context.benchmark_name:
            self.console.print(f"[dim]  Benchmark: {context.benchmark_name}[/dim]")

        if context.database_type:
            self.console.print(f"[dim]  Database: {context.database_type}[/dim]")

        # Show source location if available
        if context.source_file and context.source_line:
            # Shorten the file path for readability
            from pathlib import Path

            try:
                source_path = Path(context.source_file)
                # Try to show path relative to benchbox package
                if "benchbox" in source_path.parts:
                    idx = source_path.parts.index("benchbox")
                    relative_path = Path(*source_path.parts[idx:])
                    self.console.print(f"[dim]  Location: {relative_path}:{context.source_line}[/dim]")
                else:
                    # Fallback to filename only
                    self.console.print(f"[dim]  Location: {source_path.name}:{context.source_line}[/dim]")

                if context.source_function:
                    self.console.print(f"[dim]  Function: {context.source_function}()[/dim]")
            except Exception:
                # Fallback to raw file path
                self.console.print(f"[dim]  Location: {context.source_file}:{context.source_line}[/dim]")

        # Show system info including version information
        if context.system_info:
            for key, value in context.system_info.items():
                if key == "version_warning":
                    self.console.print(f"[orange1]  ⚠️️  {key}: {value}[/orange1]")
                elif key.startswith("version") or key == "benchbox_version":
                    self.console.print(f"[dim]  {key}: {value}[/dim]")
                else:
                    self.console.print(f"[dim]  {key}: {value}[/dim]")


def create_error_handler(console: Union[Console, QuietConsoleProxy, None] = None) -> ErrorHandler:
    """Factory function to create error handler."""
    return ErrorHandler(console)


class ValidationRules:
    """Common validation rules for CLI inputs."""

    @staticmethod
    def validate_scale_factor(scale_factor: float) -> None:
        """Validate scale factor input."""
        if scale_factor <= 0:
            raise ValidationError(
                "Scale factor must be positive",
                details={"provided_value": scale_factor, "valid_range": "> 0"},
            )

        if scale_factor > 100:
            raise ValidationError(
                "Scale factor is very large and may cause resource issues",
                details={
                    "provided_value": scale_factor,
                    "recommended_range": "0.01 - 10.0",
                    "warning": "Large scale factors require significant memory and disk space",
                },
            )

    @staticmethod
    def validate_benchmark_name(name: str, available_benchmarks: list[str]) -> None:
        """Validate benchmark name."""
        if not name:
            raise ValidationError("Benchmark name cannot be empty")

        if name.lower() not in [b.lower() for b in available_benchmarks]:
            raise ValidationError(
                f"Unknown benchmark: {name}",
                details={
                    "provided_name": name,
                    "available_benchmarks": available_benchmarks,
                },
            )

    @staticmethod
    def validate_output_directory(output_dir: str) -> None:
        """Validate output directory."""
        from benchbox.utils.cloud_storage import (
            is_cloud_path,
            validate_cloud_credentials,
        )

        if is_cloud_path(output_dir):
            # Validate cloud credentials
            validation = validate_cloud_credentials(output_dir)
            if not validation["valid"]:
                raise CloudStorageError(
                    "Cloud storage credentials validation failed",
                    details={
                        "path": output_dir,
                        "provider": validation["provider"],
                        "error": validation["error"],
                        "required_env_vars": validation["env_vars"],
                    },
                )
        else:
            # Validate local directory
            from pathlib import Path

            try:
                path = Path(output_dir)
                path.mkdir(parents=True, exist_ok=True)
            except (OSError, PermissionError) as e:
                raise ValidationError(
                    f"Cannot create output directory: {output_dir}",
                    details={"path": output_dir, "error": str(e)},
                ) from e
