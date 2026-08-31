# Nightly SQLGlot generator disposition

Date: 2026-08-31
Owner: @joeharris76
Status: accepted

## Decision

Choose **ADVISORY_WITH_AGE** for future SQLGlot generated-case failures.
Nightly reports these failures but does not join the develop post-merge
auto-revert path. This decision adds no generator or workflow job.

Known failures live in `_project/sqlglot-upstream/generator-policy.json` and
must carry the exact SQLGlot version, integer seed, source dialect, target
dialect, failure artifact, owner, canonical SQLGlot GitHub issue, and
first-known date needed for deterministic replay. Replay fields use a narrow
shell-safe grammar. The list starts empty.

If the generator is implemented later, its replay entrypoint belongs at
`_project/sqlglot-upstream/repros/generator.py`, keeping the pilot under its
allowed project-evidence scope rather than adding another script surface.

The maximum age is seven calendar days. An entry is valid at ages 0 through 6
and the guard fails when `age >= max_known_failure_age_days`, including day 7.
The policy cannot raise or lower that maximum without changing the guard and
its tests.

## Rationale and operation

Generated cases can reveal useful upstream translation gaps without making an
unreviewed generator an automatic revert authority. A short, fail-closed
exception window keeps the signal visible while requiring prompt ownership and
an upstream record.

Run the guard locally with:

```bash
uv run -- python scripts/check_sqlglot_generator_known_failures.py --policy _project/sqlglot-upstream/generator-policy.json
```

Malformed policy data, missing or unknown fields, duplicate IDs, future dates,
expired entries, and incomplete replay metadata all fail validation. The
default comparison date is the current UTC date; `--today YYYY-MM-DD` provides
a deterministic audit boundary.

Policy, age, artifact, and infrastructure guard failures are blocking. Only a
new generated-case discovery is advisory. Future workflow wiring must preserve
that split and must not use job-level continue-on-error.
