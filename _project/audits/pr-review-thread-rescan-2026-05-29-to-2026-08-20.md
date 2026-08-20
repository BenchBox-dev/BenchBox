# PR review thread rescan: 2026-05-29 to 2026-08-20

- Sweep head: `1e8cc3dee48a4c345bb96df2e59f47cdbf6dde5f` (`origin/develop` at collection time)
- Merged-PR scope: latest 1,000 PRs merged to `develop`
- Window: 2026-05-29 through 2026-08-20, inclusive
- Canonical inventory: 613 unmarked root review comments across 426 PRs
- Thread state: 60 open threads (57 current, 3 outdated) and 553 resolved threads retained for phantom-resolution audit
- Open-thread classification after current-tree revalidation: 25 fixed here, 22 already fixed, 1 deferred, 12 rejected

This audit records the evidence boundary for the remediation branch. Source-thread replies must link the durable remediation PR before the strict final rescan can report zero pending comments.

## Resolved By w1-wN

The remediation branch fixes these 25 source threads:

| Source PR | Comment | Thread | Work unit |
| --- | ---: | --- | --- |
| #876 | 3462254465 | `PRRT_kwDOQ7J64c6LsUPP` | w2 |
| #972 | 3524970785 | `PRRT_kwDOQ7J64c6Oaqz8` | w2 |
| #991 | 3525517230 | `PRRT_kwDOQ7J64c6OcN02` | w2 |
| #991 | 3525517233 | `PRRT_kwDOQ7J64c6OcN04` | w2 |
| #1075 | 3554319791 | `PRRT_kwDOQ7J64c6Pr0Dj` | w3 |
| #1093 | 3558872360 | `PRRT_kwDOQ7J64c6P4VfP` | w3 |
| #1102 | 3559188480 | `PRRT_kwDOQ7J64c6P5Ml8` | w3 |
| #1124 | 3561755973 | `PRRT_kwDOQ7J64c6QANu0` | w4 |
| #1149 | 3565404472 | `PRRT_kwDOQ7J64c6QKNdU` | w4 |
| #1159 | 3566248907 | `PRRT_kwDOQ7J64c6QMkON` | w4 |
| #1175 | 3592103659 | `PRRT_kwDOQ7J64c6RTI-9` | w4 |
| #1196 | 3599261158 | `PRRT_kwDOQ7J64c6RmpcF` | w3 |
| #1498 | 3708588231 | `PRRT_kwDOQ7J64c6WKOrJ` | w2 |
| #1503 | 3708852796 | `PRRT_kwDOQ7J64c6WK6ju` | w2 |
| #1529 | 3712660156 | `PRRT_kwDOQ7J64c6WU43X` | w2 |
| #1538 | 3714375079 | `PRRT_kwDOQ7J64c6WZZc9` | w2 |
| #1539 | 3714378349 | `PRRT_kwDOQ7J64c6WZZ_y` | w2 |
| #1548 | 3714911973 | `PRRT_kwDOQ7J64c6WazRr` | w3 |
| #1550 | 3715073202 | `PRRT_kwDOQ7J64c6WbOhH` | w3 |
| #1551 | 3715151813 | `PRRT_kwDOQ7J64c6WbbvC` | w3 |
| #1777 | 3816023499 | `PRRT_kwDOQ7J64c6algfU` | w4 |
| #1777 | 3816023510 | `PRRT_kwDOQ7J64c6algfc` | w4 |
| #1781 | 3821466178 | `PRRT_kwDOQ7J64c6aza5p` | w4 |
| #1781 | 3821466184 | `PRRT_kwDOQ7J64c6aza5v` | w4 |
| #1783 | 3823501314 | `PRRT_kwDOQ7J64c6a4q_Y` | w4 |

Axis 3 also found and repaired two weakened tests that were not source review threads: the forced landing-page CSS state in public visual capture, and the same-output primitives concurrency test that accepted `IndexError`. Axis 5 repaired 27 stale verification rungs across 20 terminal items, amended seven known semantic false positives or exemplars, and added a bounded semantic linter.

## Already-Fixed By Earlier Merges

Current-tree inspection showed that 22 reports were already fixed or superseded. This includes the initially classified #955 report: the reviewed YAML item no longer exists, and the current hosted tracker does not carry that failing verification command.

`#824/3444628573`, `#913/3488713690`, `#955/3523676549`, `#1091/3558813972`, `#1096/3558989229`, `#1096/3558989240`, `#1496/3708544115`, `#1497/3708587044`, `#1500/3708628701`, `#1503/3708852791`, `#1511/3712138980`, `#1511/3712138985`, `#1515/3712300782`, `#1515/3712300793`, `#1521/3712417649`, `#1531/3712688244`, `#1538/3714375073`, `#1539/3714378345`, `#1541/3714424163`, `#1545/3714793143`, `#1545/3714793155`, `#1548/3714911966`.

Twelve identity-only comments were rejected under `AGENTS.md` review policy because commit identity is not a PR defect: `#1339/3674924072`, `#1512/3712184847`, `#1514/3712244304`, `#1521/3712417657`, `#1522/3712465207`, `#1523/3712516100`, `#1524/3712560416`, `#1541/3714424167`, `#1545/3714793148`, `#1549/3714970667`, `#1552/3715414567`, and `#1553/3715752387`.

## Still Actionable

One valid report is intentionally deferred from this remediation because it requires a cross-adapter throughput-session design and implementation: PR #1095, comment 3558916574, thread `PRRT_kwDOQ7J64c6P4dMQ`. It must remain visible as follow-up work rather than being marked fixed.

No other concrete defect from the 60 open threads remains unimplemented in the remediation branch. The final zero-pending assertion remains gated on a durable PR link, source-thread action-marker replies, CI, maintainer review for soundness-path changes, and merge.

## Other mandatory axes

- Axis 2: the hosted findings store was checked live. The verification-rung blind spot is actioned; auto-revert and serialization-boundary findings are promoted. The only actionable in-window hosted record belongs to the external `memory-governance` repository and is outside this BenchBox sweep. One unsynced local product-process draft is also outside merged-PR correctness scope.
- Axis 4: all 553 resolved threads remain in the audit inventory. Resolution state is not used to enqueue remediation, and the hardened collector keeps resolved threads separate for phantom-resolution inspection.
- Axis 5: the current-window semantic linter passes after the tracker amendments. The broader `todo lint --all` corpus still reports pre-existing tracker-quality debt outside this bounded sweep; that baseline is not treated as a green gate.
