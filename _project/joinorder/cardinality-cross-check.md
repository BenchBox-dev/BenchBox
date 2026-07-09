# JoinOrder Cardinality Cross-check

The Leis et al. 2015 JOB paper and the commonly mirrored JOB companion materials publish optimizer
error distributions and the canonical query text, but not a complete stable table of per-query
answer-set cardinalities for all 113 aggregate queries.

BenchBox therefore treats the PostgreSQL run captured in
`_project/joinorder/reference_cardinalities.json` as the authoritative oracle for this dataset
build. The oracle is tied to the Harvard Dataverse pg_dump SHA256, the gregrahn query commit,
the data manifest hash, and PostgreSQL version recorded in that JSON file.

Computed oracle coverage: 113/113 queries.

Traceable published per-query row counts found: none.
