# TPC Logical Tuning Profiles

BenchBox uses a platform-neutral logical profile for checked-in TPC-H and
TPC-DS tuned templates. The profile lives at
`benchbox/core/tuning/profiles/tpc.yaml`; typed loading, capability mapping,
and template validation live under `benchbox/core/tuning/`.

The profile is the workload evidence source. Platform YAML files are consumers
of that profile, not independent sources of truth. A tuned Databricks run and a
tuned DuckDB run can therefore be compared by asking two separate questions:

- Did both runs request the same logical workload profile?
- Which physical mechanisms did each platform use to represent that profile?

## Logical Profile

Each candidate records:

- benchmark id: `tpch` or `tpcds`
- table and column in canonical all-caps form
- SQL type
- bounded logical roles such as `temporal_partition`, `join_locality`,
  `high_selectivity_filter`, `fact_dimension_join`, `group_order_locality`, and
  `distribution_candidate`
- query evidence: count, query ids, evidence source, acceptance status, and
  rationale

Statuses:

- `existing_baseline`: already present before the recovered TPC tuning audit
- `accepted`: added from query-template evidence
- `dropped_low_evidence`: intentionally excluded unless future evidence changes

Dropped candidates are part of the profile so they cannot silently reappear in a
checked-in template.

## Platform Mapping

Logical parity does not require identical physical features.

| Platform | Logical roles | Physical mapping |
| --- | --- | --- |
| Databricks | temporal locality | `partitioning` |
| Databricks | joins, filters, group/order locality | `clustering`, consumed by Z-ORDER or liquid clustering paths |
| Databricks | distribution candidates | `clustering` plus `distribution` hints |
| DuckDB | temporal locality | `partitioning` hints in unified tuning |
| DuckDB | joins, filters, group/order locality, distribution candidates | `sorting` / sorted layout |
| BigQuery | temporal locality | partitioning when column shape is supported |
| BigQuery | joins, filters, group/order locality | clustering, with the four-column limit explicit |
| Redshift | distribution candidates | dist-key decisions, limited to a single key |
| Redshift | locality candidates | sort-key decisions |
| Snowflake | locality candidates | clustering keys where useful |
| Snowflake | distribution candidates | unsupported; no user-managed distribution key |

Platforms without a meaningful physical mechanism must return a structured
unsupported or waived decision. They must not be reported as fully mapped.

## Current TPC Template Matrix

