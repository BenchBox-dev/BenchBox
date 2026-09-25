# ADR: Require complete TPC-Havoc variants for public submissions

- Status: Accepted
- Date: 2026-09-24
- Constrains: `benchbox/validation/bundle.py`, the TPC-Havoc variant registry,
  and platform execution-filter skip policies.

## Context

TPC-Havoc defines ten variants of each of the 22 TPC-H queries. Its result
bundles identify queries as `N_vK`. The public submission coverage gate
previously compared those IDs with the base IDs `1` through `22`, so even a
complete 220-variant run failed the gate. Counting one variant per base query
would also admit a run that omitted the other nine.

Some engines have documented compatibility skips. Those queries are filtered
before execution and do not appear as successful timings in a bundle. The
skip dictionaries in the execution-filter rules identify the allowed gaps.

## Decision

A TPC-Havoc base query counts as covered only when every declared variant has
a successful timing or is in the documented skip set for the bundle's engine.
An unrecognized ID, an unsuccessful timing, or an undocumented omission never
fills a gap. The existing clean-validation rule still rejects failed
measurement evidence.

The public results mirror runs a slim, standard-library-only validator. It
does not ship the variant registry or execution-filter modules, so the
validator carries a fixed snapshot of their IDs. A unit contract test compares
that snapshot with the source registry and skip dictionaries. Changes to a
variant or skip policy must update the snapshot in the same change.

The denominator shown to readers remains 22 logical queries. A coverage error
names both the missing logical queries and representative missing variants.

## Consequences

Complete DuckDB runs with all 220 variants can pass this gate. Engines with
documented skips can pass when all remaining variants succeed. Partial runs
remain local artifacts or use the trusted mirror path; an engine cannot
self-declare new skips in its bundle.
