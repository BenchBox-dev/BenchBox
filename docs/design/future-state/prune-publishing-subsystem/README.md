<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# artifactlinks Future State

```{tags} contributor, architecture
```

Related TODO: `prune-publishing-subsystem`

## Future State

This subsystem ends in one of two explicit states:

1. If the audit shows real reuse potential, generic artifact publishing and
   permalink creation move into `artifactlinks`.
2. If the audit shows no active supported use, BenchBox deletes the subsystem
   instead of carrying an unowned generic layer.

The important future state is that ambiguity disappears: the code is either a
real, owned library or it is gone.

## Why This Is Valuable

- BenchBox stops carrying generic infrastructure without clear ownership.
- If extraction is justified, the publishing surface becomes reusable and easier
  to maintain independently.
- If extraction is not justified, BenchBox gets simpler with minimal user cost.

## How The End State Is Used

Coupling analysis found zero consumers of the publishing module: no CLI
integration, no runtime imports, no result-export coupling. The expected outcome
is pruning rather than extraction.

If pruning is selected (expected), there is no replacement package. BenchBox
keeps only the result-export and artifact behavior that is part of supported
workflows. The result-export system (`benchbox/core/results/exporter.py`) is
completely independent and unaffected.

If future evidence of reuse emerges, extraction to a standalone package remains
possible because the module is self-contained.

## BenchBox After The Refactor

- Result export stays user-focused rather than carrying a generic publishing
  layer by default.
- Any retained publishing API has an explicit owner and documented consumer set.
- The package boundary reflects evidence rather than guesswork.

## Non-Goals

- Extracting a package just because the code looks reusable
- Preserving dead internal APIs with no supported user or maintainer