| Platform | Benchmark | Template | Partitioning | Clustering | Sorting | Distribution |
| --- | --- | --- | --- | --- | --- | --- |
| Databricks | TPC-H | `examples/tunings/databricks/tpch_tuned.yaml` | `LINEITEM.L_SHIPDATE`; `ORDERS.O_ORDERDATE` | `LINEITEM.L_ORDERKEY,L_PARTKEY,L_SUPPKEY`; `ORDERS.O_ORDERKEY,O_CUSTKEY`; `PART.P_PARTKEY,P_TYPE,P_SIZE`; `SUPPLIER.S_SUPPKEY,S_NATIONKEY`; `CUSTOMER.C_CUSTKEY,C_NATIONKEY`; `PARTSUPP.PS_PARTKEY,PS_SUPPKEY` | none | `LINEITEM.L_ORDERKEY`; `ORDERS.O_ORDERKEY`; `PART.P_PARTKEY`; `SUPPLIER.S_SUPPKEY`; `CUSTOMER.C_CUSTKEY`; `PARTSUPP.PS_PARTKEY` |
| DuckDB | TPC-H | `examples/tunings/duckdb/tpch_tuned.yaml` | `LINEITEM.L_SHIPDATE`; `ORDERS.O_ORDERDATE` | none | `LINEITEM.L_ORDERKEY,L_LINENUMBER,L_PARTKEY,L_SUPPKEY`; `ORDERS.O_ORDERKEY,O_CUSTKEY`; `PART.P_PARTKEY,P_TYPE,P_SIZE`; `SUPPLIER.S_SUPPKEY,S_NATIONKEY`; `CUSTOMER.C_CUSTKEY,C_NATIONKEY`; `PARTSUPP.PS_PARTKEY,PS_SUPPKEY` | none |
| Databricks | TPC-DS | `examples/tunings/databricks/tpcds_tuned.yaml` | `STORE_SALES.SS_SOLD_DATE_SK`; `STORE_RETURNS.SR_RETURNED_DATE_SK`; `CATALOG_SALES.CS_SOLD_DATE_SK`; `CATALOG_RETURNS.CR_RETURNED_DATE_SK`; `WEB_SALES.WS_SOLD_DATE_SK`; `WEB_RETURNS.WR_RETURNED_DATE_SK` | `STORE_SALES.SS_ITEM_SK,SS_CUSTOMER_SK,SS_STORE_SK,SS_PROMO_SK,SS_TICKET_NUMBER`; `STORE_RETURNS.SR_ITEM_SK,SR_CUSTOMER_SK,SR_STORE_SK,SR_TICKET_NUMBER`; `CATALOG_SALES.CS_ITEM_SK,CS_SHIP_MODE_SK`; `CATALOG_RETURNS.CR_ITEM_SK`; `WEB_SALES.WS_ITEM_SK,WS_WEB_PAGE_SK,WS_WEB_SITE_SK,WS_SHIP_MODE_SK`; `WEB_RETURNS.WR_ITEM_SK`; `DATE_DIM.D_DATE_SK,D_YEAR,D_MOY`; `ITEM.I_ITEM_SK,I_CATEGORY,I_CLASS`; `CUSTOMER.C_CUSTOMER_SK,C_CURRENT_ADDR_SK,C_CURRENT_CDEMO_SK` | none | `STORE_SALES.SS_ITEM_SK`; `STORE_RETURNS.SR_ITEM_SK`; `CATALOG_SALES.CS_ITEM_SK`; `CATALOG_RETURNS.CR_ITEM_SK`; `WEB_SALES.WS_ITEM_SK`; `WEB_RETURNS.WR_ITEM_SK`; `DATE_DIM.D_DATE_SK`; `ITEM.I_ITEM_SK`; `CUSTOMER.C_CUSTOMER_SK` |
| DuckDB | TPC-DS | `examples/tunings/duckdb/tpcds_tuned.yaml` | `STORE_SALES.SS_SOLD_DATE_SK`; `STORE_RETURNS.SR_RETURNED_DATE_SK`; `CATALOG_SALES.CS_SOLD_DATE_SK`; `CATALOG_RETURNS.CR_RETURNED_DATE_SK`; `WEB_SALES.WS_SOLD_DATE_SK`; `WEB_RETURNS.WR_RETURNED_DATE_SK` | none | `STORE_SALES.SS_ITEM_SK,SS_CUSTOMER_SK,SS_STORE_SK,SS_PROMO_SK,SS_TICKET_NUMBER`; `STORE_RETURNS.SR_ITEM_SK,SR_CUSTOMER_SK,SR_STORE_SK,SR_TICKET_NUMBER`; `CATALOG_SALES.CS_ITEM_SK,CS_SHIP_MODE_SK`; `CATALOG_RETURNS.CR_ITEM_SK`; `WEB_SALES.WS_ITEM_SK,WS_WEB_PAGE_SK,WS_WEB_SITE_SK,WS_SHIP_MODE_SK`; `WEB_RETURNS.WR_ITEM_SK`; `DATE_DIM.D_DATE_SK,D_YEAR,D_MOY`; `ITEM.I_ITEM_SK,I_CATEGORY,I_CLASS`; `CUSTOMER.C_CUSTOMER_SK,C_CURRENT_ADDR_SK,C_CURRENT_CDEMO_SK` | none |

The checked-in validator enforces this profile for Databricks and DuckDB:

```bash
uv run -- python _project/scripts/tuning_profile_check.py --benchmarks tpch,tpcds --platforms databricks,duckdb --strict
```

## Result Metadata

When a TPC tuned template is applied, result execution metadata includes
`tuning_profile` with:

- `logical_tuning_profile_id`
- `logical_tuning_profile_version`
- `tuning_template_hash`
- `platform_physical_tuning_mechanisms`
- `logical_profile_coverage`
- `unmapped_logical_candidates`
- `validation_status`

The companion tuning payload also includes `logical_profile`, and the platform
tuning summary includes the profile id, version, template hash, coverage, and
physical mechanisms.

## Comparison Semantics

Treat `tuning_mode == "tuned"` as a request for a logical profile, not as proof
of identical storage layout. Databricks may represent a locality candidate with
Delta clustering/Z-ORDER behavior, while DuckDB represents the same logical
candidate through sort layout. That is a comparable logical intent with
different physical execution costs and maintenance tradeoffs.

Do not compare a fully mapped tuned template to a basic-constraints fallback as
if both are equivalent. The fallback means BenchBox could not find a
benchmark-specific tuned template for that platform/benchmark cell; result
consumers should treat that as a coverage gap unless the cell has an explicit
waiver.
