# ADR: Licensing Posture for the Recommended JOB Scale-Up Path

Date: 2026-06-30

Status: Pinned for `replicated_imdb` (the path recommended by
`_project/decisions/joinorder-scale-stress-decision-2026-06-30.md`).

This record pins the licensing posture for the recommended derived scale-up path
so future archive publishers do not have to re-derive the analysis. It is scoped
to `replicated_imdb` (offset replication of the canonical IMDb-2013 archive). It
inherits, and does not supersede, the canonical foundation's redistribution
review (`joinorder-canonical-data-licensing-2026-05-12`).

## Posture

Posture: **inherited (ambiguous upstream)** — not independently cleared.

`replicated_imdb` is a deterministic, mechanical transformation (integer offset
replication of rows and keys) of the canonical IMDb-2013 Parquet archive. It adds
no new source data. Because the derived archive contains only duplicated canonical
rows, it inherits the canonical archive's redistribution posture: the upstream
IMDb terms limit the data to personal/non-commercial use, the Harvard Dataverse
deposit is CC0 1.0, and CC0 does not override IMDb's retained rights. The
transformation is **not material** to the licensing question (it does not launder
the upstream terms), so redistribution of `replicated_imdb` carries the same
residual risk that the project owner already accepted for canonical `joinorder`.

If a future scale-up path adds genuinely new synthesized data (e.g.
`expanded_imdb` profiled graph expansion or a fully `synthetic_schema`
generator), that path requires a fresh licensing review with its own
`DATA-LICENSE.md` provenance trail and is out of scope for this record.

Statistics/analyze-phase blocker: this derived path is **represented by a new
TODO that the prototype must depend on** — `track2-joinorder-stats-phase`
(seeded by `joinorder-track2-groundwork` w2). The `replicated_imdb` prototype
must not claim publication-quality statistics-maintenance conclusions until that
dependency is satisfied; it may run earlier only under an explicitly narrowed,
smoke-only scope.

## Attribution

Required attribution and disclaimers for any published `replicated_imdb` archive:

- Cite the Harvard Dataverse DOI `10.7910/DVN/2QYZBT` and the source canonical
  `dataset_version` the replica was derived from.
- Attribute IMDb as the upstream data source and reproduce the upstream
  non-commercial framing.
- State that the dataset is a BenchBox-generated **derived** replica, not
  canonical JOB and not comparable to the JOB literature.
- Carry the generator version, replica count (scale factor), and seed so the
  transformation is reproducible.

## Hosting model

Hosting model: **GitHub Release (BenchBox-owned) with a user-supplied BYO path**.

- Default: a BenchBox-owned GitHub Release asset (same model as canonical
  `joinorder`), integrity-verified by SHA256 manifest, staged as DRAFT and
  promoted only after UAT.
- Alternative: a documented BYO path letting users generate the replica locally
  from their own canonical archive, for environments requiring stricter
  redistribution separation. Because `replicated_imdb` is deterministic from the
  canonical archive + (scale factor, seed), the BYO path is fully reproducible and
  needs no separate hosted asset.

## Takedown contact

Takedown contact inherits from the canonical foundation record unchanged: route
takedown or licensing concerns through the same project-owner contact and process
documented for canonical `joinorder` redistribution
(`joinorder-canonical-data-licensing-2026-05-12`). This record does not introduce
a separate contact; if the canonical contact changes, that change propagates here
by reference.
