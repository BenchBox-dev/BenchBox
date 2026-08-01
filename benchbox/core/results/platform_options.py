"""Sanitized platform-option capture for result metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED_VALUE = "<redacted>"

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _normalize_secret_key(key: str) -> str:
    """Lowercase ``key`` and strip non-alphanumerics so ``sessionToken``,
    ``session-token`` and ``session_token`` all collapse to ``sessiontoken``."""
    return _NON_ALNUM_RE.sub("", key.lower())


_SECRET_KEY_PARTS = tuple(
    _normalize_secret_key(part)
    for part in (
        "password",
        "token",
        "secret",
        "access_key",
        # Normalizes to "keyid", which "access_key" does not cover: an
        # ``accessKeyId`` matched only because it also contains "accesskey", so
        # the shorter provider-prefixed spellings (``s3_key_id``, ``kms_key_id``)
        # were exported verbatim. Matches only key-id-shaped names - ordinary
        # data-modelling keys (sort_key, partition_key, primary_key) do not
        # contain "keyid" and keep exporting their real values.
        "key_id",
        "private_key",
        "session_token",
        "connection_string",
        "credential",
        # DSNs can embed URI userinfo (for example, user:password@host), and
        # Azure Hadoop ``fs.azure.sas.*`` configuration values are bearer
        # credentials. Redact the whole option rather than trying to preserve
        # a partially parsed value across provider-specific formats.
        "dsn",
        "sas",
        # Found by the 2026-07-31 sentinel sweep leaking through BOTH layers:
        # api_key/onehouse_api_key (quanton's only credential) and Azure's
        # storage_account_key matched none of the parts above. Deliberately
        # narrow - a bare "key" part would redact sort_key/partition_key-class
        # data-modelling options.
        "api_key",
        "account_key",
    )
)
# Connection usernames are identity, not secrets, so they are NOT in
# _SECRET_KEY_PARTS (the public anonymization path shares that list and must
# keep PSEUDONYMIZING usernames for grouping, not redacting them). But the
# internal capture path has no pseudonymizer, so before this set existed a
# username rode into every internal bundle verbatim. Exact normalized match
# only - a substring rule on "user" would nuke user_agent/num_users-class
# options.
_USERNAME_KEYS = frozenset({"user", "username", "userid", "pguser", "dbuser"})


def _is_username_key(key: str) -> bool:
    return _normalize_secret_key(key) in _USERNAME_KEYS


_INTERNAL_OPTION_KEYS = {
    "_explicit_platform_options",
    "verbosity_settings",
    "verbose",
    "verbose_level",
    "verbose_enabled",
    "very_verbose",
    "quiet",
    "tuning_enabled",
    "unified_tuning_configuration",
    "df_tuning_config",
    "capture_plans",
    "analyze_plans",
    "strict_plan_capture",
    "plan_queries",
    "execution_mode",
    "benchmark",
    "scale_factor",
    "tuning_config",
    "driver_package",
    "driver_version_resolved",
    "driver_version_actual",
    "driver_runtime_strategy",
    "driver_runtime_path",
    "driver_runtime_python_executable",
    "driver_auto_install",
    "driver_auto_install_used",
}


def is_secret_option_key(key: str) -> bool:
    normalized = _normalize_secret_key(key)
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def sanitize_platform_options(
    options: Mapping[str, Any] | None,
    *,
    exclude_internal: bool = False,
) -> dict[str, Any]:
    """Return a JSON-friendly platform-options dict with secret-like values redacted.

    ``exclude_internal`` drops keys in ``_INTERNAL_OPTION_KEYS`` and
    underscore-prefixed keys, mirroring ``_iter_public_options`` semantics.
    Set it for any payload that is exported/persisted (bundle metadata,
    result payloads) so internal bookkeeping options (e.g. the full
    ``tuning_config`` object) never leak into published data.
    """
    if not options:
        return {}

    sanitized: dict[str, Any] = {}
    for key, value in options.items():
        key_str = str(key)
        if exclude_internal and (key_str.startswith("_") or key_str in _INTERNAL_OPTION_KEYS):
            continue
        if is_secret_option_key(key_str) or _is_username_key(key_str):
            sanitized[key_str] = REDACTED_VALUE
        else:
            sanitized[key_str] = _sanitize_option_value(value, exclude_internal=exclude_internal)
    return sanitized


def build_platform_options_capture(
    *,
    requested_options: Mapping[str, Any] | None = None,
    requested_sources: Mapping[str, str] | None = None,
    database_options: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Merge platform options for run metadata and return sanitized values plus sources.

    ``requested_options`` are options explicitly carried by the CLI/orchestrator
    and may include registered defaults. ``database_options`` are the resolved
    options from ``DatabaseConfig`` after credentials/config builders have run.
    CLI-provided options override resolved config values; registered defaults do
    not override saved/config-derived values, including their provenance.
    """
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    source_map = {str(key): str(value) for key, value in (requested_sources or {}).items()}

    for key, value in _iter_public_options(database_options):
        values[key] = value
        sources[key] = "saved_config"

    for key, value in _iter_public_options(requested_options):
        requested_source = source_map.get(key, "requested")
        if requested_source == "registered_default" and key in values:
            # Saved config already populated this key; preserve its provenance
            # rather than rewriting the source to "registered_default" just
            # because the values happen to match.
            continue
        values[key] = value
        sources[key] = requested_source

    sanitized_values = sanitize_platform_options(values, exclude_internal=True)
    return sanitized_values, {key: sources[key] for key in sanitized_values if key in sources}


def _iter_public_options(options: Mapping[str, Any] | None):
    if not options:
        return
    for key, value in options.items():
        key_str = str(key)
        if key_str.startswith("_") or key_str in _INTERNAL_OPTION_KEYS or value is None:
            continue
        yield key_str, value


def _sanitize_option_value(value: Any, *, exclude_internal: bool = False) -> Any:
    if isinstance(value, Mapping):
        return sanitize_platform_options(value, exclude_internal=exclude_internal)
    if isinstance(value, list):
        return [_sanitize_option_value(item, exclude_internal=exclude_internal) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_option_value(item, exclude_internal=exclude_internal) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        to_dict = getattr(value, "to_dict", None)
    except Exception:
        return f"<unserializable:{type(value).__name__}>"
    if callable(to_dict):
        try:
            as_dict = to_dict()
        except Exception:
            return f"<unserializable:{type(value).__name__}>"
        if isinstance(as_dict, Mapping):
            return sanitize_platform_options(as_dict, exclude_internal=exclude_internal)
        return _sanitize_option_value(as_dict, exclude_internal=exclude_internal)
    # No canonical serialization available. Never fall back to str()/repr()
    # here: that would silently publish opaque Python repr text into
    # exported bundles/payloads. Leave an explicit marker instead so gaps
    # in capture stay visible rather than masquerading as real data.
    return f"<unserializable:{type(value).__name__}>"


__all__ = [
    "REDACTED_VALUE",
    "build_platform_options_capture",
    "is_secret_option_key",
    "sanitize_platform_options",
]
