# Astro parity sign-off

Status: pending
Approval: pending

This record is the cutover gate for the Astro site. The cutover may not start
until the owner reviews the URL compatibility report below and replaces both
pending lines above with an approval. Nothing here is approved yet.

## How the report is produced

`make site-parity` builds the Sphinx site and the Astro site from one tree,
assembles the Sphinx site the way production does, and writes the URL
compatibility report to `site-parity/report/`. The CI job `site-parity` runs it
on every pull request that touches `docs/` or `website/`. The job is not a
required check. It uploads the report as the `url-compatibility-report`
artifact and copies it into the job summary.

The report covers:

- missing paths, lost anchors and fragments, changed titles and headings,
  broken internal links and missing images;
- tag pages, archives, series and categories, and generated query pages;
- Atom feed entry ids;
- the API URL map in `_project/design/site-inventory/api-reference-url-map.json`;
- axe over every page template, in light and dark themes;
- Explorer and DuckDB bytes on docs and blog pages;
- the privacy scan on the Astro output;
- a Pagefind smoke search.

Every redirect page and every allowed difference carries a reason and an owner
approval field. They live in `_project/design/site-inventory/`:
`allowed-differences.json`, `redirect-pages.json`, `added-paths.json` and the
`expected-removals-*.json` files. Their approval field reads `pending` until
the owner edits it.

## Report summary

The numbers below come from the last local `make site-parity` run, made on
top of parent commit `49fceef0678b65d004d0682b68a6b302822a154e` with the
changes that finished this harness. They are a record of that run only. The
SHA the owner approves is the one named in the `site-parity` CI report, which
records the pull request head, so the report SHA below stays pending until the
owner copies it from that run. Verdict of the local run: PASS.

| Measure | Value |
| --- | --- |
| Public paths in the Astro site | 4617 |
| Pages in the Astro site | 1903 |
| Broken public URLs | 0 |
| Broken fragments | 0 |
| Broken internal links beyond the known-broken list | 0 |
| Missing images | 0 |
| Lost Atom entry ids | 0 |
| Missing tag, archive and query pages | 0 |
| Missing API URL map pages and anchors | 0 |
| Sphinx objects inventory entries lost (2104 compared) | 0 beyond 2 allowed |
| Redirect pages | 4 |
| Page templates under `website/src/pages` plus content templates checked by axe | 21, light and dark |
| Axe failures | 0 |
| Remaining differences of any kind | 0 |

Public files kept at their Sphinx paths: 50 images under `/docs/_images/`, 183
downloads under `/docs/_downloads/` (same hashed directories), and a generated
`/docs/objects.inv`. The inventory lists pages, labels, blog post labels and
heading targets, and the report compares it entry by entry with the Sphinx
inventory. It has no Python object entries, because the authored API pages
replaced autodoc, and it omits the two module index labels.

Informational only: against the published baseline taken at an earlier
commit, some download paths, fragments and headings differ. They come from
docs edits made since the baseline and affect both renderers.

## Decisions for the owner

- Approve each redirect page in `redirect-pages.json`: the not-found
  fallback and the retired `/docs/genindex.html`, `/docs/search.html` and
  `/docs/blog.html`.
- Approve the expected removals in `expected-removals-sphinx-assets.json`: the
  Sphinx and Furo assets under `/_static/` and `/docs/_static/` (including a
  published Python module and its bytecode), `.buildinfo`, `searchindex.js`
  and the old landing page assets.
- Approve the two module index labels that the objects inventory omits, in
  `allowed-inventory-losses.json`.
- Approve the differences added beyond the earlier allowlist: the docs index
  title, the Footnotes heading, the headings on four generated index pages,
  the added canonical and description metadata, and the placeholder content of
  the redirect pages.

## Approval

- Owner approval: pending
- Approved by: pending
- Approval date: pending
- Report SHA: pending

## Re-run on the cutover base SHA

An approval holds only for the SHA it was given on. Before the cutover starts,
run `make site-parity` on the cutover base SHA, attach the new report, and
record the result here. A report that is not clean, or that was produced on a
different SHA, voids the approval.

- Cutover base SHA: pending
- Re-run result: pending
- Re-run approval: pending
