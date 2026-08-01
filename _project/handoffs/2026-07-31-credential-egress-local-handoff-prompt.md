Validate, adversarially review, and complete the follow-ups of the
credential-egress batch that a remote session landed on develop overnight
(2026-07-31 → 2026-08-01). Repo: /Users/joe/Developer/BenchBox (branch develop).
You are running LOCALLY on the primary machine — some work below was deferred
precisely because it needs this machine.

Work in four phases, in order. Phase 2 is REVIEW-ONLY (findings, no edits).

═══════════════════════════════════════════════════════════════════════
WHAT LANDED (all squash-merged to develop, one TODO per PR)
═══════════════════════════════════════════════════════════════════════

  #1378  feat(tracker): lint verification commands that cannot execute
         (todo-lint-unrunnable-verification-commands-2)
  #1379  fix(results): share one secret-key list between capture and
         anonymization (anonymization-path-misses-key-id-secrets)
  #1380  fix(make): let guards-fix finish its report when the skill-sync
         step fails (guards-fix-aborts-on-skill-sync-unreadable-tree-2)
  #1381  fix(results): redact connection usernames in internal result
         metadata (internal-result-metadata-exports-connection-usernames)
  #1382  feat(tooling): guard against a uv.lock schema-revision downgrade
         (uv-lock-revision-downgrade-guard-2)
  #1383  feat(tracker): lint unresolvable scope globs and ladder file paths
         (todo-lint-unresolvable-scope-and-ladder-paths-2)
  #1384  fix(results): redact api_key and account_key on both export layers
         (public-export-misses-api-key-and-storage-account-key)
  #1385  feat(tracker): lint claim-level quality — falsifiable ladders and
         test-file scope completeness
         (todo-lint-rung-falsifiability-and-scope-completeness-2)

Context you MUST read before starting: the phase-1 findings report, committed
with this prompt on branch claude/benchbox-credential-egress-emxkl9-handoff at
_project/handoffs/2026-07-31-credential-egress-phase1-findings.md
(`git fetch origin claude/benchbox-credential-egress-emxkl9-handoff` then read
it from that ref; the branch is a handoff artifact, not for merging). Its load-bearing
conclusions: 47 registered adapters (not 25); the map-egress channels are ~4
central functions, not 25x7 cells; two defect families (value-materialisation
vs key-list gaps); SecretStr (L1 of the old proposal) rejected as unjustified;
the L3 sentinel sweep found the leaks that #1384 fixed. The 4-layer proposal
remains UNAPPROVED — nothing beyond what the PRs above contain was built.

Tracker state changes made by the remote session (actor
claude-egress-review-20260731):
  - 5 defective items dropped with successor-naming reasons; -2 successors
    created and all implemented.
  - test-export-invalid-output-dir-assumes-non-root (2026-07-30) dropped as a
    duplicate of cli-invalid-output-dir-tests-assume-non-root (broken rung,
    narrower scope; the drop reason names the successor).
  - 10 new lint-clean items created from review findings (list in phase 4).
  - Deferral 674 promoted to guards-fix-skill-sync-real-cli-manual-confirmation.
  - HOSTED DB CONFIG: lint.require_falsifiable_rung=on and
    lint.require_scope_test_files=on (both default OFF in code). This makes
    ~137 falsifiability + ~15 scope-completeness warn findings appear on
    legacy open items in `todo lint --all`. Decide deliberately in phase 2
    whether to keep them on, turn them off, or triage the backlog.

