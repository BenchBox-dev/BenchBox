"""
Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

Platform Registry and Factory

This module provides a centralized registry and factory for platform adapters,
enabling dynamic discovery and instantiation of platform adapters.
"""

import argparse
import importlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from benchbox.core.platform_manifest import (
    SUPPORT_STATUS_VALUES,
    SupportStatus,
    get_adapter_imports,
    get_all_platform_aliases,
    get_platform_aliases,
    get_platform_manifest_entry,
    get_platform_metadata,
    is_valid_platform_key,
)
from benchbox.core.schemas import LibraryInfo, PlatformInfo
from benchbox.platforms.base import PlatformAdapter

CostClass = Literal["free", "paid_credits", "paid_compute"]
OptionalAdapterImportStatus = Literal[
    "available",
    "missing_optional_dependency",
    "native_library_load_failure",
    "broken_adapter_import",
    "deprecated_platform",
    "intentionally_disabled",
    "not_configured",
]

# The output location the Snowflake credential prompt advertises as its
# default. It lives next to get_cloud_path_examples() — and is the first entry
# of the snowflake example list — so the prompt and the documented examples
# cannot drift apart again. Any value here must stay acceptable to
# benchbox.utils.cloud_storage.is_cloud_path, which is the classifier the run
# path uses; a test pins that agreement.
SNOWFLAKE_DEFAULT_OUTPUT_LOCATION = "@~/benchbox"

_NATIVE_IMPORT_ERROR_MARKERS = (
    "dlopen",
    "dylib",
    "cannot open shared object file",
    "image not found",
    "library not loaded",
    "undefined symbol",
    "symbol not found",
    "dll load failed",
    "failed to map segment",
)


def _is_internal_module_miss(missing_name: str, module_path: str | None = None) -> bool:
    """Return whether a ModuleNotFoundError names BenchBox code, not an SDK dependency."""
    if module_path is not None and (missing_name == module_path or missing_name.startswith(f"{module_path}.")):
        return True
    return missing_name == "benchbox" or missing_name.startswith("benchbox.")


