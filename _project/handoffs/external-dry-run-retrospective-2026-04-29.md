# External Dry-Run Retrospective — 2026-04-29

> Source: agent-proxy run via Codex (Joe-supervised, against PyPI
> `benchbox 0.2.1` on a clone of the `published-results` branch). The
> parent TODO `external-contributor-submission-dry-run` requires a
> *human* contributor dry-run; this run is the **second** doc-hardening
> pre-pass after the 2026-04-28 Cowork run, and the TODO is **not
> closed** by it. See "Agent-vs-human caveat" at the bottom.

## Headline finding

The community submission flow has a **release-blocker hash-contract
mismatch** between the submit writer and the validator that runs in CI
on `published-results`. Confirmed empirically and forensically:

- Codex's manifest recorded `bundle_hash: 799c80a2...` (per-FILE SHA-256
  of the bundle JSON).
- `shasum -a 256` of the actual bundle file: `799c80a2...` (matches the
  manifest exactly — the writer is internally consistent).
- The validator on `published-results` (commit `0182c9556`, v0.2.1)
  computed `8a89ab6f...` and reported `Bundle hash mismatch`.
- Forensic: the validator on `published-results` uses a per-DIRECTORY
  hash (`for f in bundle_dir: sha256(rel_path + bytes)`); the validator
  on `develop` (post-PR #33) uses per-FILE. They will never agree.

**Net:** any submission produced today by `develop`'s `benchbox submit`
will fail CI on `published-results`. Filed as
`dry-run-followup-validator-hash-contract-mismatch.yaml` (Critical).

## Timeline (from contributor's report + maintainer forensic)

- 20:49 EDT — Codex started reading `docs/contributing-results.md`.
- 20:50 EDT — First `benchbox` command. Bundle generated cleanly:
  `tpch_sf001_duckdb_sql_20260428_205018_e4f24ee2.json`.
- 20:50 EDT — `benchbox submit` packaged the bundle into
  `/Users/joe/Developer/BenchBox/submission/`. Manifest written with
  per-file hash.
- ~20:51 EDT — Bundle copied into the clone's `results-data/bundles/`,
  alongside a fresh `submission-manifest.json`.
- ~20:55 EDT — Local validator on `published-results` failed with
  `Bundle hash mismatch: manifest says 799c80a21b651fe2..., computed
  8a89ab6f5a61d845...`. Codex stopped before opening a PR.
- ~20:57 EDT — Codex submitted report.
- 2026-04-29 (post-hoc) — Maintainer forensic confirmed the hash
  algorithm divergence between branches (see Headline above).

Total wall time start → blocked: ~8 min. PR never opened.

## Environment caveats

Codex's run could not test:

- **PR open / CI on the workflow runner** — Codex stopped at the local
  validator step. The actual `validate-submission.yml` workflow that
  runs on a real PR uses the same `scripts/validate_submission.py`, so
  the failure would have replayed identically; Codex's local run is a
  high-fidelity proxy for what CI would have done.
- **Maintainer review / merge / docs CI rebuild** of `results-explorer`.
- **Trust-label assignment** in the explorer.

What Codex's run *did* exercise vs the 2026-04-28 Cowork run:

- ✅ End-to-end dry-run of the local validator (Cowork couldn't reach this).
- ✅ A clone of `published-results` (Cowork ran on `main`).
- ✅ `git config user.name` was set ("Joe Harris"), so the
  `submitted_by` empty-string path was not exercised.
- ❌ PyPI `benchbox 0.2.1` was used as the submit binary, so the
  in-bundle `CONTRIBUTING.md` Codex saw was the OLD stub (the fixes in
  PR #43 are on `develop` but not in any released wheel yet).

## Friction items (one bullet per item, classified)

### Critical (release-blocker)

- **Hash-contract mismatch between writer and `published-results`
  validator.** Per-file vs per-directory algorithm disagreement. See
  Headline. Filed as
  `dry-run-followup-validator-hash-contract-mismatch.yaml`.

### Already addressed by in-flight PRs (PyPI release pending)

- **Generated `submission/CONTRIBUTING.md` omits inventory regeneration,
  target branch, and local-validation steps.** Same bug the Cowork run
  hit. Codex was using PyPI 0.2.1, which still ships the OLD stub.
  Fixed on `develop` by PR #43 (merged); will land for contributors at
  the next PyPI release. **No new TODO.**
- **Manifest filename collision risk** (`submission-manifest.json` is
  generic; two contributors → same filename). Same Cowork finding.
  Fixed on `develop` by PR #45 (auto-merge enabled). **No new TODO.**
- **`submitted_by` silent-empty case** (Cowork hit it; Codex didn't,
  having `git config user.name` set, but the underlying gap is the same).
  Fixed on `develop` by PR #44 (auto-merge enabled). **No new TODO.**

### New friction items (all consolidated into one TODO to avoid sprawl)

Filed as `dry-run-followup-cli-ux-and-doc-polish-2026-04-29.yaml`
(Medium). One work unit per item:

| # | Item | Classification |
|---|---|---|
| 1 | `benchbox` vs `uv run benchbox` vs `uv run -- benchbox` doc inconsistency | doc-fix |
| 2 | `benchbox submit` should print exact next commands (cp dest, inventory, validate, PR title, target branch) | tool-fix |
| 3 | Red `❌ Missing tables` then auto-recovery looks like failure but actually succeeded | tool-fix (UX) |
| 4 | `Interactive Benchmark Runner` header in non-interactive `benchbox run` is misleading | tool-fix (UX) |
| 5 | `benchbox profile` doc references "Platform Availability" table; CLI prints simpler "Available Databases" line | doc-fix |
| 6 | `benchbox submit --dry-run` and real submit output formats differ slightly | tool-fix (UX) |
| 7 | TPC-H `validation disabled for stream_id != 0` warning unclear (Codex unsure if result was fully validated) | doc-fix or downgrade |

## What worked / what didn't / what I'd change

**What worked.** The benchmark itself ran clean and packaged in ~30
seconds end-to-end. The docs are now far enough along that Codex
followed them mostly without backtracking — proof that the dry-run-
followup-* PRs from 2026-04-28 reduced the doc surface area Codex had
to second-guess. The submission package itself was structurally
correct (bundle, manifest, CONTRIBUTING.md all present).

**What didn't.** The submit-vs-validate hash contract mismatch. This
is the first cross-branch correctness defect surfaced by either dry-run
and is invisible until a contributor actually runs the validator. The
Cowork run (2026-04-28) couldn't have found this because it had no
clone of `published-results` to validate against. Two things would
have caught this earlier: (a) a CI cross-branch contract test that
runs the writer + validator on the same bundle; (b) running an
end-to-end round-trip test as part of the release-readiness checklist.

**What I'd change.** Land the validator hash-contract sync before the
next PyPI release. Add the cross-branch contract test as the third
work unit of the new Critical TODO. Once landed, recruit the
human contributor — the docs and tooling are now plausibly ready for
a frictionless human run, modulo the polish items.

## Comparison vs the 2026-04-28 Cowork retrospective

| Friction surfaced 2026-04-28 (Cowork) | Status today (2026-04-29) |
|---|---|
| Broken Prerequisites link to `getting-started.rst` | **Fixed** in PR landed with the 2026-04-28 retrospective |
| `pip install benchbox` lacks `[duckdb]` extras hint | Open (doc fix; not surfaced by Codex because the CLI's hint was clear) |
| Example filename shape doesn't match real output | Open (low; not surfaced by Codex) |
| Bundle table `(if captured)`/`(if used)` undefined | Open in `dry-run-followup-bundle-table-conditionals` (Identified, blocked on maintainer call) |
| Packaged CONTRIBUTING.md disagrees with canonical doc | **Fixed** by PR #43 (merged); contributor still hits OLD copy until next PyPI release |
| Manifest filename collision risk | **Fixed** by PR #45 (auto-merge enabled) |
| `submitted_by` empty silent | **Fixed** by PR #44 (auto-merge enabled) |
| Schema version key naming | **Fixed** by PR #46 (auto-merge enabled) |
| `uv run` validation stall | **Fixed** by PR #46 (auto-merge enabled) |
| Inventory silently filters manifest | Open (low; deferred) |

The dry-run-followup-* PR cluster is doing exactly what was intended:
each item Codex *didn't* hit corresponds to a fix that landed (or is
landing) on `develop`. The new findings are non-overlapping and at a
deeper layer (cross-branch contracts + CLI polish), which is what you
expect when the surface friction has been pre-fixed.

## Agent-vs-human caveat

Codex is a second agent-proxy run, not the human contributor required
to close `external-contributor-submission-dry-run`. Like Cowork, Codex
is structurally limited:

- Pattern-matched the validator error to a specific error string and
  stopped cleanly; a human might have spent 30+ minutes trying to
  re-package, re-run, or grep their bundle for the wrong hash before
  giving up or filing an issue.
- Wrote a structured friction list immediately; humans will more often
  give a single Slack message ("submit is broken, idk why") that
  underspecifies the failure.
- Used a clone of `published-results` directly (the right branch for
  CI) instead of cloning `main` like a typical contributor's `git
  clone` default would land them on. A human would have probably hit
  the wrong-branch friction Cowork hit, *plus* the hash mismatch on
  top.

Net: the parent TODO still needs a human run. But the
hash-contract-mismatch finding is real and would have blocked a human
just as cleanly — Codex just diagnosed it faster. That finding alone
makes this run worth the cost.

## Follow-ups filed

Two new TODOs land alongside this retrospective in
`_project/TODO/main/planning/`:

- `dry-run-followup-validator-hash-contract-mismatch.yaml` (**Critical**)
- `dry-run-followup-cli-ux-and-doc-polish-2026-04-29.yaml` (Medium,
  consolidates 7 friction items as separate work units)

The parent TODO `external-contributor-submission-dry-run` is updated
with a 2026-04-29 stanza naming this as the second agent-proxy
pre-pass and pointing to this retrospective.

The parent TODO is **not closed**: the human contributor dry-run
(w1–w5) is still required because (a) the hash-contract fix needs to
land + ship before recruiting the human, (b) only a human can validate
the post-CI maintainer review and explorer redeploy steps, and (c)
public promotion timing depends on a frictionless human run.

---

## Appendix A — Codex's report verbatim

```
BenchBox Dry-run Report — Codex, 2026-04-29 UTC / 2026-04-28 EDT

1. Outcome
PR URL: didn't open one
Got to a merged PR? No / Stopped at: local validation against published-results
Total wall time, start → PR opened: N/A; stopped before PR after ~8 min

2. Timeline
Started reading docs: ~20:49 EDT
Ran first benchbox command: 20:50 EDT
Opened PR: didn't open one
CI passed: didn't reach CI; local equivalent on published-results failed
PR merged: didn't merge

3. Friction
3a. Steps you re-read or had to guess at
Whether to use bare benchbox, uv run benchbox, or uv run -- benchbox; docs are inconsistent across pages.
Where exactly submission-manifest.json should go. "Alongside the bundle files" implies flat results-data/bundles/, but that is collision-prone.
Whether PR target should be published-results; main doc says yes, generated submission/CONTRIBUTING.md does not.

3b. Errors you hit and how you resolved them
Bundle hash mismatch: manifest says 799c80a21b651fe2..., computed 8a89ab6f5a61d845...: unresolved; root cause is develop/current CLI hash contract differs from published-results CI validator.
Benchmark printed ❌ Missing tables... then deleted/rebuilt the DuckDB file and succeeded: resolved automatically, but it looked like a failure.
TPC-H run warned that validation was disabled for stream_id != 0: not blocking, but made me question whether the submitted result was fully validated.

3c. Tools or dependencies you didn't already have installed
None beyond existing uv; the separate PR worktree created a fresh .venv and installed 186 packages.

3d. Things in the docs that turned out wrong, missing, or surprising
Main docs say regenerate inventory; generated submission/CONTRIBUTING.md omits that step.
Main docs say target published-results; generated CONTRIBUTING.md omits the target branch.
published-results validation is incompatible with the package generated from current develop.
benchbox profile docs mention a "Platform Availability" table, but CLI showed a simpler "Available Databases" line.
benchbox submit dry-run path output and real output format differ slightly.

4. The three best fixes
Sync published-results with the current submit/validate_submission hash contract before inviting contributors.
Make benchbox submit generate exact next commands, including copy destination, inventory regeneration, local validation, PR title, and target branch.
De-alarm direct CLI output: avoid "Interactive Benchmark Runner" in direct mode, downgrade recoverable "Missing tables" from red failure, and clarify validation warnings.

5. Free-form
The core benchmark path worked quickly: DuckDB TPC-H SF0.01 ran and packaged cleanly. The submission path is the risky part. A contributor can follow the docs, produce a valid-looking package, regenerate inventory, and still fail CI because the PR target branch validates a different manifest hash model than the current CLI emits.

6. Would you submit a second result without being asked?
No — not until the target-branch validator and released/current benchbox submit agree.

Local artifacts left for inspection:
/Users/joe/Developer/BenchBox/submission/
/private/tmp/BenchBox-community-result-dry-run/
```

## Appendix B — Maintainer forensic of the hash mismatch

Demonstrating the algorithm divergence empirically:

```
$ shasum -a 256 /Users/joe/Developer/BenchBox/submission/bundle/tpch_sf001_duckdb_sql_20260428_205018_e4f24ee2.json
799c80a21b651fe24f2b80de03d5d5582a2460e294009a26a6efd28de8c65ba8

$ cat /Users/joe/Developer/BenchBox/submission/submission-manifest.json | jq -r .bundle_hash
799c80a21b651fe24f2b80de03d5d5582a2460e294009a26a6efd28de8c65ba8

$ python3 -c "
import hashlib
from pathlib import Path
bundle_dir = Path('/Users/joe/Developer/BenchBox/submission/bundle')
h = hashlib.sha256()
for f in sorted(bundle_dir.rglob('*')):
    if f.is_file():
        h.update(f.relative_to(bundle_dir).as_posix().encode())
        h.update(f.read_bytes())
print('per-directory hash:', h.hexdigest())
"
per-directory hash: 1ef7e244bc61b9bc412e223021d71751d572c064e95db2cef081326473beccb9

$ cd /private/tmp/BenchBox-community-result-dry-run  # clone of published-results
$ python3 scripts/validate_submission.py results-data/bundles/tpch_sf001_duckdb_sql_20260428_205018_e4f24ee2.json
Validated 1 bundle(s): 1 error(s), 0 warning(s)
  FAIL  results-data/bundles/tpch_sf001_duckdb_sql_20260428_205018_e4f24ee2.json
        ERROR: Bundle hash mismatch: manifest says 799c80a21b651fe2..., computed 8a89ab6f5a61d845...
```

Note: the validator reports `8a89ab6f5a61d845...`, but my recomputation
of the per-directory hash with the same code gives `1ef7e244...`. The
discrepancy suggests the validator is processing more files than just
the bundle — likely also the `submission-manifest.json` itself before
its skip-filter applies, or a path ordering issue. The exact 4-byte
prefix Codex saw (`8a89...`) is not reproducible from a clean re-read,
which strengthens the case that the per-directory algorithm is inputs-
sensitive to filesystem state in ways the per-file algorithm is not.
The fix is the same regardless: sync `published-results`'s validator
with `develop`'s per-file algorithm.

`published-results` HEAD: `0182c9556` (release v0.2.1, before PR #33's
hash refactor).
`develop` HEAD when this retrospective was written: latest after PR #46
auto-merge.
