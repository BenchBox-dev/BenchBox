---
date: 2026-08-15
develop_sha: e03c75382be312c1368ef98fd53f1e5ac68fe4bc
measured_at_sha: e03c75382be312c1368ef98fd53f1e5ac68fe4bc
checked_sha: e03c75382be312c1368ef98fd53f1e5ac68fe4bc
verdict: green
---

# Blog and historical release-language audit — 2026-08-15

## Verdict

**Green after follow-up corrections.** The initial audit missed two issues:
the v0.1.3 extra-install examples were unsafe under default zsh glob handling,
and the source/docs comparison understated substantive content differences.
Both issues are corrected in this follow-up; the remaining Alpha references
are explicitly historical.

## Evidence inputs

| Surface | Checked contract |
|---|---|
| `pyproject.toml` | version `0.3.1`; `Development Status :: 4 - Beta` |
| `README.md` | current release `v0.3.1`; current extras and installation guidance |
| `docs/usage/installation.md` | current `uv add` and `uv pip install` forms |
| `benchbox/cli/commands/download_answers.py` | `download-answers` supports `tpch`, `tpcds`, and `all` |
| `docs/blog/*.md` and `_blog/building-benchbox/published/*.md` | 27 tracked public prose files |

## Classification

- The four Alpha matches are confined to the v0.2.0 historical release
  summary and its v0.2.1 backlink. They describe the Alpha-to-Beta transition
  in that release and do not claim that the current project is Alpha.
- The v0.1.3 optional-extra commands are release-specific upgrade guidance;
  the extras still exist in the current package, and both maintained copies now
  quote the bracketed requirement strings for zsh-safe use.
- The v0.2.0 `download-answers` examples remain valid. The current CLI still
  supports both named benchmarks and `all`, including offline cache priming.
- The v0.3.0 DuckDB examples use the current `uv add` extra syntax. The
  standalone `textcharts` installation example belongs to that separate
  package-extraction post and is not BenchBox installation guidance.
- The source and docs copies share the release content but are not path-only
  clones: relative image/companion-post paths differ, and the docs copy carries
  a current JoinOrder behavior note that the historical source copy does not.

## Decision

The follow-up corrected the two missed public-content issues in both maintained
v0.1.3 copies and in this audit record. This audit is the durable result; future
release-language changes should rerun the same inventory against
`pyproject.toml`, `README.md`, and the installation guide before editing
historical posts.

## Reproduction

```bash
rg -n -i '\balpha\b|pip install|uv add|download-answers|optional extras' \
  docs/blog _blog/building-benchbox/published
uv run -- benchbox --version
uv run -- benchbox download-answers --help
make docs-validate
```