═══════════════════════════════════════════════════════════════════════
PHASE 1 — VALIDATE ON THIS MACHINE (read-only + test runs)
═══════════════════════════════════════════════════════════════════════

 1. `git fetch && git log --oneline origin/develop -10` — confirm #1378–#1385
    are the top commits (interleaved with #1376/#1377 from other sessions).
 2. Re-run the verification ladder of every one of the eight completed items
    (`todo show <id>` prints it) on merged develop. Every formerly-gating rung
    must now exit 0; every regression-guard rung must pass. Caveats:
      - The two tracker-lint rungs (`todo lint ducklake-beta-scale-runs-four-modes
        | grep ...` and `todo lint motherduck-token-leak-via-chained-cause |
        grep ...`) need the hosted env (see ENVIRONMENT below).
      - The guards-fix stub rung REGENERATES drift artifacts as a side effect —
        run it in a pool worktree and reset the regen output (do not commit the
        oracle-coverage-map restamp).
      - `make guards-fix` normal-path rung: on THIS machine the skill-sync CLI
        exists, so it will actually sync — review the diff before discarding.
 3. Run the suites the PRs cite: tests/unit/scripts (todo_db family),
    tests/unit/core/results, tests/unit/platforms/test_motherduck.py. Note:
    the remote container ran everything as root; three tests/unit/cli tests
    failed there for root-only reasons (tracked as
    cli-invalid-output-dir-tests-assume-non-root). Locally as non-root they
    should pass — confirm, because that confirms the item's premise.
 4. Validate the uv-lock guard end-to-end locally: `make uv-lock-revision-check`
    on a clean tree (exit 0), then stage a synthetic revision-2 uv.lock copy in
    a scratch worktree and confirm the pre-commit hook rejects it. Also check
    YOUR local uv version against the documented minimum (uv >= 0.8,
    docs/development/development.md).

═══════════════════════════════════════════════════════════════════════
PHASE 2 — ADVERSARIAL REVIEW (findings only, no edits, no tracker writes)
═══════════════════════════════════════════════════════════════════════

Apply ~/.claude/skills/SHARED/review-protocol/SKILL.md (the real one exists on
this machine). Verify by DRIVING entry points, never by reading predicates —
the prior sessions were burned by this three times. Known soft spots to attack
first (be harsher than this list):

 1. The falsifiability heuristic (_GATING_EXPECTED_RE in todo_db.py) is
    TEXT-based and loose: bare "today", "once", "until" anywhere in expected
    text counts as gating. Construct a rung that passes the heuristic while
    gating nothing, and one that gates but fails the heuristic. Decide whether
    the category exemptions (flake, validation) are a hole — any author can
    self-exempt by picking the category.
 2. The near-miss cutoff (0.87) dropped a genuine catch during calibration:
    do_not_modify naming benchbox/core/runner.py where only the runner/
    package exists (ratio 0.80). Look for other real typos now under the
    cutoff, and check whether deny-rule typos deserve a separate, stricter
    rule (a deny that matches nothing protects nothing).
 3. _USERNAME_KEYS is an enumerated set {user, username, userid, pguser,
    dbuser}. Sweep the 47 adapters for other username spellings (login, uid,
    admin_user, svc_user, snowflake 'user' aliases...) that still export
    verbatim internally.
 4. The api_key/account_key parts (#1384): sweep real platform options for
    over-redaction (any legitimate non-secret key containing 'apikey' or
    'accountkey'?), and for near-miss credential keys still uncovered
    (auth, pat, pwd, passwd were known-missing at review time — confirm and
    weigh adding them).
 5. #1379 made anonymization.py import from platform_options at module load.
    Check import-order/cycle robustness (lazy loaders, partial-init paths) and
    that anonymization_specs.yaml consumers elsewhere didn't depend on the
    removed secret_key_parts key.
 6. #1380's containment is `$(MAKE) -s skill-sync || echo WARNING...` — the
    warning goes to stdout and guards-fix exits 0. Confirm genuine mirror
    drift is still caught by skill-sync-check in CI and pre-commit, and that
    exit-0-with-warning cannot mask a real failure in any automation that
    wraps guards-fix.
 7. The uv-lock guard is wired into pre-commit + a make target but NOT the
    pr.yml lint job (deliberate scope decision; CI-local parity contract).
    Decide whether that leaves a real gap (contributor without pre-commit
    pushing a downgrade straight to a PR) and whether pr.yml wiring plus the
    parity test update is warranted.
 8. The hosted-DB lint config flip (see above): keep/off/triage. If keep,
    the ~150 legacy findings need an owner or a sweep plan.
 9. Done-item path resolution (#1383) flags a done item whose rung references
    a file that exists only after a parallel PR merges — transient by design,
    but confirm no standing false positives remain now everything is merged:
    `todo lint --include-done` (hosted) and eyeball the resolution findings.

Deliver a findings report with severities before touching anything.

═══════════════════════════════════════════════════════════════════════
PHASE 3 — FIX WHAT PHASE 2 FOUND
═══════════════════════════════════════════════════════════════════════

Normal flow: `make worktree-claim BRANCH=fix/<slug>`, agent-write-preflight,
one concern per PR against develop, `make pr-open` (auto-merge). Anything
out of scope of a quick fix becomes a new tracker item — which must now carry
a gating rung with unfixed-tree-failure language and complete test-file scope,
or the new lint checks will flag it at `todo lint` time. Log every new defect
as its own item. Do not relax or delete a rung to make something pass.

═══════════════════════════════════════════════════════════════════════
PHASE 4 — COMPLETE THE FOLLOW-UPS AND DEFERRALS
═══════════════════════════════════════════════════════════════════════

Use the todo-db `batch` action, one TODO per PR. Every item below has a
verification ladder already verified to fail on the unfixed tree (2026-07-31);
each has a w0-style re-validation step — run it on current develop before
implementing, and if the premise changed, say so rather than implementing on
the old premise.

  MACHINE-BOUND (only this machine can do these — do them first):
    guards-fix-skill-sync-real-cli-manual-confirmation   low
      The real skill-sync CLI is at /Users/joe/Developer/skill-sync. Confirm
      the original 'unable to read tree' case now reports-and-completes, and
      that genuine drift still fails skill-sync-check. Record both outcomes.
    ducklake-remeasure-cv-on-quiet-host                  low
      Needs an IDLE host + live PostgreSQL + S3. Use mocker for PG — note
      `-p 5432:5432` port forwarding DOES NOT WORK; reach the server at the
      container IP from `container ls` (PG_DUCKLAKE_HOST=192.168.64.x).
      If the host is busy, leave it — a contended-host measurement is worse
      than none. n>=5 per mode, then update the ADR table and remove the
      'Re-measure on a quiet host' caveat.

  CREDENTIAL EGRESS (core-functionality/security):
    csv-html-tuning-exports-bypass-anonymization                medium
    mcp-output-bypasses-anonymization-and-echoes-raw-exceptions medium
      (w1 is a genuine decision: anonymize MCP payloads vs documented
       exemption + error-text scrubbing; don't skip the decision)
    public-export-pg-user-and-tenant-id-bypass-pseudonymization medium
    databend-dsn-password-exported-verbatim-in-result-metadata  medium
    cli-debug-logging-carries-raw-platform-options              medium
    platform-config-extraction-lacks-secret-filtering           low
    singlestore-setup-persists-password-on-failed-validation    low
      (w0 is a decision: persisting INVALID creds may be intended retry UX;
       survey the sibling setups before fixing one)

  HYGIENE / TESTS:
    dead-sanitize-error-message-and-duplicate-motherduck-redactor  low
    cli-invalid-output-dir-tests-assume-non-root                   low
      CAUTION: its gating rung fails ONLY when run as root. Locally it
      passes vacuously — validate the fix in a root container (docker run
      as root, or CI), or record explicitly that the rung was exercised
      only as non-root.

  LEAVE ALONE unless it recurs:
    xdist-internalerror-monitoring-gate-flake (observational tripwire)

Ordering notes: the three anonymization-adjacent items (csv-html, pg-user,
dsn) all touch benchbox/core/results/* — sequence them or expect rebases.
platform-config-extraction should land BEFORE or WITH the MCP item (MCP
returns platform.config verbatim; filtering it upstream shrinks the MCP
decision). If phase 2 changed any item's premise or severity, repair via
`todo drop <id> --reason "... Successor: <new-id>"` + `todo create` —
scope/ladder/units are create-time-only, drop is terminal, name successors.

═══════════════════════════════════════════════════════════════════════
ENVIRONMENT (local machine — mostly the traps you already know)
═══════════════════════════════════════════════════════════════════════

Tracker (Turso, hosted). Mint tokens inline, never write one to a file:

```bash
export TODO_DB_URL=libsql://benchbox-todo-joeharris76.aws-us-east-1.turso.io
export TODO_DB_AUTH_TOKEN=$(turso db tokens create benchbox-todo --expiration 1d)
export TODO_DB_REPLICA=/tmp/todo-replica-$$/replica.db   # FRESH EMPTY DIR
```

  - Fresh empty replica path (copying an existing replica fails two ways).
  - CWD picks the todo_db.py version; run from a worktree current with
    origin/develop (hosted schema v4; an old CLI errors).
  - Reads look plausible even when misconfigured; only a write proves the
    right primary.
  - The two new lint config keys are ON in the hosted DB; `todo config
    lint.require_falsifiable_rung off` (etc.) is the opt-out if phase 2
    decides against them.

Other traps:
  - Worktrees: `make worktree-claim BRANCH=...`; pool is shared and often
    FULL; release when done; re-check `git branch --show-current` before
    committing.
  - Test lock: ~/.benchbox/test.lock serialises pytest across worktrees; a
    blocked run is usually another session.
  - `make guards-fix` no longer aborts on a skill-sync failure (that's #1380)
    but still restamps _project/analysis/oracle-coverage-map.md — do not
    commit that restamp.
  - uv.lock downgrades are now REJECTED by pre-commit (#1382); if the hook
    fires, upgrade uv, don't fight the guard.
  - CI: medium-test ~30 min; auto-merge via `make pr-open`; an xdist
    INTERNALERROR is a worker crash (usually flake) — verify locally before
    blaming your change.

═══════════════════════════════════════════════════════════════════════
DEFINITION OF DONE
═══════════════════════════════════════════════════════════════════════

  - Phase 1: every ladder of the eight done items re-run locally with results
    recorded (including both hosted-env rungs).
  - Phase 2: a findings report; every claim backed by a driven entry point.
  - Phase 3: every Critical/Required finding fixed (own PR) or refuted with
    cited evidence; new defects logged as lint-clean items.
  - Phase 4: every listed item completed with `todo complete <id> --pr <n>`,
    or explicitly left with the item's own justification (idle-host rule,
    root-only rung, recurrence tripwire). The two machine-bound items get
    first attention since only this machine can do them.
  - A closing summary: validation results, findings + dispositions, PRs
    opened/merged, items completed/deferred, the hosted-config decision, and
    anything you could not verify.

DO NOT:
  - Do not edit anything during phases 1–2.
  - Do not implement the old 4-layer proposal (still unapproved); if phase 2
    concludes a layer is now justified, say so and ask.
  - Do not relax or delete a rung to make an item or a fix pass.
  - Do not report conclusions from reading matchers/predicates — drive the
    entry point and paste observed output.
  - Do not commit guards-fix regen restamps or raw logs.
  - Do not release another session's worktree or claim.
