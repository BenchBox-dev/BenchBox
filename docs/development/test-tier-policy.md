# Test tiers, duration budgets, and quarantine

BenchBox uses explicit test tiers so routine validation stays predictable while
nightly validation can exercise the full suite.

## Tiers

| Tier | Selection | Duration policy | Quarantine policy |
| --- | --- | --- | --- |
| T1 | `fast` tests in the routine lane | A measured p95 above 0.5 seconds must be fixed, moved to T2, or covered by a time-limited exemption | Quarantined tests are skipped |
| T2 | The medium or integration validation lane | No T1 per-test budget is enforced | Quarantined tests are skipped |
| T3 | Nightly full-fidelity validation | Collects JUnit timing data used to refresh the committed duration artifact | Quarantined tests run so their owner can repair them |

The active tier is selected with `BENCHBOX_TEST_TIER=t1`, `t2`, or `t3`.
The default is `t1`. An unknown value fails collection rather than silently
running the wrong validation contract.

## Markers

A test that cannot run reliably in T1 or T2 may use a quarantine marker, but the
metadata is mandatory and expires:

```python
@pytest.mark.quarantine(owner="team-name", expiry="2026-10-15", issue="#2450")
def test_external_dependency():
    ...
```

The owner, issue, and ISO date are checked during collection. An expired or
incomplete marker fails collection. The test is skipped in T1 and T2 and runs
in T3.

A fast test whose measured p95 is above the T1 budget may use a temporary
exception while it is being repaired:

```python
@pytest.mark.duration_exempt(reason="tracked fixture optimization", expiry="2026-10-15")
def test_expensive_fast_path():
    ...
```

The exception also requires a future ISO date and fails collection when its
metadata is missing or expired. It does not change the measured duration or
move the test out of the fast lane.

## Duration artifact

`tests/fixtures/test_durations.json` is a checked-in, schema-versioned map from
pytest node ID to p95 duration in seconds. T3 JUnit reports are the source of
truth. The refresh utility merges one or more reports and writes stable JSON:

```bash
uv run -- python _project/scripts/update_test_durations.py \
  --input t3-junit-1.xml \
  --input t3-junit-2.xml
```

The nightly T3 publication job is responsible for supplying those reports and
refreshing the artifact. It merges the fast and T3 reports so the artifact
retains a record for every T1 test. A missing or malformed artifact fails
collection so a stale or partial measurement cannot silently weaken the T1
budget. An unexempted fast test without a timing record in
`test_durations.json` fails collection unless covered by
`@pytest.mark.duration_exempt`. The checked-in artifact may use
`"bootstrap": true` only while its `tests` map is empty, or the one-time
baseline run may set `BENCHBOX_TEST_DURATION_BOOTSTRAP=1`. The updater omits
that flag, so a populated artifact fails closed for newly added or renamed
fast tests.

Collection-time policy is deliberately separate from speed-marker assignment.
It never rewrites `fast`, `medium`, or `slow` markers based on local timing.
That keeps test selection reviewable in source while measured data enforces the
budget.
