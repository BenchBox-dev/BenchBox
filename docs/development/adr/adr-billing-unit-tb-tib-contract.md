# ADR: Scan billing units — decimal terabytes for Athena/Synapse, tebibytes for BigQuery

- Status: Accepted
- Date: 2026-09-18
- Constrains: `NormalizedCost.billing_unit` values, the `units` block in `benchbox/core/cost/pricing_data.yaml` and the `BYTES_PER_UNIT` divisors in `benchbox/core/cost/calculator.py`, the `NORMALIZED_COST_BILLING_UNITS` vocabulary in `benchbox/validation/bundle.py`, the result-bundle schema version policy (no bump), and BigQuery free-tier modeling (none, disclosed).

## Context and Motivation

The pricing-provenance work deliberately encoded the Athena and Synapse
serverless byte divisor as `terabyte_unconfirmed`: both vendors print a bare
"TB" for data scanned/processed, and neither publishes whether that TB is
10^12 or 2^40 bytes. Google is settled — BigQuery bills per TiB — but the
public `NormalizedCost` contract still reported a single `tb_scanned` unit for
all three scan-priced platforms, asserting a unit the code did not use for
BigQuery. This ADR settles the divisor, fixes the contract values, and
discloses the one related modeling choice (the BigQuery free tier) that was
previously silent.

Vendor evidence gathered 2026-09-18:

- **AWS Athena** prints "$5.00 per TB of data scanned"
  ([pricing page](https://aws.amazon.com/athena/pricing/)). Its worked
  example equates S3 file-size TB with billed TB (3 TB scanned = 3 x $5),
  which is self-consistent under either divisor, so it does not settle the
  byte count. The Price List API names the usage type
  `USE1-DataScannedInTB` (bare "TB", no divisor). Rounding is to the nearest
  megabyte with a 10 MB minimum per query.
- **Azure Synapse serverless** is "charged by the TB of data processed"
  ([cost-management doc](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/data-processed)),
  rounded up to the nearest MB per query with a 10 MB minimum. The Retail
  Prices API meter "Standard Data Processed" carries
  `unitOfMeasure: "1 TB"` (bare "TB", no divisor).
- **Google BigQuery** prices "On-demand (per TiB)" and works its example as
  billed-bytes / 1099511627776
  ([pricing page](https://cloud.google.com/bigquery/pricing)). 2^40 is
  confirmed for BigQuery only.

The tiebreaker is the printed unit itself. Under SI/IEEE 1541, "TB" means
10^12 bytes and 2^40 bytes is "TiB" — and Google's deliberate "TiB" plus an
explicit 2^40 divisor shows vendors write "TiB" when they mean 2^40. AWS and
Azure wrote "TB", so BenchBox reads 10^12.

A second, previously undisclosed choice: BenchBox charges the BigQuery
on-demand list rate from byte zero and does not model the first 1 TiB per
month free tier (same Google pricing page: "The first 1 TiB of query data
processed per month is free"). That is the right call for cross-platform
comparability — a monthly account-level credit cannot be attributed to one
benchmark run — but most benchmark runs scan under 1 TiB, so a reader could
reasonably expect zero. It must be documented, not just decided.

## The Decision

1. **Athena and Synapse serverless bill in decimal terabytes.**
   `pricing_data.yaml` declares `terabyte` for both tables and
   `BYTES_PER_UNIT["terabyte"]` is 10^12. Computed Athena/Synapse costs rise
   by x(2^40/10^12) = ~9.95% versus the old 2^40 divisor, which understated
   them under this reading.
2. **`billing_unit` reports the unit actually billed per platform.**
   BigQuery emits `tib_scanned`; Athena and Synapse serverless keep
   `tb_scanned`, which now explicitly means decimal TB. All other platform
   values are unchanged.
3. **No result-bundle schema bump beyond 2.2.** No new top-level
   `NormalizedCost` field is added; the change extends the `billing_unit`
   value domain by one value (`tib_scanned`) while keeping the old BigQuery
   value (`tb_scanned`) in the validator vocabulary, so previously published
   bundles still validate. A value-domain extension with backward-compatible
   validation is drift, not breakage.
4. **No BigQuery free-tier modeling, disclosed.** The cost README and the
   calculator docstring now state that list rate applies from byte zero.
5. **Residual exposure is bounded and stated.** If either vendor actually
   means 2^40, BenchBox overstates that platform by ~9.95% (the mirror of
   the old understatement). Absolute exposure is small: benchmark scans are
   MB-to-GB scale, so the disputed band is cents per run. The bundle
   validator now enforces the closed `billing_unit` vocabulary, so any
   future per-vendor correction is a data change, not a contract repair.

## Rejected Alternatives

### 1. Keep 2^40 for Athena and Synapse

Keeping the historical divisor would preserve number stability, but it reads
a bare "TB" as "TiB" against the SI definition with no vendor text
supporting the binary reading — while Google's explicit "TiB" shows what a
binary reading looks like when a vendor means it. Stability is not a reason
to keep a known-likely understatement.

### 2. Stay inconclusive and keep the `terabyte_unconfirmed` marker

Recording the attempt as inconclusive with stated exposure was the allowed
fallback, but a cost calculator must divide by something, and an
"unconfirmed" marker in the shipped pricing table leaves every downstream
number carrying an unresolved qualifier. The evidence supports a decision
(decimal TB), with the residual uncertainty bounded above instead of left
open.

### 3. Model the BigQuery 1 TiB monthly free tier

Subtracting free-tier credit per run would make BenchBox numbers match one
specific Google bill shape, at the cost of cross-platform comparability:
the credit is monthly, account-level, and shared across all workloads, so
no per-run attribution is principled. Rejected in favor of list-rate-from-
byte-zero, disclosed.

### 4. Bump the result-bundle schema to 2.3 for the new unit value

A version bump signals that old readers may fail on new bundles. They will
not: the only structural change is one additional accepted string in an
existing field, and old `tb_scanned` values remain valid. Bumping would
force needless migration for zero reader benefit.

### 5. Rename `tb_scanned` to `terabyte_scanned` for symmetry with `tib_scanned`

A rename would state the decimal meaning more loudly, but it would
invalidate every previously published Athena/Synapse bundle for no
computational gain, contradicting decision 3. The README and this ADR pin
the meaning of `tb_scanned` instead.

## Consequences

- Positive: the public contract states the unit the code bills; the
  unconfirmed marker is gone; the free-tier choice is disclosed; the bundle
  validator rejects fictional units for normalized cost.
- Neutral: Athena/Synapse estimates rise ~9.95%; historical bundles keep the
  version stamped at export (per existing pricing-version policy) and still
  validate.
- Negative: if a vendor means 2^40, BenchBox overstates by ~9.95% until
  corrected — bounded, disclosed, and a one-line data change to fix.
