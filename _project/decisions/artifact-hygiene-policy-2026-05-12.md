# Artifact Hygiene Policy - 2026-05-12

## Decision

BenchBox treats raw review evidence as temporary unless it has a durable
repository consumer. Commit markdown/TODO summaries, not raw screenshot batches,
browser reports, verification logs, or generated binary evidence.

## Rationale

The Results Explorer review wave committed large screenshot matrices under
`_project/audits/screenshots/`. Those images were useful during PR review, but
the durable information is the checked SHA, route, viewport, observed behavior,
finding ID, and remediation decision already captured in audit markdown.

The retained verification logs were smaller, but they created the same failure
mode: future agents learned to commit stdout transcripts even when a compact
summary would preserve the meaningful evidence.

## Evidence

A GitHub PR-file scan on 2026-05-12 found 67 of 364 merged PRs with suspect
temporary evidence under `_project/`. The highest-volume examples were:

| PR | Temporary evidence files | Total files | Pattern |
|---|---:|---:|---|
| #334 | 101 | 109 | recaptured Results Explorer screenshots and logs |
| #269 | 48 | 81 | Results Explorer retheme screenshot evidence |
| #335 | 41 | 46 | PR246 final evidence screenshots |
| #246 | 40 | 47 | hierarchy usability screenshot matrix |
| #263 | 33 | 38 | retheme release-readiness screenshots |
| #371 | 14 | 17 | release-gate stdout logs |

The current-tree cleanup removes 384 tracked evidence files, including 241
binary deletions, for 46.1 MiB removed from the checked-out tree. This does not
remove historical blobs from existing packfiles; that requires the coordinated
history rewrite described below.

## Storage Classes

| Evidence | Git policy | Storage |
|---|---|---|
| Audit conclusions and finding tables | Commit | `_project/audits/*.md` |
| TODO guardrails and work summaries | Commit | `_project/TODO/**`, `_project/DONE/**` |
| Full screenshot batches | Do not commit | CI artifacts, `/tmp`, or `BENCHBOX_OUTPUT_DIR` |
| Browser reports and test results | Do not commit | CI artifacts |
| Raw stdout logs | Do not commit by default | `/tmp`, CI artifacts, or `BENCHBOX_OUTPUT_DIR` |
| Product docs/blog images | Commit case-by-case | `docs/**`, `_blog/**` |
| Small test fixtures | Commit when needed | `tests/fixtures/**` |

## Enforcement

`_project/scripts/artifact_hygiene_check.py` blocks tracked temporary evidence
under `_project/audits/screenshots/`, `_project/verification-logs/`, and
binary/log-like files under `_project/`. The develop PR workflow and local
`make ci-lint` run the check.

## Cleanup Strategy

This policy first removes ephemeral artifacts from the current `develop` tree.
That reduces checkout and archive size without rewriting shared history.

History rewrite remains a separate administrative action. Use it only if the
remaining historical clone cost is worth a coordinated disruption:

```bash
git clone --mirror git@github.com:joeharris76/BenchBox.git BenchBox-rewrite.git
cd BenchBox-rewrite.git
git filter-repo --invert-paths \
  --path _project/audits/screenshots \
  --path _project/verification-logs \
  --path-glob '_project/audits/**/*.png' \
  --path-glob '_project/**/*.log'
git count-objects -vH
git push origin --force --all
git push origin --force --tags
```

Before rewriting: freeze merges, close or rebase open PRs, preserve a read-only
backup mirror, confirm branch-protection settings, and tell developers to
reclone or hard-reset after the force-push.
