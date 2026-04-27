# `benchbox submit --service` Reuse Points

Output of [CLI integration TODO][cli] w2: which parts of the existing
benchbox surfaces are reused vs. net-new when adding the Phase 3
hosted-API backend.

[cli]: ./../DONE/main/planning/integrate-benchbox-cli-submit-and-service-auth.yaml

## Reused (no changes needed)

| Concern                      | Existing surface                                    | Why it works as-is                                             |
|------------------------------|-----------------------------------------------------|----------------------------------------------------------------|
| Result-file discovery (`--last` + filters) | `benchbox.cli.commands.submit:_select_last_result` | Already filters by benchmark/platform; identical for both modes |
| Bundle loading + schema-v2 validation | `benchbox.core.results.loader:load_result_file` | Used today by Phase 2 packager; the `--service` mode validates the same way |
| Submission manifest construction | `benchbox.cli.commands.submit:_build_submission_manifest` | Phase 3's `submission-manifest.json` is the same envelope format as Phase 2's; the manifest's content hash is the `bundle_hash` referenced in the architecture design |
| Companion file resolution (`.plans.json`, `.tuning.json`) | `benchbox.cli.commands.submit:_resolve_companion_files` | Identical for both modes |
| Result history persistence  | `benchbox.core.results.history` (existing)          | After a successful Phase 3 submission, append a hosted-URL field to the same history record. No separate "submissions DB" |
| `benchbox results` listing  | `benchbox.cli.commands.results`                     | Add a `--submitted` filter; the underlying records are the existing history rows with the new field populated |

The whole point of `must_preserve` in the TODO ("submit the canonical
bundle, not a second bespoke payload shape") is that the bytes the
service receives are the bytes Phase 2 already packages. There is no
"hosted bundle" format separate from the canonical bundle.

## Net-new modules

| Concern                                | New module path                            | Notes                                              |
|----------------------------------------|--------------------------------------------|----------------------------------------------------|
| Hosted submit transport (HTTP client)  | `benchbox/core/submit/transport.py`        | Thin wrapper over `httpx`. Handles upload, status polling, retry. No business logic. |
| Idempotency-key generation + persistence | `benchbox/core/submit/idempotency.py`    | Generates client-side UUID, persists per-bundle so retries reuse the key |
| Auth token storage / retrieval         | `benchbox/core/auth/store.py`              | Wraps `keyring`; falls back to encrypted file. Used by the `benchbox auth` command tree |
| Auth CLI commands                      | `benchbox/cli/commands/auth/{login,logout,status,whoami}.py` | New command group; not entangled with submit |
| Service-mode submit handler            | `benchbox/cli/commands/submit_service.py`  | The `--service` branch of `benchbox submit`. Dispatched from the existing submit command after flag parsing |
| Hosted-URL field on history records    | `benchbox/core/results/history.py` (extend) | Single field addition: `hosted_url: Optional[str]` |

## Net-new tests

| Test type           | Path                                            | Coverage                                          |
|---------------------|-------------------------------------------------|---------------------------------------------------|
| Unit                | `tests/unit/cli/commands/test_submit.py` (extend) | Flag parsing for `--service`, `--visibility`, `--idempotency-key`; mode dispatch logic |
| Unit                | `tests/unit/core/submit/test_transport.py`      | Upload + retry, status polling, error mapping     |
| Unit                | `tests/unit/core/submit/test_idempotency.py`    | Key persistence + reuse on retry                  |
| Unit                | `tests/unit/core/auth/test_store.py`            | Token round-trip via keyring; fallback to encrypted file |
| Integration         | `tests/integration/test_hosted_submission.py`   | Full submit flow against `respx` mock service. Cover: success, transient 5xx + retry, 401 → re-auth prompt, idempotent re-submit, --no-wait |
| Smoke               | `tests/smoke/test_submit_dry_run.py`            | `benchbox submit --last --service --dry-run` works without credentials |

## Composition seam (one-line summary)

`benchbox submit` retains its current entry point. After flag parsing,
it dispatches to:

- the existing **PR-packaging** code path when `--output` is set (or
  when neither `--output` nor `--service` is given and config
  `service.default_mode == "pr"`); or
- the new **hosted-service** code path in `submit_service.py` when
  `--service` is set (or default mode is "service").

Both paths share the bundle-loading and manifest-construction helpers.
Only the *destination* differs — and that is exactly what the
`publish` vs. `submit` distinction in the strategy doc says it should
be.

## Anti-patterns this design rules out

- **Two submit commands.** Tempting (`benchbox submit-service`) but
  splits the user mental model. One command, two destinations.
- **A second bundle format.** The canonical schema-v2 bundle is what
  the service receives. No "wire-format" intermediary.
- **A separate submission history.** `benchbox results --submitted`
  reads from the same history table that Phase 2 already populates.
  The hosted URL is one column, not a separate ledger.
- **Auth in submit.py.** The submit command handles token *use* (read
  from store, attach to request); the `benchbox auth` command tree
  handles token *management* (login, refresh, logout, whoami). Both
  consume the same store module.
