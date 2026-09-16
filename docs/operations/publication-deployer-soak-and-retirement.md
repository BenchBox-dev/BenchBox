# Publication deployment and cutover

`publication-transaction.yml` is the one normal production writer for
benchbox.dev. It uses the append-only `publication` journal to reserve a
generation and to distinguish desired, built, provider-acknowledged, and
publicly verified state. `publication-deploy.yml` is the candidate builder. It
does not perform a normal Pages write.

## Normal promotion

1. Dispatch `Publication Control Plane Deployment` from `develop` with
   `candidate_only=true`. The workflow resolves the current `develop` and
   `published-results` commits and the next journal generation, builds the
   site, validates privacy and lane inputs, and uploads one retained candidate
   bundle.
2. Select the immutable numeric artifact ID from that run. The transaction
   workflow downloads and validates the artifact before the approval job is
   entered. Validation checks the producing run, workflow path, successful
   develop dispatch, exact source pins, manifest digest, unpacked tree digest,
   safe archive extraction, target, parent, and all required route checksums:
   `/`, `/docs/`, `/docs/api.html`, `/results/`, and
   `/results/data/results.duckdb`.
3. Review the generated candidate summary and approve the protected
   `github-pages` environment once. There is no permit hash, comment, tracker
   claim, generation entry, or author footer to copy into the workflow.
4. The deploy job revalidates the same artifact after approval, then records
   journal intent before submitting the Pages write. It uploads the exact site
   bytes, records the provider response, probes the public routes, signs the
   live receipt, and advances the durable journal head only after verification.

A changed branch, expired artifact, changed artifact contents, stale parent,
wrong producer, incomplete route set, or unresolved prior write stops the
transaction. To retry a rejected or failed pre-write run, start a new
transaction against the same immutable artifact and approve that new run.
An uncertain provider write remains quarantined until provider finality is
established; a fresh approval does not clear it.

## Rollback and recovery

Rollback uses the normal transaction writer and a retained, previously verified
artifact. It restores exact bytes, performs fresh public verification, and
creates a successor receipt. It does not rebuild from a branch or use an
artifact name as a substitute for identity.

`publication-recover.yml` is observational. It reads the journal, reports
unknown or stale operations, and retains a report. It has no Pages, journal
write, signing, or compensation capability. An operation older than ten
minutes is reported as `stale_transaction`; an unknown provider outcome stays
blocked. After provider finality is established, an authorized maintainer
starts the protected transaction workflow for restoration.

The journal's CAS protects its own state and serializes the normal writer. It
does not fence a Pages request that is already in flight and does not prevent
other workflows from writing Pages. During cutover, legacy writers must be
drained and their normal admission disabled before a production transaction is
started.

## Cutover evidence

The fixed 72-hour timer, three-production-run count, and separate retirement
approval are superseded. Completion evidence is outcome based:

- one verified production publication with its signed receipt;
- an independent monitor that records five-minute availability observations,
  reports missing observations within ten minutes, and demonstrates a failed or
  missing observation;
- a safe exact-artifact restoration test;
- a test that an unknown provider outcome remains quarantined;
- the relevant lane and contract checks for the candidate build.

Five-minute observations probe availability without downloading DuckDB. A full
content comparison, including DuckDB and all required routes, runs hourly and
after each transaction. An active transaction produces availability observations
but its content status is `unknown`; it is never counted as healthy coverage.
The monitor retains timestamps and outcomes, so missing data is not silently
treated as success. GitHub Actions scheduling alone does not satisfy the
independent-monitor requirement.

The external monitor must target `https://benchbox.dev/` and the four HTML
routes above every five minutes, alert after two missed observations, and run
the full route and DuckDB comparison hourly. It must retain observations for
at least 30 days. No external monitor credential is currently available in the
repository; activation is a deployment dependency, not evidence that monitoring
is already active.

## Current status (2026-09-15)

The transaction writer is the active production path. The `publication` journal shows durable
generation 7 (`live-7-570c2c50-d8c0-48fb-9ee8-d83afc272061`, run `34702300640`, 2026-09-12) with
`next_generation: 8` and no active transaction. Generation 6 demonstrated quarantine and forward
reconciliation: a `POST_SEND_FAILURE` entered `recovery-required`, then reconciled forward with a
signed live receipt before generation 7 promoted.

Cutover evidence state:

- Verified production publication with signed receipt: present (generation 7).
- Internal availability monitor (`publication-soak-monitor.yml`): running on its five-minute schedule
  with 30-day observation artifacts, a best-effort top-of-hour full content check, and `unknown`
  (never healthy) status during an active transaction. Recent runs show GitHub scheduling gaps
  longer than five minutes, so schedule cadence alone is not five-minute coverage; a top-of-hour
  run delayed past minute five performs an availability check instead of a full comparison, so a
  full check is not guaranteed every hour.
- External independent monitor: still missing. No external monitor credential exists in the
  repository. Activation remains a deployment dependency, not completed evidence.
- Safe exact-artifact restoration test through the protected rollback path: still pending
  post-cutover demonstration.
- Legacy retirement: pending. `.github/workflows/docs.yml` still contains the release-to-Pages job,
  but it skips while a recent independent publication owns Pages (ownership guard over unexpired
  live-receipt artifacts, retained 90 days). `develop` and `release`
  both remain in the `github-pages` deployment-branch policy; `develop` must stay while the
  transaction workflow requires dispatch from that ref. `sync-results-data-to-published.yml` is a
  corpus mirror into `published-results`, not a Pages writer, so it stays.

## Legacy retirement

The historical freeze closure
`docs/operations/publication-freeze-closure-2026-09-04.json` is preserved as
historical evidence and is not rewritten. Once the replacement writer has
deployed and the cutover evidence above exists:

1. disable the release-to-Pages job in `.github/workflows/docs.yml`;
2. remove `.github/workflows/sync-results-data-to-published.yml` if it is still
   an independent publication writer;
3. keep release API-doc production and the accepted `published-results` corpus;
4. keep the retained exact restoration artifact and the protected transaction
   rollback path;
5. reconcile any mirror changes by exact path and content equivalence.

Do not remove `develop` from the Pages deployment policy while the transaction
workflow still requires dispatch from that ref. Tracker items record the
superseded timer and any unactivated external monitoring as requirements
disposition, not as completed production evidence.
