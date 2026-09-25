# ADR: Prove FlightData source months before reusing a corpus

- Status: Accepted
- Date: 2026-09-24
- Constrains: FlightData generation, manifest reuse, and result provenance.

## Context

FlightData uses monthly BTS archives. A failed download at scale factors of
0.1 or greater previously generated synthetic rows silently. A corpus could
therefore contain both remote and synthetic months, while its manifest and
result bundle did not identify the substituted months. The runner could also
reuse the corpus directly from its manifest without calling the downloader.

## Decision

At scale factors of 0.1 or greater, a monthly download failure stops
generation by default. Synthetic fallback requires the explicit
`allow_synthetic_fallback` benchmark option. Smaller scale factors retain
their documented synthetic generation behavior.

The manifest records the exact downloaded and synthetic month lists and their
counts. The source contract includes the fallback policy, so switching that
policy changes the corpus identity. Both the runner and direct downloader
reject cached data unless the manifest partitions the expected window into
those two complete, disjoint lists. A result bundle includes the source
provenance only when the run established its link to a verified manifest.

## Consequences

Older FlightData caches lack complete month evidence and require regeneration.
Real-only runs stop when a required BTS archive is unavailable; the scale
factor is not silently redefined and synthetic rows are not mislabeled as
remote data. Explicit fallback runs remain identifiable as mixed or synthetic.
