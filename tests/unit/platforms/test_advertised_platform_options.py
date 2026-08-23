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

#: Advertised-but-rejected pairs that are knowingly left unfixed. EMPTY, and
#: it must only ever be re-populated with a recorded reason. Every pair the
#: original audit found has been resolved, each according to what it is:
#:
#:   Non-secret configuration -- thirteen keys the adapters already read from
#:   config but had never declared as option specs, so the advertised route
#:   genuinely did not work. They are declared now, which makes the advice
#:   true: athena aws_profile / s3_bucket / s3_staging_dir / staging_root,
#:   motherduck database, pg-duckdb duckdb_db_path, redshift iam_role /
#:   s3_bucket / staging_root, snowflake iceberg_external_volume /
#:   staging_root, spark java_home, synapse staging_root.
#:
#:   Secret-bearing -- pg-duckdb motherduck_token, the one key that must never
#:   be CLI-passable, because options land in shell history and in the process
#:   list. The message now names MOTHERDUCK_TOKEN and says why.
#:
#: `redshift.iam_role` was classified secret-bearing in the first audit. That
#: was wrong and is corrected here: it is a role ARN, an identifier, and it
#: exists precisely so the caller does NOT pass aws_secret_access_key. The
#: secrets in that adapter are the access-key pair and the session token, and
#: none of them is advertised as an option.
KNOWN_MISMATCHES: frozenset[tuple[str, str]] = frozenset()


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


def _accepted_option_names(platform: str) -> set[str]:
    """Every spelling the CLI accepts for *platform*, aliases included.

    `list_option_specs` returns primary names only. Checking against that
    alone reported `velox.jar` as rejected when the velox spec has declared
    `aliases=('jar',)` all along and `--platform-option jar=...` exits 0 -- a
    false positive in this guard, not a defect in the adapter. A guard that
    cries wolf gets its allowlist padded, which is exactly how the real
    mismatches would come back.
    """
    names = set(PlatformHookRegistry.list_option_specs(platform))
    for spec in PlatformHookRegistry._option_specs.get(platform, {}).values():
        names.update(getattr(spec, "aliases", ()) or ())
    return names


def _owning_platform(module: str, module_to_key: dict[str, str]) -> str | None:
    """Resolve *module* to the platform that owns it, or None if none does.

    Several adapters live inside a package -- the manifest names
    ``benchbox.platforms.databricks`` while the error text lives in
    ``benchbox.platforms.databricks.adapter``. Matching only the exact module
    silently skipped those files, so walk up to the nearest ancestor package
    the manifest does name before giving up.
    """
    parts = module.split(".")
    if parts[-1] == "__init__":
        parts.pop()
    while parts:
        platform = module_to_key.get(".".join(parts))
        if platform is not None:
            return platform
        parts.pop()
    return None


def _advertised_pairs() -> set[tuple[str, str]]:
    module_to_key = _module_to_platform_key()
    pairs: set[tuple[str, str]] = set()
    for path in sorted(PLATFORMS_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        keys = {m.group(1) for m in ADVERTISED.finditer(text)} - PLACEHOLDERS
        if not keys:
            continue
        module = ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
        platform = _owning_platform(module, module_to_key)
        if platform is None:
            # Shared base/helper module with no single owning platform.
            continue
        allowed = _accepted_option_names(platform)
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


def test_the_bigquery_case_that_motivated_the_guard_is_fixed() -> None:
    """The two original defects are gone from the detected set."""
    detected = _advertised_pairs()
    assert ("bigquery", "project_id") not in detected
    assert ("bigquery", "biglake_connection") not in detected


def test_the_guard_still_detects_a_rejected_advertised_key(tmp_path: Path) -> None:
    """Negative control.

    Once the real defect is fixed there is nothing broken left to assert on,
    so synthesize the exact shape it had -- an adapter advertising a key that
    is not in its registered option specs -- and check the detector finds it.
    A control that depends on a real defect staying broken stops being a
    control the moment someone fixes it.
    """
    allowed = set(PlatformHookRegistry.list_option_specs("bigquery"))
    rejected_key = "not_a_registered_option"
    assert rejected_key not in allowed, "fixture assumption changed"

    source = tmp_path / "bigquery.py"
    source.write_text(f'"""--platform-option {rejected_key}=<value>"""\n', encoding="utf-8")
    keys = {m.group(1) for m in ADVERTISED.finditer(source.read_text(encoding="utf-8"))}

    assert keys - PLACEHOLDERS - allowed == {rejected_key}


def test_an_accepted_key_is_not_flagged() -> None:
    """Positive control: a real spec key must never appear as a mismatch."""
    allowed = set(PlatformHookRegistry.list_option_specs("postgresql"))
    assert "host" in allowed, "fixture assumption changed"
    assert ("postgresql", "host") not in _advertised_pairs()
