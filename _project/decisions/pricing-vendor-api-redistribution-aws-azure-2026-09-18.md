# ADR: Vendor Pricing API Data Redistribution (AWS Price List, Azure Retail Prices)

Date: 2026-09-18

Status: Accepted project-owner redistribution risk; optional hardening follow-up

## Question

May BenchBox redistribute derived price values pulled from the AWS Price List
API (`pricing.us-east-1.amazonaws.com/offers/v1.0/aws/...`) and the Azure
Retail Prices API (`prices.azure.com/api/retail/prices`) inside the
`pricing_data.yaml` file that ships in the runtime wheel and in the repo?

Both APIs are public and unauthenticated, which is suggestive but not
dispositive. This decision settles the question before generator work starts
pulling values from vendor APIs into that file. It does not cover the separate
data-correction work: hand-transcribing a published list price into a config
file is a different act from automatically mirroring a vendor's price feed.

## Determination

Neither vendor's published terms expressly permit BenchBox to redistribute
derived price values, and both vendors' closest governing terms lean
restrictive (personal/non-commercial use, no copying or redistribution of
obtained information or site contents without written consent).

BenchBox will nevertheless ship a small set of derived price values with
per-value provenance in `pricing_data.yaml` in both the wheel and the repo.
This is an explicit project-owner risk acceptance, not a conclusion that the
redistribution question is fully cleared.

Scope of this determination: it covers redistribution in the wheel and in the
repo alike. There is no meaningful distinction between the two for this file:
the wheel ships the same vendored values the repo holds, so a clearance that
covered only one would be incoherent. Bulk mirroring of either vendor's price
catalog is not covered; only a small set of individually selected derived
values with recorded provenance is.

## Evidence Digest

Retrieved on 2026-09-18.

| Source | Evidence | Impact |
|---|---|---|
| AWS Price List Bulk API user guide, `https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-the-aws-price-list-bulk-api.html` | Documents programmatic download of price list files from `pricing.us-east-1.amazonaws.com/offers/v1.0/aws/...` (unauthenticated bulk files) for consuming large amounts of product and pricing information. | Confirms the endpoint is published for programmatic consumption, but the guide grants no redistribution license. |
| AWS Site Terms, `https://aws.amazon.com/terms/` | Grants only a limited license to access and make personal use of the AWS Site: the license "does not include any resale or commercial use of the AWS Site or its contents; any derivative use of the AWS Site or its contents", nor "any use of data mining, robots, or similar data gathering and extraction tools". The Site "may not be reproduced, duplicated, copied, sold, resold ... or otherwise exploited for any commercial purpose without express written consent or license of AWS." | The closest published AWS terms for unauthenticated reads lean against commercial redistribution and automated extraction; no separate price-data license was found. |
| Azure Retail Prices REST API overview, `https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices` | Describes an unauthenticated API to "get retail prices for all Azure services" and to "explore prices ... against different regions and different SKUs", framing the programmatic API as help to "create your own tools for internal analysis and price comparison across SKUs and regions". | Confirms the endpoint is published for programmatic use, framed around internal analysis; grants no redistribution license. |
| Microsoft Terms of Use, `https://www.microsoft.com/en-us/legal/terms-of-use` (last updated 2022-02-07) | Covers services provided through Microsoft's "network of Web properties", including "developer tools ... and product information" (collectively "Services"). "Unless otherwise specified, the Services are for your personal and non-commercial use. You may not modify, copy, distribute, transmit, display, perform, reproduce, publish, license, create derivative works from, transfer, or sell any information, software, products or services obtained from the Services." | The closest published Microsoft terms for unauthenticated reads prohibit redistributing obtained information; no separate retail-prices license was found. |

## Rationale

The strongest permissive facts are that both endpoints are deliberately
published for unauthenticated programmatic access, that BenchBox would
redistribute only a small number of individually selected scalar values
rather than a mirrored feed or bulk republication of either catalog, and that
individual list prices are factual data points rather than expressive vendor
content. The vendors publish these endpoints precisely so third parties can
build pricing tooling, and the practical enforcement risk of redistributing a
handful of attributed list prices in an open-source benchmark config is low.

The restrictive facts cut the other way. Neither vendor grants an express
redistribution right for these endpoints, and both vendors' closest published
terms limit use to personal/non-commercial purposes and prohibit copying or
redistributing obtained information or site contents without written consent.
Unauthenticated access means no click-through agreement is affirmatively
accepted at fetch time, but that absence of contract formation is not a
permission either. Prices also change continuously, so any vendored value is a
stale snapshot the moment it is recorded, which is a correctness risk on top
of the terms risk. Because BenchBox would ship vendor-derived values in a
widely distributed wheel and repo, the safe engineering conclusion is that
this redistribution path is not clearly permitted.

This ADR is not legal advice. It is an engineering release-risk decision based
on published terms and the project owner's judgment, following the shape of
the JoinOrder canonical-data decision (`joinorder-canonical-data-licensing-2026-05-12.md`).

## Accepted Path And Optional Remediation

Ship derived values under this risk acceptance subject to these guardrails,
which keep the exposure to a small set of attributed facts rather than a
vendor feed mirror:

1. Vendor only individually selected scalar values, with the retained
   provenance needed to identify the source API, selected region, currency,
   and retrieved or effective date. Where a provider exposes a stable SKU or
   meter identifier, retain it with the value; the current regional tables do
   not claim per-value identifiers that the source does not expose. Never
   vendor bulk snapshots of either catalog.
2. Keep vendor attribution and the residual-risk disclosure in the data file
   header and user-facing docs, alongside the other pricing provenance.
3. Treat vendored values as stale-by-default: the generator and cost paths
   must handle refresh and staleness rather than trusting vendored values
   indefinitely. Unknown per-table retrieval dates remain unavailable for
   normalized publication.

Optional hardening remains useful, but it is not a generator blocker:

1. Seek written permission from AWS and Microsoft covering redistribution of
   derived list prices in an open-source benchmark wheel and repo.
2. Switch the generator to fetch-at-build (or fetch-at-run) with no vendored
   values, if the staleness or terms posture ever requires a design without
   BenchBox redistribution.
3. Prefer linking to the vendor endpoints and documenting the lookup over
   vendoring values wherever a value does not need to ship for offline or
   deterministic runs.

## Consequences

- Generator work that pulls values from the AWS Price List API and the Azure
  Retail Prices API into `pricing_data.yaml` is unblocked under this accepted
  risk.
- `pricing_data.yaml` may ship in the runtime wheel and in the repo with
  small-scale derived vendor values plus per-value provenance; bulk vendoring
  stays out of scope until a separate determination.
- Per-value provenance records in `pricing_data.yaml` and user-facing docs
  must disclose the vendor sources, retrieval dates, and the fact that
  BenchBox is accepting residual redistribution risk rather than declaring
  redistribution cleared. (No cost-module `DATA-LICENSE.md` exists yet; if
  one is created it inherits this duty.)
