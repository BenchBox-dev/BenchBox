"""Every `--platform-option KEY` an adapter advertises must be a key it accepts.

`benchbox/platforms/bigquery.py` told users to run
`--platform-option project_id=<your-project>`, and the CLI answered
`Unknown platform option 'project_id' for platform 'bigquery'`. An error
message that prescribes a command the tool rejects sends a user in a circle at
exactly the moment they are already stuck.

The prior guard only checked that an advertised command *parsed*, which passed
while the bigquery case was broken. This one checks the KEY against the
adapter's registered option specs -- the same allowlist
`PlatformHookRegistry.parse_options` enforces.

Note the adapters do consume these keys (`config.get("project_id")` and so on);
they arrive through environment variables or a credentials file. What is
missing is the `--platform-option` spec declaration, so the advertised route
specifically does not work.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

import benchbox.cli.platform_defaults  # noqa: F401  -- registers the option specs at import
from benchbox.core.hooks.platform_hooks import PlatformHookRegistry
from benchbox.platforms.manifest import PLATFORM_MANIFEST

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
PLATFORMS_DIR = REPO_ROOT / "benchbox" / "platforms"

ADVERTISED = re.compile(r"--platform-option\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")

#: Generic prose placeholders, not real key names.
PLACEHOLDERS = frozenset({"key", "K", "name", "value", "option"})

#: Known advertised-but-rejected pairs, as of 2026-08-23. This list must only
#: ever SHRINK. Each entry is a message that sends a user to a command the CLI
#: refuses.
#:
#: Resolving them needs a maintainer decision, split by sensitivity:
#:
#:   SECRET-BEARING -- must never become CLI-passable (shell history, process
#:   listings). Fix by correcting the message to `benchbox setup` plus
#:   environment variables:
#:       pg-duckdb.motherduck_token, redshift.iam_role
#:
#:   NON-SECRET CONFIG -- safe to declare as real option specs, which would
#:   make the advertised advice true:
#:       everything else below.
KNOWN_MISMATCHES: frozenset[tuple[str, str]] = frozenset(
    {
        ("athena", "aws_profile"),
        ("athena", "s3_bucket"),
        ("athena", "s3_staging_dir"),
        ("athena", "staging_root"),
        ("bigquery", "biglake_connection"),
        ("bigquery", "project_id"),
        ("motherduck", "database"),
        ("pg-duckdb", "duckdb_db_path"),
        ("pg-duckdb", "motherduck_token"),
        ("redshift", "iam_role"),
        ("redshift", "s3_bucket"),
        ("redshift", "staging_root"),
        ("snowflake", "iceberg_external_volume"),
        ("snowflake", "staging_root"),
        ("spark", "java_home"),
        ("synapse", "staging_root"),
        ("velox", "jar"),
    }
)


def _module_to_platform_key() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in PLATFORM_MANIFEST:
        if entry.adapter is None:
            continue
        mapping.setdefault(entry.adapter.module, entry.key)
        try:
            importlib.import_module(entry.adapter.module)
        except Exception:  # pragma: no cover - optional driver not installed
            pass
    return mapping


def _advertised_pairs() -> set[tuple[str, str]]:
    module_to_key = _module_to_platform_key()
    pairs: set[tuple[str, str]] = set()
    for path in sorted(PLATFORMS_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        keys = {m.group(1) for m in ADVERTISED.finditer(text)} - PLACEHOLDERS
        if not keys:
            continue
        module = ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
        platform = module_to_key.get(module)
        if platform is None:
            # Shared base/helper module with no single owning platform.
            continue
        allowed = set(PlatformHookRegistry.list_option_specs(platform))
        pairs |= {(platform, key) for key in keys if key not in allowed}
    return pairs


def test_no_new_adapter_advertises_a_rejected_option() -> None:
    new = _advertised_pairs() - KNOWN_MISMATCHES
    assert not new, (
        "adapter error text or docstring advertises --platform-option keys the CLI rejects:\n  "
        + "\n  ".join(f"{platform}: {key}" for platform, key in sorted(new))
    )


def test_known_mismatch_list_does_not_grow_stale() -> None:
    """Entries must be removed from KNOWN_MISMATCHES once fixed."""
    fixed = KNOWN_MISMATCHES - _advertised_pairs()
    assert not fixed, "these were fixed - delete them from KNOWN_MISMATCHES:\n  " + "\n  ".join(
        f"{platform}: {key}" for platform, key in sorted(fixed)
    )


def test_the_guard_catches_the_bigquery_case_that_motivated_it() -> None:
    """Negative control: the original defect is in the detected set."""
    assert ("bigquery", "project_id") in _advertised_pairs()


def test_an_accepted_key_is_not_flagged() -> None:
    """Positive control: a real spec key must never appear as a mismatch."""
    allowed = set(PlatformHookRegistry.list_option_specs("postgresql"))
    assert "host" in allowed, "fixture assumption changed"
    assert ("postgresql", "host") not in _advertised_pairs()
