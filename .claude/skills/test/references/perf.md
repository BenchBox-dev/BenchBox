# Slow Test Reference

Optimize test runtime only after measuring.

## Process

1. Run duration reporting for the relevant suite.
2. Group slowness: setup, I/O, database/container, network/mock gaps, data volume, sleeps/retries, parametrization explosion.
3. Prove the bottleneck with targeted timing/profile output.
4. Apply the narrowest fix.
5. Rerun affected tests and compare timings.

## Common Fixes

- Reuse expensive setup with wider-scoped fixtures when isolation remains correct.
- Replace external services with local fakes/mocks where behavior under test permits.
- Reduce fixture data to the smallest shape that exercises the branch.
- Split slow integration coverage from fast unit coverage using existing markers.
- Remove arbitrary sleeps by waiting on explicit conditions.

## Rules

Do not weaken assertions, delete meaningful coverage, or hide flakes. Report before/after timing and any risk tradeoff.
