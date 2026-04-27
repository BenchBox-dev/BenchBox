# ADR-0001: Unified Platform Registration Architecture

## Status

Accepted

## Date

2025-12-08

## Context

BenchBox had two parallel systems for platform registration that could drift apart:

1. **`get_platform_adapter()`** in `benchbox/platforms/__init__.py`
   - Hardcoded dictionary mapping platform names to adapter classes
   - Included alias handling (e.g., `sqlite3` -> `SQLiteAdapter`)
   - Used by CLI for benchmark execution (`benchbox run`)

2. **`PlatformRegistry`** in `benchbox/core/platform_registry.py`
   - Dynamic registration via `auto_register_platforms()`
   - Rich metadata (descriptions, categories, capabilities, requirements)
   - Used by CLI for platform discovery (`benchbox platforms list`)

This led to bugs where:
- New platforms were added to one system but not the other
- Alias handling was only in `get_platform_adapter()`
- Installation requirements were duplicated and could diverge
- Platform availability detection was implemented twice

## Decision

Make `PlatformRegistry` the single source of truth for all platform-related information:

1. **Adapter Registration**: All platforms are registered only in `auto_register_platforms()`
2. **Alias Resolution**: Move alias handling to `PlatformRegistry.resolve_platform_name()`
3. **Adapter Lookup**: `get_platform_adapter()` delegates to `PlatformRegistry.get_adapter_class()`
4. **Metadata**: All platform metadata (requirements, capabilities) lives in `PlatformRegistry`

The `get_platform_adapter()` function remains as a thin wrapper that:
- Handles CLI-specific concerns (driver version resolution, error messages)
- Delegates all platform lookup to PlatformRegistry

## Consequences

### Positive

- **Single registration point**: New platforms only need to be added to `auto_register_platforms()`
- **Consistent aliases**: Alias resolution works everywhere via `resolve_platform_name()`
- **No drift**: Alignment tests prevent future divergence
- **Reduced code**: ~100 lines of duplicated code removed
- **Cleaner architecture**: Clear separation between registry (source of truth) and factory (CLI concerns)

### Negative

- **Additional indirection**: `get_platform_adapter()` now calls PlatformRegistry methods
- **Migration required**: Any external code directly using the old implementations needs updating

### Neutral

- **Public API preserved**: `get_platform_adapter()`, `list_available_platforms()`, and `get_platform_requirements()` remain available with same signatures

## Implementation

1. Added `resolve_platform_name()` and `get_all_aliases()` to PlatformRegistry
2. Updated `get_adapter_class()`, `get_platform_info()`, `get_platform_capabilities()` to use alias resolution
3. Refactored `get_platform_adapter()` to delegate adapter lookup to PlatformRegistry
4. Replaced `list_available_platforms()` and `get_platform_requirements()` with thin wrappers
5. Added comprehensive alignment tests in `test_platform_registration_alignment.py`

## How to Add a New Platform

After this change, adding a new platform requires:

1. Create the adapter class in `benchbox/platforms/`
2. Add metadata to `_build_platform_metadata()` in `platform_registry.py`
3. Add registration to `auto_register_platforms()` in `platform_registry.py`

The alignment tests will fail if any of these steps are missed.

## References

- `benchbox/core/platform_registry.py` - PlatformRegistry class
- `benchbox/platforms/__init__.py` - get_platform_adapter() and other wrappers
- `tests/unit/core/test_platform_registration_alignment.py` - Alignment tests
