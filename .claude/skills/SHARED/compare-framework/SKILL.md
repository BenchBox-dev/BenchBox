---
name: compare-framework
description: Compare two artifacts for semantic and behavioral equivalence.
---

# Compare Framework

Compare behavior, contracts, and relationships; do not compare wording alone.

## Workflow

1. Extract semantics from artifact A and B independently, preferably in parallel.
2. Normalize items, relationships, metadata, and confidence.
3. Compare exact matches, semantic equivalents, type mismatches, and unique items.
4. Score: primary items 40%, relationships 40%, structure 20%.
5. Report shared/unique items and warnings.

## Thresholds

| Score | Meaning |
|---|---|
| >=0.95 | Equivalent |
| 0.85-0.94 | Mostly equivalent; review |
| 0.70-0.84 | Significant differences |
| <0.70 | Breaking/not equivalent |

Breaking contract changes halve the score; lost critical relationships multiply by 0.7.

## Limits

Static comparison can miss runtime registration, reflection, external references, and behavior hidden behind indirection. Note confidence and any unverified assumptions.
