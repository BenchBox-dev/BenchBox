# JoinOrder Cardinality Cross-check

The Leis et al. 2015 JOB paper and the commonly mirrored JOB companion materials publish optimizer
error distributions and the canonical query text, but not a complete stable table of per-query
answer-set cardinalities for all 113 aggregate queries.

BenchBox therefore treats the PostgreSQL run captured in
`_project/joinorder/reference_cardinalities.json` as the authoritative oracle for this dataset
build. The oracle is tied to the Harvard Dataverse pg_dump SHA256, the gregrahn query commit,
the data manifest hash, and PostgreSQL version recorded in that JSON file.

Computed oracle coverage: 113/113 queries.

Each JOB query is an aggregate query that returns one row. The stored `first_row_sha256` value is
therefore a full aggregate-result oracle: it hashes PostgreSQL's `row_to_json(...)::text` output for
that row. Re-run `make joinorder-verify-reference-results JOINORDER_POSTGRES_CONTAINER=<container>`
against a restored PostgreSQL source to compare all 113 row counts, underlying row counts, and full
aggregate row hashes against the committed oracle.

Traceable published per-query row counts found: none.
