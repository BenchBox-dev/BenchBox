# Phase 2 Qualitative Request Log

Append-only log of Phase 2 user requests that map to Phase 3 promotion
metrics #4-#6 in
[`_project/analysis/phase-3-promotion-metrics.md`](../analysis/phase-3-promotion-metrics.md).

## Format

Append entries under the relevant section. Each entry must include:

- **Date** (YYYY-MM-DD)
- **Source** (issue #, PR #, Discord thread, email, in-conversation)
- **Requester** (handle or "anonymous"; do not log private contact info)
- **Summary** (one sentence)

`scripts/phase2_metrics.py` parses entries by counting distinct
**Requester** values per section over a configurable window.

## Private/Unlisted

Requests for results that are not publicly browsable (private to the
submitter, unlisted but linkable, or scoped to an organization).

_(none yet)_

## Blocked-Maintainer

Submissions blocked by constraints only a maintainer can resolve
(missing platform adapter, NDA-restricted hardware, schema-v2 fields
that need approval, etc.). This is *not* a place for "user got confused
by docs" — that goes into a different kind of follow-up.

_(none yet)_

## Org-Spaces

Requests for organization or team accounts: shared submission
namespace, group-level trust labels, multi-user attribution.

_(none yet)_
