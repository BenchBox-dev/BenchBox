# BenchBox `published-results`

This is the **slim, corpus-only branch** of
[`joeharris76/BenchBox`](https://github.com/joeharris76/BenchBox). It carries
only the files needed to receive, validate, and host the public results
corpus consumed by the BenchBox results explorer.

For the BenchBox project itself — the benchmark engine, platform adapters,
documentation, blog, results explorer source — see the
[`develop`](https://github.com/joeharris76/BenchBox/tree/develop) and
[`main`](https://github.com/joeharris76/BenchBox/tree/main) branches.

## What lives here

| Path | Purpose |
| --- | --- |
| `results-data/bundles/` | The corpus: schema-v2 result bundle JSONs and per-bundle `<stem>.manifest.json` sidecars. |
| `results-data/corpus-inventory.json` | Generated inventory index, regenerated on every submission. |
| `results-data/README.md` | Corpus structure, trust labels, layout guide. |
| `results-data/CORPUS_NOTES.md` | Per-cohort curation notes. |
| `results-data/SEED_CORPUS_SPEC.md` | Maintainer-run seed lane spec. |
| `results-data/validate_corpus.py` | The cohort-depth gate (≥3 platforms per cohort). |
| `scripts/validate_submission.py` | Per-bundle schema, hash, and contract validator (vendored from develop). |
| `scripts/generate_corpus_inventory.py` | Inventory generator (vendored from develop). |
| `.github/workflows/validate-submission.yml` | The submission CI gate. |
| `LICENSE`, `COPYRIGHT.md`, `DISCLAIMER.md` | Standard public-repo legal docs. |
| `CONTRIBUTING.md` | How to submit a bundle to this branch. |

Anything outside the above is intentionally not on this branch. The
slim shape is the design intent documented in
[`docs/development/adr/adr-published-results-slim-corpus-branch.md`](https://github.com/joeharris76/BenchBox/blob/develop/docs/development/adr/adr-published-results-slim-corpus-branch.md)
on `develop`.

## How to contribute

See [`CONTRIBUTING.md`](CONTRIBUTING.md) on this branch for the slim
quick-start, and
[`docs/contributing-results.md`](https://github.com/joeharris76/BenchBox/blob/develop/docs/contributing-results.md)
on `develop` for the full guide.

PRs whose diff touches files outside the allowlist will be redirected to
`develop`.

## Vendored validator scripts

`scripts/validate_submission.py` and `scripts/generate_corpus_inventory.py`
have their canonical home on `develop` and are vendored here so this
branch's CI can run without depending on the rest of the BenchBox source
tree. If you find a validator bug, fix it on `develop` first; the change
will be mirrored to this branch via the develop ↔ published-results sync
mechanism.

## License

[MIT](LICENSE).