@dataclass(frozen=True)
class OptionalAdapterDiagnostic:
    """Diagnostic detail for an optional adapter import attempt."""

    platform_name: str
    module_path: str
    class_name: str
    status: OptionalAdapterImportStatus
    support_status: Optional[SupportStatus] = None
    available: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation for CLI/tests/docs tooling."""
        return {
            "platform_name": self.platform_name,
            "module_path": self.module_path,
            "class_name": self.class_name,
            "status": self.status,
            "support_status": self.support_status,
            "available": self.available,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass
class DeploymentCapability:
    """Describes requirements and characteristics of a specific deployment mode.

    Deployment modes represent different ways to run the same database engine:
    - local: Embedded or in-process (DuckDB, chDB, SQLite)
    - self-hosted: User-managed server/cluster (ClickHouse server, Trino)
    - managed: Vendor-managed cloud service (MotherDuck, ClickHouse Cloud, Snowflake)

    Attributes:
        mode: Deployment category (local, self-hosted, or managed)
        requires_credentials: Whether authentication is needed
        requires_cloud_storage: Whether cloud storage staging is required for data loading
        requires_network: Whether network connectivity to a remote service is required
        default_for_platform: Whether this is the platform's default deployment mode
        display_name: Human-readable name for this deployment mode
        description: Description of this deployment mode
        dependencies: Additional package dependencies for this deployment mode
        auth_methods: Supported authentication methods (password, oauth, token, api_key, etc.)
    """

    mode: Literal["local", "self-hosted", "managed"]
    requires_credentials: bool = False
    requires_cloud_storage: bool = False
    requires_network: bool = False
    default_for_platform: bool = False
    display_name: str = ""
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    auth_methods: list[str] = field(default_factory=list)


@dataclass
class PlatformCapability:
    """Platform execution mode and deployment capabilities.

    Tracks which execution modes (SQL, DataFrame) a platform supports,
    its default mode, and deployment mode information.

    Attributes:
        supports_sql: Whether platform supports SQL execution mode
        supports_dataframe: Whether platform supports DataFrame execution mode
        default_mode: Default execution mode (sql or dataframe)
        deployment_modes: Available deployment modes mapped by name
        default_deployment: Name of the default deployment mode
        platform_family: Platform family for dialect inheritance (e.g., "duckdb", "clickhouse")
        inherits_from: Parent platform name for configuration inheritance
        cost_class: Coarse cost model for prompt safety gates
    """

    supports_sql: bool = False
    supports_dataframe: bool = False
    default_mode: Literal["sql", "dataframe"] = "sql"
    deployment_modes: dict[str, DeploymentCapability] = field(default_factory=dict)
    default_deployment: str = "local"
    platform_family: Optional[str] = None
    inherits_from: Optional[str] = None
    cost_class: CostClass = "free"
    unsupported_benchmarks: dict[str, str] = field(default_factory=dict)


class PlatformRegistry:
    """Registry for platform adapters with factory functionality.

    Static definitions are projected from ``benchbox.core.platform_manifest``.
    This class owns runtime adapter state and factory behavior. The
    get_platform_adapter() function in benchbox/platforms/__init__.py delegates
    to this registry for adapter lookup while handling CLI-specific concerns.

    Alias Support:
        Platform aliases (e.g., 'sqlite3' -> 'sqlite') are resolved via
        resolve_platform_name() before any lookup. This allows users to
        use familiar names while the registry maintains canonical names.
    """

    _adapters: dict[str, type[PlatformAdapter]] = {}
    _availability_cache: Optional[dict[str, bool]] = None
    _platform_metadata: dict[str, dict[str, Any]] = {}
    _auto_registered: bool = False
    _platform_aliases: dict[str, str] = get_platform_aliases("registry")

    @classmethod
    def resolve_platform_name(cls, platform_name: str) -> str:
        """Resolve user input (with possible alias) to canonical platform name.

        This method normalizes platform names and resolves aliases to their
        canonical counterparts. It should be called before any platform lookup.

        Args:
            platform_name: User-provided platform name (may be an alias)

        Returns:
            Canonical platform name (lowercase)

        Examples:
            >>> PlatformRegistry.resolve_platform_name("SQLite3")
            'sqlite'
            >>> PlatformRegistry.resolve_platform_name("azure_synapse")
            'synapse'
            >>> PlatformRegistry.resolve_platform_name("DuckDB")
            'duckdb'
        """
        normalized = platform_name.lower()
        return cls._platform_aliases.get(normalized, normalized)

    @classmethod
    def get_all_aliases(cls) -> dict[str, str]:
        """Get all platform name aliases.

        Returns:
            Dictionary mapping alias names to their canonical platform names.
            Useful for CLI help and documentation.

        Examples:
            >>> PlatformRegistry.get_all_aliases()
            {'sqlite3': 'sqlite', 'azure_synapse': 'synapse'}
        """
        return cls._platform_aliases.copy()

    @classmethod
    def _build_platform_metadata(cls) -> dict[str, dict[str, Any]]:
        """Build mutable legacy metadata from the typed manifest authority."""
        return get_platform_metadata()

    @classmethod
    def _ensure_registered(cls) -> None:
        """Lazily trigger auto_register_platforms() on first registry access.

        This avoids eagerly importing every platform adapter (and their heavy
        native dependencies like chdb/polars/datafusion/duckdb) at module load
        time.  Instead, the imports are deferred until something actually queries
        the registry, which most unit tests never do.
        """
        if not cls._auto_registered:
            cls._auto_registered = True
            auto_register_platforms()

    @classmethod
    def register_adapter(cls, platform_name: str, adapter_class: type[PlatformAdapter]) -> None:
        """Register a built-in or third-party adapter under a canonical key.

        Args:
            platform_name: Name of the platform (e.g., 'duckdb', 'databricks')
            adapter_class: Platform adapter class
        """
        normalized = platform_name.lower()
        if not is_valid_platform_key(normalized):
            raise ValueError(f"Platform {platform_name!r} is not a valid canonical adapter key")
        if normalized in get_all_platform_aliases():
            raise ValueError(f"Platform alias {platform_name!r} cannot be used as an adapter registration key")
        canonical_name = normalized
        entry = get_platform_manifest_entry(canonical_name)
        if entry is not None and entry.adapter is None:
            raise ValueError(f"Built-in platform {platform_name!r} has no runtime adapter registration")
        if not isinstance(adapter_class, type) or not issubclass(adapter_class, PlatformAdapter):
            raise TypeError(f"Adapter registered for {canonical_name!r} must subclass PlatformAdapter")

        existing = cls._adapters.get(canonical_name)
        if existing is not None and existing is not adapter_class:
            raise ValueError(
                f"Platform {canonical_name!r} is already registered with {existing.__module__}.{existing.__name__}"
            )
        cls._adapters[canonical_name] = adapter_class
        # Clear availability cache when new adapter is registered
        cls._availability_cache = None
        # Initialize metadata if not present
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

    @classmethod
    def get_adapter_class(cls, platform_name: str) -> type[PlatformAdapter]:
        """Get platform adapter class by name.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Platform adapter class

        Raises:
            ValueError: If platform is not registered
        """
        cls._ensure_registered()
        # Resolve aliases to canonical name
        canonical_name = cls.resolve_platform_name(platform_name)

        if canonical_name not in cls._adapters:
            available = ", ".join(cls.get_available_platforms())
            raise ValueError(f"Platform '{platform_name}' not registered. Available: {available}")
        return cls._adapters[canonical_name]

    @classmethod
    def create_adapter(cls, platform_name: str, config: dict[str, Any]) -> PlatformAdapter:
        """Create platform adapter instance from configuration.

        Args:
            platform_name: Name of the platform
            config: Unified configuration dictionary

        Returns:
            Platform adapter instance
        """
        adapter_class = cls.get_adapter_class(platform_name)
        return adapter_class.from_config(config)

    @classmethod
    def add_platform_arguments(cls, parser: argparse.ArgumentParser, platform_name: str) -> None:
        """Add platform-specific arguments to parser.

        Args:
            parser: Argument parser to add arguments to
            platform_name: Name of the platform
        """
        adapter_class = cls.get_adapter_class(platform_name)
        adapter_class.add_cli_arguments(parser)

    @classmethod
    def get_available_platforms(cls) -> list[str]:
        """Get list of available platform names.

        Returns:
            List of registered platform names
        """
        cls._ensure_registered()
        return list(cls._adapters.keys())

    @classmethod
    def _detect_library(cls, lib_spec: dict[str, Any]) -> LibraryInfo:
        """Detect a single library."""
        lib_name = lib_spec["name"]
        import_name = lib_spec.get("import_name", lib_name)

        try:
            module = importlib.import_module(import_name)
            version = getattr(module, "__version__", None)
            # Handle edge cases where __version__ is not a string
            # (e.g., clickhouse_connect has __version__ as a module)
            if version is not None and not isinstance(version, str):
                # Try common patterns for version submodules/attributes
                if hasattr(version, "version"):
                    version = version.version
                elif hasattr(version, "VERSION"):
                    version = version.VERSION
                else:
                    version = None
            # Ensure version is a string or None
            if version is not None and not isinstance(version, str):
                version = str(version) if version else None
            return LibraryInfo(name=lib_name, version=version, installed=True)
        except (ImportError, OSError) as e:
            return LibraryInfo(name=lib_name, version=None, installed=False, import_error=str(e))

    @staticmethod
    def _extract_requirement_package(requirement: str) -> Optional[str]:
        """Extract distribution name from a requirement string."""

        if not requirement:
            return None

        requirement = requirement.strip()
        # Ignore descriptive requirements (e.g. "sqlite3 (built-in)")
        if "(" in requirement and ")" in requirement and " " in requirement:
            return requirement.split(" ", 1)[0]

        separators = [" ", "<", ">", "=", "!", "~"]
        package = requirement
        for sep in separators:
            if sep in package:
                package = package.split(sep, 1)[0]
        package = package.strip()
        return package or None

    @classmethod
    def get_platform_availability(cls) -> dict[str, bool]:
        """Get availability status for all registered platforms.

        Returns:
            Dictionary mapping platform names to availability status
        """
        cls._ensure_registered()
        if cls._availability_cache is not None:
            return cls._availability_cache.copy()

        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        availability = {}
        for platform_name in cls._adapters:
            if platform_name in cls._platform_metadata:
                # Use detailed library detection
                platform_spec = cls._platform_metadata[platform_name]
                available = True

                for lib_spec in platform_spec.get("libraries", []):
                    lib_info = cls._detect_library(lib_spec)
                    if (
                        lib_spec.get("required", True)
                        and not lib_info.installed
                        and not lib_spec.get("alternative", False)
                    ):
                        available = False
                        break

                availability[platform_name] = available
            else:
                # Fallback to old method
                try:
                    adapter_class = cls._adapters[platform_name]
                    test_config = {"database_path": ":memory:"} if platform_name == "duckdb" else {}
                    adapter_class(**test_config)
                    availability[platform_name] = True
                except (ImportError, OSError):
                    availability[platform_name] = False
                except Exception:
                    availability[platform_name] = True

        cls._availability_cache = availability
        return availability.copy()

    @classmethod
    def is_platform_available(cls, platform_name: str) -> bool:
        """Check if a specific platform is available.

        Args:
            platform_name: Name of the platform to check

        Returns:
            True if platform is available
        """
        availability = cls.get_platform_availability()
        return availability.get(platform_name, False)

    @classmethod
    def get_platform_info(cls, platform_name: str) -> Optional[PlatformInfo]:
        """Get comprehensive platform information.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Platform information or None if not found
        """
        cls._ensure_registered()
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        # Resolve aliases to canonical name
        canonical_name = cls.resolve_platform_name(platform_name)

        if canonical_name not in cls._platform_metadata:
            return None

        platform_spec = cls._platform_metadata[canonical_name]

        # Detect libraries
        libraries = []
        available = True

        for lib_spec in platform_spec.get("libraries", []):
            lib_info = cls._detect_library(lib_spec)
            libraries.append(lib_info)

            if lib_spec.get("required", True) and not lib_info.installed and not lib_spec.get("alternative", False):
                available = False

        # Check if driver_package is explicitly set in metadata
        if "driver_package" in platform_spec:
            driver_package = platform_spec["driver_package"]
        else:
            # Fallback: extract from requirements if not explicitly specified
            requirements = platform_spec.get("requirements", [])
            driver_package = cls._extract_requirement_package(requirements[0]) if requirements else None

        return PlatformInfo(
            name=canonical_name,
            display_name=platform_spec["display_name"],
            description=platform_spec["description"],
            libraries=libraries,
            available=available,
            enabled=available and canonical_name in cls._adapters,
            requirements=platform_spec["requirements"],
            installation_command=platform_spec["installation_command"],
            adoption=platform_spec.get("adoption", "niche"),
            category=platform_spec.get("category", "database"),
            supports=platform_spec.get("supports", []),
            driver_package=driver_package,
        )

    @classmethod
    def get_platform_requirements(cls, platform_name: str) -> str:
        """Get installation requirements for a platform.

        Args:
            platform_name: Name of the platform

        Returns:
            Installation requirements string
        """
        info = cls.get_platform_info(platform_name)
        if info:
            return info.installation_command

        # Fallback to old static mapping
        requirements_map = {
            "duckdb": "uv add duckdb",
            "databricks": "uv add databricks-sql-connector",
            "clickhouse": "uv add benchbox --extra clickhouse",
            "clickhouse-local": "uv add benchbox --extra clickhouse-local",
            "clickhouse-server": "uv add benchbox --extra clickhouse-server",
            "clickhouse-cloud": "uv add benchbox --extra clickhouse-cloud",
            "sqlite": "Built-in (no additional requirements)",
            "bigquery": "uv add google-cloud-bigquery",
            "redshift": "uv add redshift-connector",
            "snowflake": "uv add snowflake-connector-python",
        }
        return requirements_map.get(platform_name, "Unknown requirements")

    @classmethod
    def get_platforms_by_category(cls, category: str) -> list[str]:
        """Get platforms filtered by category.

        Args:
            category: Platform category ('analytical', 'cloud', 'embedded', etc.)

        Returns:
            List of platform names in the category
        """
        cls._ensure_registered()
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        return [
            name
            for name, spec in cls._platform_metadata.items()
            if spec.get("category") == category and name in cls._adapters
        ]

    @classmethod
    def get_platforms_by_adoption(cls, tier: str) -> list[str]:
        """Get platforms by adoption tier.

        Args:
            tier: Adoption tier ('mainstream', 'established', 'emerging', 'niche')

        Returns:
            List of platform names in the specified tier
        """
        cls._ensure_registered()
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        return [
            name
            for name, spec in cls._platform_metadata.items()
            if spec.get("adoption", "niche") == tier and name in cls._adapters
        ]

    @classmethod
    def requires_cloud_storage(cls, platform_name: str) -> bool:
        """Check if a platform requires cloud storage for data loading.

        Cloud platforms (Databricks, BigQuery, Snowflake, Redshift) require
        a cloud storage staging location for loading benchmark data.

        Args:
            platform_name: Name of the platform

        Returns:
            True if platform requires cloud storage staging location
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        metadata = cls._platform_metadata.get(platform_name.lower(), {})
        # Cloud platforms require staging locations for data loading
        return metadata.get("category") == "cloud"

    @classmethod
    def get_cloud_path_examples(cls, platform_name: str) -> list[str]:
        """Get example cloud paths for a platform.

        Args:
            platform_name: Name of the platform

        Returns:
            List of example cloud path formats for the platform
        """
        examples = {
            "databricks": [
                "dbfs:/Volumes/catalog/schema/volume/benchbox",
                "s3://my-bucket/benchbox/data",
                "abfss://container@storage.dfs.core.windows.net/benchbox",
                "gs://my-bucket/benchbox/data",
            ],
            "bigquery": [
                "gs://my-bucket/benchbox/data",
            ],
            "snowflake": [
                # User stage first: it is what the credential prompt defaults to
                # and needs no cloud-storage setup.
                SNOWFLAKE_DEFAULT_OUTPUT_LOCATION,
                "s3://my-bucket/benchbox/data",
                "azure://my-container/benchbox/data",
                "gcs://my-bucket/benchbox/data",
            ],
            "redshift": [
                "s3://my-bucket/benchbox/data",
            ],
            "trino": [
                "s3://my-bucket/benchbox/data",
                "gs://my-bucket/benchbox/data",
                "abfss://container@storage.dfs.core.windows.net/benchbox",
            ],
        }
        return examples.get(platform_name.lower(), [])

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the availability cache."""
        cls._availability_cache = None

    @classmethod
    def get_all_platform_metadata(cls) -> dict[str, dict[str, Any]]:
        """Get all platform metadata for CLI use.

        Returns:
            Dictionary mapping platform names to their metadata
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()
        return cls._platform_metadata.copy()

    @classmethod
    def get_platform_support_status(cls, platform_name: str) -> Optional[SupportStatus]:
        """Return the registry support status for a platform."""
        metadata = cls.get_all_platform_metadata()
        canonical_name = cls.resolve_platform_name(platform_name)
        platform_spec = metadata.get(canonical_name)
        if platform_spec is None:
            return None
        return platform_spec["support_status"]

    @classmethod
    def get_platforms_by_support_status(cls, status: SupportStatus) -> list[str]:
        """Get platforms filtered by product support status."""
        if status not in SUPPORT_STATUS_VALUES:
            raise ValueError(f"Unknown support_status {status!r}. Expected one of: {', '.join(SUPPORT_STATUS_VALUES)}")

        metadata = cls.get_all_platform_metadata()
        return sorted(name for name, spec in metadata.items() if spec["support_status"] == status)

    @classmethod
    def get_platform_count_summary(cls) -> dict[str, Any]:
        """Return registry-derived platform counts for docs drift checks."""
        metadata = cls.get_all_platform_metadata()
        status_counts = Counter(spec["support_status"] for spec in metadata.values())
        category_counts = Counter(spec.get("category", "unknown") for spec in metadata.values())
        sql_capable = sum(1 for spec in metadata.values() if spec.get("capabilities", {}).get("supports_sql", False))
        dataframe_capable = sum(
            1 for spec in metadata.values() if spec.get("capabilities", {}).get("supports_dataframe", False)
        )
        dual_mode = sum(
            1
            for spec in metadata.values()
            if spec.get("capabilities", {}).get("supports_sql", False)
            and spec.get("capabilities", {}).get("supports_dataframe", False)
        )
        dataframe_only = sum(
            1
            for spec in metadata.values()
            if not spec.get("capabilities", {}).get("supports_sql", False)
            and spec.get("capabilities", {}).get("supports_dataframe", False)
        )

        return {
            "total": len(metadata),
            "sql_capable": sql_capable,
            "dataframe_capable": dataframe_capable,
            "dual_mode": dual_mode,
            "dataframe_only": dataframe_only,
            "support_status": {status: status_counts.get(status, 0) for status in SUPPORT_STATUS_VALUES},
            "category": dict(sorted(category_counts.items())),
        }

    @classmethod
    def classify_optional_import_error(
        cls,
        exc: BaseException,
        *,
        module_path: str | None = None,
    ) -> OptionalAdapterImportStatus:
        """Classify an optional adapter import failure without raising it."""
        message = str(exc).lower()
        if isinstance(exc, ModuleNotFoundError):
            missing_name = exc.name or ""
            if _is_internal_module_miss(missing_name, module_path):
                return "broken_adapter_import"
            return "missing_optional_dependency"
        if "no module named" in message:
            return "missing_optional_dependency"
        if isinstance(exc, OSError) or any(marker in message for marker in _NATIVE_IMPORT_ERROR_MARKERS):
            return "native_library_load_failure"
        return "broken_adapter_import"

    @classmethod
    def diagnose_optional_adapter_imports(
        cls,
        platform_names: Optional[Iterable[str]] = None,
    ) -> dict[str, dict[str, Any]]:
        """Diagnose optional adapter import health on demand.

        Normal registry discovery remains fail-open for missing optional
        dependencies. This explicit diagnostic path imports selected adapters
        and reports whether a failure is dependency, native-library, broken
        adapter, deprecated, or intentionally disabled status.
        """
        requested = None
        if platform_names is not None:
            requested = {cls.resolve_platform_name(platform_name) for platform_name in platform_names}

        diagnostics: dict[str, dict[str, Any]] = {}
        for name, module_path, class_name in _OPTIONAL_ADAPTERS:
            if requested is not None and name not in requested:
                continue
            diagnostics[name] = _diagnose_optional_adapter_entry(name, module_path, class_name).to_dict()

        if requested is not None:
            missing = requested - set(diagnostics)
            for name in sorted(missing):
                diagnostics[name] = OptionalAdapterDiagnostic(
                    platform_name=name,
                    module_path="",
                    class_name="",
                    status="not_configured",
                    support_status=cls.get_platform_support_status(name),
                    error_message="Platform is not configured for optional adapter registration.",
                ).to_dict()

        return diagnostics

    @classmethod
    def detect_library(cls, lib_spec: dict[str, Any]) -> LibraryInfo:
        """Detect a single library for CLI use.

        Args:
            lib_spec: Library specification dictionary

        Returns:
            LibraryInfo object with detection results
        """
        return cls._detect_library(lib_spec)

    @classmethod
    def get_platform_capabilities(cls, platform_name: str) -> Optional[PlatformCapability]:
        """Get capability information for a platform.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            PlatformCapability object or None if platform not found
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        # Resolve aliases to canonical name
        canonical_name = cls.resolve_platform_name(platform_name)
        metadata = cls._platform_metadata.get(canonical_name)
        if metadata is None:
            return None

        caps = metadata.get("capabilities", {})

        # Parse deployment modes from metadata
        deployment_modes: dict[str, DeploymentCapability] = {}
        deployment_data = caps.get("deployment_modes", {})
        for mode_name, mode_spec in deployment_data.items():
            deployment_modes[mode_name] = DeploymentCapability(
                mode=mode_spec.get("mode", "local"),
                requires_credentials=mode_spec.get("requires_credentials", False),
                requires_cloud_storage=mode_spec.get("requires_cloud_storage", False),
                requires_network=mode_spec.get("requires_network", False),
                default_for_platform=mode_spec.get("default_for_platform", False),
                display_name=mode_spec.get("display_name", ""),
                description=mode_spec.get("description", ""),
                dependencies=mode_spec.get("dependencies", []),
                auth_methods=mode_spec.get("auth_methods", []),
            )

        # unsupported_benchmarks is computed from registry benchmark_gate rules;
        # the hardcoded dict in metadata is the legacy source and is ignored post-w16.
        import benchbox.sql_compat.rules.benchmark_gate.lakesail_gate  # noqa: F401
        import benchbox.sql_compat.rules.benchmark_gate.pg_family_gate  # noqa: F401
        import benchbox.sql_compat.rules.benchmark_gate.questdb_gate  # noqa: F401
        from benchbox.sql_compat.actions import CompatAction
        from benchbox.sql_compat.context import Phase
        from benchbox.sql_compat.registry import REGISTRY

        unsupported: dict[str, str] = {}
        for (phase, platform, benchmark, _query_id), entry in REGISTRY.all_rules():
            if (
                phase is Phase.BENCHMARK_GATE
                and platform == canonical_name
                and benchmark is not None
                and entry.decision.action is CompatAction.BLOCK_BENCHMARK
            ):
                reason = getattr(entry.decision.payload, "reason", None) or entry.decision.reason or ""
                unsupported[benchmark] = reason

        return PlatformCapability(
            supports_sql=caps.get("supports_sql", False),
            supports_dataframe=caps.get("supports_dataframe", False),
            default_mode=caps.get("default_mode", "sql"),
            deployment_modes=deployment_modes,
            default_deployment=caps.get("default_deployment", "local"),
            platform_family=caps.get("platform_family"),
            inherits_from=caps.get("inherits_from"),
            cost_class=caps.get("cost_class", "free"),
            unsupported_benchmarks=unsupported,
        )

    @classmethod
    def get_platform_conflicts(cls, platform_name: str) -> list[str]:
        """Get list of platforms that conflict with the given platform.

        Some PostgreSQL extensions share libraries (e.g., pg_duckdb and
        pg_mooncake share libduckdb.so) and cannot coexist in the same
        PostgreSQL instance.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            List of conflicting platform names, or empty list if none.
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        canonical_name = cls.resolve_platform_name(platform_name)
        metadata = cls._platform_metadata.get(canonical_name)
        if metadata is None:
            return []

        caps = metadata.get("capabilities", {})
        return list(caps.get("conflicts_with", []))

    @classmethod
    def supports_mode(cls, platform_name: str, mode: str) -> bool:
        """Check if platform supports a specific execution mode.

        Args:
            platform_name: Name of the platform
            mode: Execution mode ('sql' or 'dataframe')

        Returns:
            True if platform supports the mode
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None:
            return False

        if mode == "sql":
            return caps.supports_sql
        elif mode == "dataframe":
            return caps.supports_dataframe
        return False

    @classmethod
    def get_default_mode(cls, platform_name: str) -> str:
        """Get default execution mode for a platform.

        Args:
            platform_name: Name of the platform

        Returns:
            Default mode ('sql' or 'dataframe'), defaults to 'sql' if unknown
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None:
            return "sql"
        return caps.default_mode

    @classmethod
    def get_dual_mode_platforms(cls) -> list[str]:
        """Get platforms that support both SQL and DataFrame modes.

        Returns:
            List of platform names with dual-mode support
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        dual_mode = []
        for name, metadata in cls._platform_metadata.items():
            caps = metadata.get("capabilities", {})
            if caps.get("supports_sql") and caps.get("supports_dataframe"):
                dual_mode.append(name)
        return dual_mode

    @classmethod
    def get_sql_platforms(cls, *, include_deprecated: bool = False) -> list[str]:
        """Return registry platforms that support SQL execution."""
        return cls._get_platforms_matching_capability("supports_sql", include_deprecated=include_deprecated)

    @classmethod
    def get_dataframe_platforms(cls, *, include_deprecated: bool = False) -> list[str]:
        """Return registry platforms that support DataFrame execution."""
        return cls._get_platforms_matching_capability("supports_dataframe", include_deprecated=include_deprecated)

    @classmethod
    def get_self_hosted_platforms(cls, *, include_deprecated: bool = False) -> list[str]:
        """Return platforms with at least one self-hosted deployment mode."""
        metadata = cls.get_all_platform_metadata()
        out: list[str] = []
        for name, spec in metadata.items():
            if not include_deprecated and spec.get("support_status") in {"deprecated", "document_only"}:
                continue
            deployment_modes = spec.get("capabilities", {}).get("deployment_modes", {})
            if any(mode.get("mode") == "self-hosted" for mode in deployment_modes.values()):
                out.append(name)
        return out

    @classmethod
    def _get_platforms_matching_capability(
        cls,
        capability: str,
        *,
        include_deprecated: bool = False,
    ) -> list[str]:
        metadata = cls.get_all_platform_metadata()
        out: list[str] = []
        for name, spec in metadata.items():
            if not include_deprecated and spec.get("support_status") in {"deprecated", "document_only"}:
                continue
            if spec.get("capabilities", {}).get(capability, False):
                out.append(name)
        return out

    @classmethod
    def get_deployment_capability(cls, platform_name: str, deployment_mode: str) -> Optional[DeploymentCapability]:
        """Get deployment capability information for a specific deployment mode.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)
            deployment_mode: Deployment mode name (e.g., 'local', 'server', 'cloud')

        Returns:
            DeploymentCapability object or None if deployment mode not found
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None or not caps.deployment_modes:
            return None
        return caps.deployment_modes.get(deployment_mode)

    @classmethod
    def get_default_deployment(cls, platform_name: str) -> Optional[str]:
        """Get default deployment mode for a platform.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Default deployment mode name, or None if platform has no deployment modes
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None or not caps.deployment_modes:
            return None
        return caps.default_deployment

    @classmethod
    def get_platform_family(cls, platform_name: str) -> Optional[str]:
        """Get platform family for dialect/configuration inheritance.

        Platform families group related platforms that share SQL dialect,
        benchmark compatibility, and data type mappings. For example:
        - 'duckdb' family: duckdb, motherduck, ducklake
        - 'clickhouse' family: clickhouse (local, server, cloud modes)
        - 'trino' family: trino, starburst, athena

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Platform family name or None if no family defined
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None:
            return None
        return caps.platform_family

    @classmethod
    def get_inherited_platform(cls, platform_name: str) -> Optional[str]:
        """Get parent platform for configuration inheritance.

        Child platforms inherit SQL dialect, benchmark compatibility, and
        data type mappings from their parent. For example:
        - motherduck, ducklake inherit from duckdb
        - starburst inherits from trino

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Parent platform name or None if no inheritance defined
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None:
            return None
        return caps.inherits_from

    @classmethod
    def requires_cloud_storage_for_deployment(cls, platform_name: str, deployment_mode: Optional[str] = None) -> bool:
        """Check if a specific deployment mode requires cloud storage.

        Args:
            platform_name: Name of the platform
            deployment_mode: Specific deployment mode to check, or None for default

        Returns:
            True if deployment mode requires cloud storage staging location
        """
        if deployment_mode is None:
            deployment_mode = cls.get_default_deployment(platform_name)

        # If no deployment mode available, fallback to platform-level check
        if deployment_mode is None:
            return cls.requires_cloud_storage(platform_name)

        dep_cap = cls.get_deployment_capability(platform_name, deployment_mode)
        if dep_cap is not None:
            return dep_cap.requires_cloud_storage

        # Fallback to existing requires_cloud_storage method
        return cls.requires_cloud_storage(platform_name)

    @classmethod
    def get_available_deployment_modes(cls, platform_name: str) -> list[str]:
        """Get list of available deployment modes for a platform.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            List of deployment mode names, empty if none defined
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None or not caps.deployment_modes:
            return []
        return list(caps.deployment_modes.keys())

    @classmethod
    def supports_deployment_mode(cls, platform_name: str, deployment_mode: str) -> bool:
        """Check if platform supports a specific deployment mode.

        Args:
            platform_name: Name of the platform
            deployment_mode: Deployment mode to check

        Returns:
            True if platform supports the deployment mode
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None or not caps.deployment_modes:
            # Platform has no deployment modes defined - only supports default
            return deployment_mode == "local"
        return deployment_mode in caps.deployment_modes


# (name, module_path, class_name) - each entry becomes one optional import+register.
# pg-mooncake historically co-registered questdb in the same try/except; that
# coupling is now explicit (two separate entries).
_OPTIONAL_ADAPTERS: tuple[tuple[str, str, str], ...] = get_adapter_imports()

_OPTIONAL_ADAPTER_REGISTRATION_DIAGNOSTICS: dict[str, dict[str, Any]] = {}


def _diagnose_optional_adapter_entry(
    name: str,
    module_path: str,
    class_name: str,
) -> OptionalAdapterDiagnostic:
    """Import one optional adapter and return a structured diagnostic."""
    support_status = PlatformRegistry.get_platform_support_status(name)
    if support_status == "deprecated":
        return OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="deprecated_platform",
            support_status=support_status,
            error_message="Platform selector is deprecated; use the documented replacement.",
        )
    if support_status in {"repo_only", "document_only"}:
        return OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="intentionally_disabled",
            support_status=support_status,
            error_message=f"Platform support_status is {support_status}; it is not a default runtime adapter.",
        )

    try:
        module = importlib.import_module(module_path)
        adapter_cls = getattr(module, class_name)
    except AttributeError as exc:
        return OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="broken_adapter_import",
            support_status=support_status,
            error_type=type(exc).__name__,
            error_message=f"{module_path} does not expose {class_name}",
        )
    except (ImportError, OSError) as exc:
        return OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status=PlatformRegistry.classify_optional_import_error(exc, module_path=module_path),
            support_status=support_status,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    return OptionalAdapterDiagnostic(
        platform_name=name,
        module_path=module_path,
        class_name=class_name,
        status="available",
        support_status=support_status,
        available=adapter_cls is not None,
    )


def _try_register_adapter(name: str, module_path: str, class_name: str) -> None:
    """Import ``class_name`` from ``module_path`` and register as ``name``.

    Missing optional dependencies are silently skipped - adapters whose driver
    packages aren't installed simply don't appear in the registry.
    """
    support_status = PlatformRegistry.get_platform_support_status(name)
    try:
        module = importlib.import_module(module_path)
        adapter_cls = getattr(module, class_name)
        PlatformRegistry.register_adapter(name, adapter_cls)
        _OPTIONAL_ADAPTER_REGISTRATION_DIAGNOSTICS[name] = OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="available",
            support_status=support_status,
            available=True,
        ).to_dict()
    except AttributeError as exc:
        _OPTIONAL_ADAPTER_REGISTRATION_DIAGNOSTICS[name] = OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="broken_adapter_import",
            support_status=support_status,
            error_type=type(exc).__name__,
            error_message=f"{module_path} does not expose {class_name}",
        ).to_dict()
    except (ImportError, OSError) as exc:
        _OPTIONAL_ADAPTER_REGISTRATION_DIAGNOSTICS[name] = OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status=PlatformRegistry.classify_optional_import_error(exc, module_path=module_path),
            support_status=support_status,
            error_type=type(exc).__name__,
            error_message=str(exc),
        ).to_dict()


def auto_register_platforms() -> None:
    """Automatically register all available platform adapters.

    Platforms are registered if their dependencies can be successfully imported.
    The BENCHBOX_ENABLE_EXPERIMENTAL environment variable is reserved for future
    truly-experimental features but is not currently used.
    """
    for name, module_path, class_name in _OPTIONAL_ADAPTERS:
        _try_register_adapter(name, module_path, class_name)


# NOTE: auto_register_platforms() is no longer called at module level.
# It is deferred to first access via PlatformRegistry._ensure_registered()
# to avoid eagerly loading ~600 MB of native libraries (chdb, polars,
# datafusion, duckdb, databend_driver) into every xdist worker process.
# See: https://github.com/benchbox/benchbox/issues/XXXX
