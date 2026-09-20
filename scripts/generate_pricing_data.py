#!/usr/bin/env python3
"""Regenerate the vendor-derived pricing tables from checked-in vendor evidence.

The machine-readable prices in ``benchbox/core/cost/pricing_data.yaml`` come
from two places: hand-maintained tables (BigQuery, Snowflake, Firebolt,
Databricks AWS/GCP) and vendor-API-derived tables rendered by this script
from ``benchbox/core/cost/pricing_vendor_evidence.yaml``. That evidence file
records one vendor-native observation per emitted value -- source API, SKU or
meter identifier, region, currency, retrieval date -- and this script applies
the derivation rules (region-to-tier mapping, DWU linear scaling, the
``other`` bucket, tier-independent meter reuse) to render the BenchBox-shaped
tables. ``make pricing-data-check`` fails when the committed tables diverge
from what the evidence derives, so a hand edit to a generated value cannot
pass CI; the weekly ``Pricing Data Drift Check`` workflow re-pulls the vendor
APIs and surfaces upstream moves as a diff.

This follows the repo's regenerate-plus-check idiom (a default mode that
rewrites the artifact plus a ``--check`` mode that regenerates in memory and
exits non-zero on drift), but the artifact here is a subset of sections
inside one YAML file rather than whole files: each generated section is
delimited by ``BEGIN/END GENERATED <section>`` markers, and only the lines
between a marker pair are replaced. Everything else in the file --
hand-maintained tables, their provenance, comments -- is preserved
byte-for-byte.

Modes:

- ``scripts/generate_pricing_data.py`` regenerates the marked sections from
  the evidence file. Fully offline; safe to run anywhere.
- ``scripts/generate_pricing_data.py --check`` regenerates in memory and
  exits 1 with a unified diff when the committed file drifts. This is what
  ``make pricing-data-check`` and the ``guard-pricing-data`` CI step run.
- ``scripts/generate_pricing_data.py --refresh`` re-pulls the AWS Price List
  API and the Azure Retail Prices API, folds moved prices into the evidence
  file (unchanged prices keep their recorded retrieval date, so an unchanged
  upstream regenerates byte-identical output), then regenerates. Network only;
  runs on a schedule, never in the PR-blocking path. Refresh only revisits
  regions already recorded in the evidence file: a brand-new vendor region is
  not auto-discovered (consistent with the individually-selected-values
  license posture) and must be added to the evidence file by hand.

Redistribution of the emitted vendor-derived values ships under the accepted
project-owner risk recorded alongside the redistribution-check item, not
under a vendor grant: see the header of the evidence file.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import difflib
import json
import re
import sys
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COST_DIR = REPO_ROOT / "benchbox" / "core" / "cost"
EVIDENCE_PATH = COST_DIR / "pricing_vendor_evidence.yaml"
PRICING_PATH = COST_DIR / "pricing_data.yaml"

EVIDENCE_VERSION = 1
REQUEST_TIMEOUT_SECONDS = 60
USER_AGENT = "BenchBox-pricing-generator"

# Tables whose provenance is hand-maintained. Each must carry a
# ``manual_review_due`` ISO date; --check fails when one is missing or
# malformed. Generated tables are excluded: their freshness is enforced by
# the evidence retrieval dates plus the scheduled refresh instead.
MANUAL_TABLES = (
    "snowflake_credit_prices",
    "bigquery_on_demand_prices",
    "firebolt_node_fbu_rates",
    "firebolt_fbu_price",
    "databricks_dbu_prices",
)

# Emitted Redshift node-type columns, in file order, plus the derived bucket.
REDSHIFT_NODES = (
    "dc2.large",
    "dc2.8xlarge",
    "ra3.large",
    "ra3.xlplus",
    "ra3.4xlarge",
    "ra3.16xlarge",
    "rg.large",
    "rg.xlarge",
    "rg.4xlarge",
    "rg.12xlarge",
)

# Emitted Redshift region columns, in file order; `other` renders last and
# always carries the `other_from` region's observed value.
REDSHIFT_TABLE_COLUMNS = (
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-west-2",
    "eu-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1",
    "other",
)

# Synapse dedicated levels as (table key, DW100c multiplier), in file order.
DWU_LEVELS = (
    ("dw100c", 1),
    ("dw200c", 2),
    ("dw300c", 3),
    ("dw400c", 4),
    ("dw500c", 5),
    ("dw1000c", 10),
    ("dw1500c", 15),
    ("dw2000c", 20),
    ("dw2500c", 25),
    ("dw3000c", 30),
    ("dw5000c", 50),
    ("dw6000c", 60),
    ("dw7500c", 75),
    ("dw10000c", 100),
    ("dw15000c", 150),
    ("dw30000c", 300),
)

COST_TIERS = ("us", "eu", "ap", "ca", "other")
DATABRICKS_TIERS = ("standard", "premium")
DATABRICKS_WORKLOADS = (
    "all_purpose",
    "jobs",
    "sql_warehouse",
    "sql_classic",
    "sql_pro",
    "sql_serverless",
    "ml",
)

_AZURE_DATABRICKS = "Azure Databricks"
_AZURE_DATABRICKS_REGIONAL = "Azure Databricks Regional"

# Canonical (service, product, meter) backing every Azure Databricks cell.
# Tier-independent products (SQL Pro, Serverless SQL) exist only under the
# Regional product family, and ML runtime bills at the all-purpose rate, so
# several cells share one meter by design; the evidence file repeats the
# shared meter per cell and the renderer asserts the binding both ways.
DATABRICKS_CELL_METER: dict[tuple[str, str], tuple[str, str, str]] = {
    (tier, workload): meter
    for tier in DATABRICKS_TIERS
    for workload, meter in {
        "all_purpose": (_AZURE_DATABRICKS, _AZURE_DATABRICKS, f"{tier.title()} All-purpose Compute DBU"),
        "jobs": (_AZURE_DATABRICKS, _AZURE_DATABRICKS, f"{tier.title()} Jobs Compute DBU"),
        "sql_warehouse": (_AZURE_DATABRICKS, _AZURE_DATABRICKS, f"{tier.title()} SQL Analytics DBU"),
        "sql_classic": (_AZURE_DATABRICKS, _AZURE_DATABRICKS, f"{tier.title()} SQL Analytics DBU"),
        "sql_pro": (
            _AZURE_DATABRICKS,
            _AZURE_DATABRICKS_REGIONAL,
            "Premium SQL Compute Pro DBU",
        ),
        "sql_serverless": (
            _AZURE_DATABRICKS,
            _AZURE_DATABRICKS_REGIONAL,
            "Premium Serverless SQL DBU",
        ),
        "ml": (_AZURE_DATABRICKS, _AZURE_DATABRICKS, f"{tier.title()} All-purpose Compute DBU"),
    }.items()
}


class PricingGeneratorError(RuntimeError):
    """Fail-closed signal: the artifact must not be written on this path."""


def canonical_decimal(raw: str, *, min_places: int, max_places: int) -> str:
    """Render a decimal string in the canonical form the tables use.

    At most ``max_places`` fractional digits (a value needing more is a
    genuine precision change and raises instead of rounding silently), with
    trailing zeros stripped down to at least ``min_places`` digits, so
    ``0.3000000000`` renders as ``0.30`` under (2, 4) and API JSON ``0.4``
    renders as ``0.40`` under (2, 2).
    """
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise PricingGeneratorError(f"not a decimal: {raw!r}") from exc
    if not value.is_finite():
        raise PricingGeneratorError(f"not a finite decimal: {raw!r}")
    if value <= 0:
        raise PricingGeneratorError(f"not a positive rate: {raw!r}")
    quantum = Decimal(1).scaleb(-max_places)
    narrowed = value.quantize(quantum)
    if narrowed != value:
        raise PricingGeneratorError(
            f"value {raw!r} needs more than {max_places} decimal places; refusing to round silently"
        )
    text = format(narrowed.normalize(), "f")
    if "." not in text:
        text += "."
    head, _, tail = text.partition(".")
    if len(tail) < min_places:
        tail += "0" * (min_places - len(tail))
    return f"{head}.{tail}"


def load_evidence(path: Path = EVIDENCE_PATH) -> dict:
    """Load and structurally validate the vendor evidence file."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PricingGeneratorError(f"evidence file not found: {path}") from exc
    if not isinstance(payload, dict):
        raise PricingGeneratorError(f"evidence file must contain a mapping: {path}")
    if payload.get("meta", {}).get("evidence_version") != EVIDENCE_VERSION:
        raise PricingGeneratorError(
            f"evidence_version {payload.get('meta', {}).get('evidence_version')!r} "
            f"is not generator version {EVIDENCE_VERSION}"
        )
    _require_keys(
        payload,
        (
            "redshift_node_prices",
            "athena_price_per_tb",
            "synapse_dedicated_dwu_prices",
            "synapse_serverless_price_per_tb",
            "fabric_cu_prices",
            "databricks_dbu_prices_azure",
        ),
        "evidence root",
    )
    return payload


def _require_keys(mapping: dict, keys: tuple[str, ...], where: str) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise PricingGeneratorError(f"{where} is missing keys: {', '.join(missing)}")


def _flow_list(key: str, items: list[str], *, indent: int, width: int = 100) -> list[str]:
    """Render a YAML flow list, greedily wrapped past ``width`` columns."""
    opener = " " * indent + f"{key}: ["
    lines: list[str] = []
    current = opener
    for position, item in enumerate(items):
        addition = item if position == 0 else f", {item}"
        if position > 0 and len(current) + len(addition) + 1 > width:
            lines.append(current + ",")
            current = " " * (indent + 2) + item
        else:
            current += addition
    lines.append(current + "]")
    return lines


def _render_redshift_table(section: dict) -> list[str]:
    nodes = section.get("nodes", {})
    if set(nodes) != set(REDSHIFT_NODES):
        raise PricingGeneratorError(f"redshift evidence nodes {sorted(nodes)} do not match {sorted(REDSHIFT_NODES)}")
    other_from = section["other_from"]
    columns = [region for region in REDSHIFT_TABLE_COLUMNS if region != "other"]
    if set(section.get("regions", [])) != set(columns) | {other_from}:
        raise PricingGeneratorError("redshift evidence regions do not cover the emitted columns plus other_from")
    if other_from in columns:
        raise PricingGeneratorError(f"redshift other_from {other_from!r} must not be an emitted column")
    lines: list[str] = []
    for node in REDSHIFT_NODES:
        lines.append(f"{node}:")
        observed = nodes[node]
        for region in columns:
            lines.append(f"  {region}: {canonical_decimal(observed[region], min_places=2, max_places=4)}")
        lines.append(f"  other: {canonical_decimal(observed[other_from], min_places=2, max_places=4)}")
    return lines


def _render_synapse_dedicated_table(section: dict) -> list[str]:
    bases = section.get("base_rates_100dwu", {})
    if set(bases) != set(COST_TIERS):
        raise PricingGeneratorError(f"synapse base tiers {sorted(bases)} do not match {list(COST_TIERS)}")
    lines: list[str] = []
    for level, multiplier in DWU_LEVELS:
        lines.append(f"{level}:")
        for tier in COST_TIERS:
            base = canonical_decimal(bases[tier]["price"], min_places=2, max_places=2)
            price = canonical_decimal(str(Decimal(base) * multiplier), min_places=2, max_places=2)
            lines.append(f"  {tier}: {price}")
    return lines


def _render_tier_map(section_key: str, mapping: dict, *, price_places: tuple[int, int]) -> list[str]:
    if set(mapping) != set(COST_TIERS):
        raise PricingGeneratorError(f"{section_key} tiers {sorted(mapping)} do not match {list(COST_TIERS)}")
    lines: list[str] = []
    for tier in COST_TIERS:
        price = canonical_decimal(mapping[tier]["price"], min_places=price_places[0], max_places=price_places[1])
        lines.append(f"{tier}: {price}")
    return lines


def _render_databricks_azure(section: dict) -> list[str]:
    cells = section.get("cells", {})
    expected = {f"{tier}.{workload}" for tier in DATABRICKS_TIERS for workload in DATABRICKS_WORKLOADS}
    if set(cells) != expected:
        raise PricingGeneratorError(
            f"databricks azure cells drift from the priced schema: {sorted(set(cells) ^ expected)}"
        )
    lines: list[str] = []
    for tier in DATABRICKS_TIERS:
        lines.append(f"{tier}:")
        for workload in DATABRICKS_WORKLOADS:
            cell = cells[f"{tier}.{workload}"]
            bound = DATABRICKS_CELL_METER[(tier, workload)]
            observed = (cell.get("service"), cell.get("product"), cell.get("meter"))
            if observed != bound:
                raise PricingGeneratorError(
                    f"databricks azure cell {tier}.{workload} meter {observed} "
                    f"does not match the canonical binding {bound}"
                )
            lines.append(f"  {workload}: {canonical_decimal(cell['price'], min_places=2, max_places=2)}")
    return lines


def _render_region_table(table: str, section: dict, *, price_places: tuple[int, int]) -> list[str]:
    """Render a region-keyed per-TB table in evidence order, key line included.

    Athena and Synapse serverless price per TB scanned/processed with
    region-specific rates, so every observed region renders as its own cell
    and pricing.py resolves each run by region key. The value-section markers
    wrap the whole mapping (key line included). An empty region map fails
    closed instead of emitting an unpriced table.
    """
    regions = section.get("regions", {})
    if not isinstance(regions, dict) or not regions:
        raise PricingGeneratorError(f"{table} has no observed regions to render")
    lines = [f"{table}:"]
    for region, price in regions.items():
        lines.append(f"  {region}: {canonical_decimal(price, min_places=price_places[0], max_places=price_places[1])}")
    return lines


def _render_provenance(table: str, section: dict, *, regions: list[str]) -> list[str]:
    retrieved = section.get("retrieved", "")
    upstream = section.get("upstream_published", "")
    for label, value in (("retrieved", retrieved), ("upstream_published", upstream)):
        if value != "unknown":
            try:
                _datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError as exc:
                raise PricingGeneratorError(f"{table} provenance {label} {value!r} is not a date") from exc
    upstream_text = "unknown" if upstream == "unknown" else f"'{upstream}'"
    return [
        f"{table}:",
        f"  source: '{section['source'] if 'source' in section else section['url_template']}'",
        f"  retrieved: '{retrieved}'",
        f"  upstream_published: {upstream_text}",
        "  method: api",
        *_flow_list("verified_regions", regions, indent=2),
    ]


def _tier_regions(section: dict, key: str) -> list[str]:
    return [section[key][tier]["region"] for tier in COST_TIERS]


def render_all_sections(evidence: dict) -> dict[str, list[str]]:
    """Render every generated section as relative-indent lines, keyed by section id."""
    redshift = evidence["redshift_node_prices"]
    athena = evidence["athena_price_per_tb"]
    dedicated = evidence["synapse_dedicated_dwu_prices"]
    serverless = evidence["synapse_serverless_price_per_tb"]
    fabric = evidence["fabric_cu_prices"]
    databricks = evidence["databricks_dbu_prices_azure"]
    return {
        "redshift_node_prices": _render_redshift_table(redshift),
        "athena_price_per_tb": _render_region_table("athena_price_per_tb", athena, price_places=(1, 2)),
        "synapse_dedicated_dwu_prices": _render_synapse_dedicated_table(dedicated),
        "synapse_serverless_price_per_tb": _render_region_table(
            "synapse_serverless_price_per_tb", serverless, price_places=(1, 2)
        ),
        "fabric_cu_prices": _render_tier_map("fabric_cu_prices", fabric["tiers"], price_places=(2, 2)),
        "databricks.azure": _render_databricks_azure(databricks),
        "provenance.redshift_node_prices": _render_provenance(
            "redshift_node_prices", redshift, regions=list(redshift["regions"])
        ),
        "provenance.athena_price_per_tb": _render_provenance(
            "athena_price_per_tb", athena, regions=require_observed_regions(athena, "athena_price_per_tb")
        ),
        "provenance.synapse_dedicated_dwu_prices": _render_provenance(
            "synapse_dedicated_dwu_prices", dedicated, regions=_tier_regions(dedicated, "base_rates_100dwu")
        ),
        "provenance.synapse_serverless_price_per_tb": _render_provenance(
            "synapse_serverless_price_per_tb",
            serverless,
            regions=require_observed_regions(serverless, "synapse_serverless_price_per_tb"),
        ),
        "provenance.fabric_cu_prices": _render_provenance(
            "fabric_cu_prices", fabric, regions=_tier_regions(fabric, "tiers")
        ),
    }


def require_observed_regions(section: dict, table: str) -> list[str]:
    """Return the observed regions for a region-keyed table, failing closed on empty."""
    regions = section.get("regions", {})
    if not isinstance(regions, dict) or not regions:
        raise PricingGeneratorError(f"{table} has no observed regions")
    return list(regions)


BEGIN_PREFIX = "# BEGIN GENERATED "
END_PREFIX = "# END GENERATED "


def splice_sections(original_text: str, rendered: dict[str, list[str]]) -> str:
    """Replace each marked section body with its rendered lines."""
    lines = original_text.split("\n")
    begins: dict[str, int] = {}
    ends: dict[str, int] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(BEGIN_PREFIX):
            section = stripped[len(BEGIN_PREFIX) :].split()[0]
            if section in begins:
                raise PricingGeneratorError(f"duplicate BEGIN marker for {section}")
            begins[section] = index
        elif stripped.startswith(END_PREFIX):
            section = stripped[len(END_PREFIX) :].split()[0]
            if section in ends:
                raise PricingGeneratorError(f"duplicate END marker for {section}")
            ends[section] = index
    unknown = (set(begins) | set(ends)) - set(rendered)
    if unknown:
        raise PricingGeneratorError(f"markers without a renderer: {sorted(unknown)}")
    missing = set(rendered) - set(begins)
    if missing:
        raise PricingGeneratorError(f"rendered sections without markers: {sorted(missing)}")
    for section in rendered:
        if begins[section] > ends[section]:
            raise PricingGeneratorError(f"END marker precedes BEGIN for {section}")
    for section, block in rendered.items():
        indent = lines[begins[section]][: len(lines[begins[section]]) - len(lines[begins[section]].lstrip())]
        body = [(indent + text) if text else "" for text in block]
        lines[begins[section] + 1 : ends[section]] = body
        shift = len(body) - (ends[section] - begins[section] - 1)
        for other in begins:
            if begins[other] > begins[section]:
                begins[other] += shift
        for other in ends:
            if ends[other] > begins[section]:
                ends[other] += shift
    return "\n".join(lines)


def validate_manual_sections(pricing_text: str) -> None:
    """Require every hand-maintained table to carry a valid manual_review_due date."""
    payload = yaml.safe_load(pricing_text)
    if not isinstance(payload, dict):
        raise PricingGeneratorError("pricing_data.yaml must contain a mapping")
    provenance = payload.get("provenance", {})
    for table in MANUAL_TABLES:
        entry = provenance.get(table)
        if not isinstance(entry, dict):
            raise PricingGeneratorError(f"manual table {table!r} lost its provenance block")
        due = entry.get("manual_review_due")
        try:
            _datetime.date.fromisoformat(str(due))
        except (ValueError, TypeError) as exc:
            raise PricingGeneratorError(
                f"manual table {table!r} needs a manual_review_due ISO date, got {due!r}"
            ) from exc


def regenerated_text(evidence_path: Path = EVIDENCE_PATH, pricing_path: Path = PRICING_PATH) -> tuple[str, str, int]:
    """Return (committed text, regenerated text, section count), validating first."""
    evidence = load_evidence(evidence_path)
    original = pricing_path.read_text(encoding="utf-8")
    rendered = render_all_sections(evidence)
    updated = splice_sections(original, rendered)
    validate_manual_sections(updated)
    return original, updated, len(rendered)


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def run_check(evidence_path: Path = EVIDENCE_PATH, pricing_path: Path = PRICING_PATH) -> int:
    """Regenerate in memory; report a unified diff and exit 1 on drift."""
    original, updated, count = regenerated_text(evidence_path, pricing_path)
    if updated == original:
        print(f"pricing data matches vendor evidence ({count} generated sections)")
        return 0
    patch = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"{_display(pricing_path)} (committed)",
        tofile=f"{_display(pricing_path)} (regenerated)",
    )
    sys.stderr.write("".join(patch))
    sys.stderr.write("pricing data drifted from vendor evidence - run `make pricing-data` to regenerate\n")
    return 1


def run_regenerate(evidence_path: Path = EVIDENCE_PATH, pricing_path: Path = PRICING_PATH) -> int:
    """Regenerate the marked sections from the evidence file, writing on change."""
    original, updated, count = regenerated_text(evidence_path, pricing_path)
    if updated == original:
        print(f"pricing data already matches vendor evidence ({count} generated sections)")
        return 0
    pricing_path.write_text(updated, encoding="utf-8")
    print(f"wrote {_display(pricing_path)} ({count} generated sections)")
    return 0


# ---------------------------------------------------------------------------
# Scheduled refresh: re-pull the vendor APIs into the evidence file.
# ---------------------------------------------------------------------------


def _http_get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except Exception as exc:
        raise PricingGeneratorError(f"GET {url} failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise PricingGeneratorError(f"GET {url} returned a non-object payload")
    return payload


def fetch_aws_region_offer(url_template: str, region: str) -> tuple[str, dict, dict]:
    """Fetch one AWS bulk offer file; return (publication date, products, OnDemand terms)."""
    payload = _http_get_json(url_template.format(region=region))
    try:
        publication = payload["publicationDate"]
        products = payload["products"]
        terms = payload["terms"]["OnDemand"]
    except (KeyError, TypeError) as exc:
        raise PricingGeneratorError(f"AWS offer file for {region} has an unrecognized shape") from exc
    if not isinstance(publication, str) or not publication:
        raise PricingGeneratorError(f"AWS offer file for {region} carries no publication date")
    return publication, products, terms


def extract_aws_prices(
    products: dict, terms: dict, *, product_family: str, unit: str, key_attribute: str
) -> dict[str, str]:
    """Index OnDemand USD prices from an AWS bulk payload by one product attribute."""
    found: dict[str, str] = {}
    for sku, product in products.items():
        if not isinstance(product, dict) or product.get("productFamily") != product_family:
            continue
        attributes = product.get("attributes", {})
        key = attributes.get(key_attribute)
        if not key:
            continue
        for term in terms.get(sku, {}).values():
            for dimension in term.get("priceDimensions", {}).values():
                if not isinstance(dimension, dict) or dimension.get("unit") != unit:
                    continue
                price = (dimension.get("pricePerUnit") or {}).get("USD")
                if price is None:
                    continue
                if key in found:
                    raise PricingGeneratorError(f"AWS offer matched {key!r} twice; refusing to guess")
                found[key] = str(price)
    return found


def fetch_azure_region_items(service: str, region: str) -> list[dict]:
    """Fetch every Consumption row for one Azure service/region, following pages."""
    filtr = f"serviceName eq '{service}' and armRegionName eq '{region}' and priceType eq 'Consumption'"
    url: str | None = "https://prices.azure.com/api/retail/prices?$filter=" + urllib.parse.quote(filtr, safe="")
    rows: list[dict] = []
    pages = 0
    while url:
        pages += 1
        if pages > 100:
            raise PricingGeneratorError(f"Azure Retail Prices paged past 100 pages for {service}/{region}")
        payload = _http_get_json(url)
        items = payload.get("Items")
        if not isinstance(items, list):
            raise PricingGeneratorError(f"Azure Retail Prices response for {service}/{region} has no Items")
        rows.extend(items)
        nxt = payload.get("NextPageLink")
        url = nxt if isinstance(nxt, str) and nxt else None
    if not rows:
        raise PricingGeneratorError(f"Azure Retail Prices returned no rows for {service}/{region}")
    return rows


def select_azure_meter(rows: list[dict], *, service: str, region: str, product: str, meter: str, unit: str) -> str:
    """Return the live price of one exact (product, meter) pair, failing on drift in shape."""
    matches = [
        row
        for row in rows
        if row.get("productName") == product and row.get("meterName") == meter and row.get("serviceName") == service
    ]
    if len(matches) != 1:
        raise PricingGeneratorError(f"expected exactly one row for {service}/{region}/{meter}, found {len(matches)}")
    row = matches[0]
    if row.get("unitOfMeasure") != unit:
        raise PricingGeneratorError(f"meter {meter} in {region} changed unit to {row.get('unitOfMeasure')!r}")
    if row.get("currencyCode") != "USD":
        raise PricingGeneratorError(f"meter {meter} in {region} is no longer USD")
    if not isinstance(row.get("retailPrice"), (int, float)):
        raise PricingGeneratorError(f"meter {meter} in {region} carries no numeric retailPrice")
    return str(row["retailPrice"])


def select_fabric_cu_price(rows: list[dict], *, region: str) -> str:
    """Return the Fabric provisioned CU-hour rate, requiring those meters to agree.

    The "Capacity Overage" meter bills burst consumption above provisioned
    capacity at a multiple of the standard rate; the cost model prices
    provisioned CU-hours, so overage is excluded by name. Any future CU
    family that disagrees in price fails loudly instead of joining silently.
    """
    candidates = [
        row
        for row in rows
        if row.get("productName") == "Fabric Capacity"
        and row.get("unitOfMeasure") == "1 Hour"
        and "Capacity Usage" in str(row.get("meterName", ""))
        and "Overage" not in str(row.get("meterName", ""))
    ]
    if not candidates:
        raise PricingGeneratorError(f"no Fabric Capacity Usage meters found in {region}")
    for row in candidates:
        if row.get("currencyCode") != "USD":
            raise PricingGeneratorError(f"Fabric meter {row.get('meterName')!r} in {region} is no longer USD")
        if not isinstance(row.get("retailPrice"), (int, float)):
            raise PricingGeneratorError(f"Fabric meter {row.get('meterName')!r} in {region} has no numeric price")
    prices = {str(row["retailPrice"]) for row in candidates}
    if len(prices) != 1:
        raise PricingGeneratorError(f"Fabric CU meters disagree in {region}: {sorted(prices)}")
    return prices.pop()


def plan_price_update(recorded: str, fetched: str, *, min_places: int, max_places: int) -> str | None:
    """Return the replacement evidence string, or None when the fetched price matches.

    The live feed is first narrowed to ``max_places`` decimals (half up),
    the table's precision standard: the AWS bulk feed carries a fifth digit
    on some SKUs (rg.4xlarge reports 3.04267 against a four-decimal table)
    and the Azure feed carries extra digits on some meters (brazilsouth DWU
    reports 2.4194 against a two-decimal table). Both reproduce the committed
    values under this rule, so comparison happens at the emitted granularity
    and an unchanged upstream keeps its retrieval date. A vendor move of half
    the last emitted digit or more still registers as drift.
    """
    try:
        narrowed = Decimal(str(fetched).strip()).quantize(Decimal(1).scaleb(-max_places), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise PricingGeneratorError(f"fetched price {fetched!r} is not a decimal") from exc
    if not narrowed.is_finite() or narrowed <= 0:
        raise PricingGeneratorError(f"fetched price {fetched!r} is not a positive rate")
    if narrowed == Decimal(recorded):
        return None
    return canonical_decimal(str(narrowed), min_places=min_places, max_places=max_places)


class EvidenceUpdate:
    """One line-local evidence edit: ``path`` + ``key`` locate the line, ``old`` guards it."""

    def __init__(self, path: tuple[str, ...], key: str, old: str, new: str) -> None:
        self.path = path
        self.key = key
        self.old = old
        self.new = new

    def __repr__(self) -> str:
        return f"EvidenceUpdate({'.'.join([*self.path, self.key])}: {self.old!r} -> {self.new!r})"


_HEADER_LINE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+):\s*(?:#.*)?$")
_VALUE_LINE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+):\s*'([^']*)'\s*(?:#.*)?$")


def apply_evidence_updates(text: str, updates: list[EvidenceUpdate]) -> str:
    """Apply line-local evidence edits, preserving comments and layout.

    Each update must match exactly one line: the indent-derived key path must
    equal the update path, the key must match, and the quoted value must still
    be the recorded ``old`` string. Anything else fails closed.
    """
    lines = text.split("\n")
    for update in updates:
        applied = 0
        stack: list[tuple[int, str]] = []
        for index, line in enumerate(lines):
            header = _HEADER_LINE.match(line)
            if header is not None:
                indent = len(header.group(1))
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                stack.append((indent, header.group(2)))
                continue
            value = _VALUE_LINE.match(line)
            if value is None:
                continue
            indent = len(value.group(1))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            path = tuple(name for _, name in stack)
            if path == update.path and value.group(2) == update.key and value.group(3) == update.old:
                lines[index] = f"{value.group(1)}{update.key}: '{update.new}'"
                applied += 1
        if applied != 1:
            raise PricingGeneratorError(f"evidence update matched {applied} lines, expected 1: {update!r}")
    return "\n".join(lines)


def _stamp_retrieved(updates: list[EvidenceUpdate], evidence: dict, table: str, *, today: str, dirty: bool) -> None:
    if dirty:
        updates.append(EvidenceUpdate((table,), "retrieved", evidence[table]["retrieved"], today))


def collect_refresh_updates(evidence: dict, *, today: str) -> list[EvidenceUpdate]:
    """Pull every vendor API and diff against the evidence; no file writes here."""
    updates: list[EvidenceUpdate] = []
    _refresh_aws_redshift(evidence, updates, today=today)
    _refresh_aws_athena(evidence, updates, today=today)
    _refresh_synapse_dedicated(evidence, updates, today=today)
    _refresh_synapse_serverless(evidence, updates, today=today)
    _refresh_fabric(evidence, updates, today=today)
    _refresh_databricks_azure(evidence, updates, today=today)
    return updates


def _refresh_aws_redshift(evidence: dict, updates: list[EvidenceUpdate], *, today: str) -> None:
    section = evidence["redshift_node_prices"]
    publications: set[str] = set()
    prices_changed = False
    for region in section["regions"]:
        publication, products, terms = fetch_aws_region_offer(section["url_template"], region)
        publications.add(publication)
        by_node = extract_aws_prices(
            products,
            terms,
            product_family=section["match_product_family"],
            unit=section["match_unit"],
            key_attribute=section["match_key_attribute"],
        )
        for node in REDSHIFT_NODES:
            if node not in by_node:
                raise PricingGeneratorError(f"AWS offer no longer lists Redshift node {node} in {region}")
            replacement = plan_price_update(section["nodes"][node][region], by_node[node], min_places=2, max_places=4)
            if replacement is not None:
                updates.append(
                    EvidenceUpdate(
                        ("redshift_node_prices", "nodes", node), region, section["nodes"][node][region], replacement
                    )
                )
                prices_changed = True
    if len(publications) != 1:
        raise PricingGeneratorError(f"redshift regions disagree on publication date: {sorted(publications)}")
    (publication,) = publications
    if prices_changed and publication != section["upstream_published"]:
        updates.append(
            EvidenceUpdate(("redshift_node_prices",), "upstream_published", section["upstream_published"], publication)
        )
    _stamp_retrieved(updates, evidence, "redshift_node_prices", today=today, dirty=prices_changed)


def _refresh_aws_athena(evidence: dict, updates: list[EvidenceUpdate], *, today: str) -> None:
    section = evidence["athena_price_per_tb"]
    publications: set[str] = set()
    prices_changed = False
    for region in section["regions"]:
        publication, products, terms = fetch_aws_region_offer(section["url_template"], region)
        publications.add(publication)
        extracted = extract_aws_prices(
            products,
            terms,
            product_family=section["match_product_family"],
            unit=section["match_unit"],
            key_attribute="usagetype",
        )
        if len(extracted) != 1:
            raise PricingGeneratorError(f"Athena offer in {region} matched {len(extracted)} metered rows, expected 1")
        (fetched,) = extracted.values()
        replacement = plan_price_update(section["regions"][region], fetched, min_places=1, max_places=2)
        if replacement is not None:
            updates.append(
                EvidenceUpdate(("athena_price_per_tb", "regions"), region, section["regions"][region], replacement)
            )
            prices_changed = True
    if len(publications) != 1:
        raise PricingGeneratorError(f"athena regions disagree on publication date: {sorted(publications)}")
    (publication,) = publications
    if prices_changed and publication != section["upstream_published"]:
        updates.append(
            EvidenceUpdate(("athena_price_per_tb",), "upstream_published", section["upstream_published"], publication)
        )
    _stamp_retrieved(updates, evidence, "athena_price_per_tb", today=today, dirty=prices_changed)


def _refresh_synapse_dedicated(evidence: dict, updates: list[EvidenceUpdate], *, today: str) -> None:
    section = evidence["synapse_dedicated_dwu_prices"]
    match = {
        "product": section["match_product"],
        "meter": section["match_meter"],
        "unit": section["match_unit"],
    }
    dirty = False
    for tier in COST_TIERS:
        cell = section["base_rates_100dwu"][tier]
        rows = fetch_azure_region_items("Azure Synapse Analytics", cell["region"])
        fetched = select_azure_meter(rows, service="Azure Synapse Analytics", region=cell["region"], **match)
        replacement = plan_price_update(cell["price"], fetched, min_places=2, max_places=2)
        if replacement is not None:
            updates.append(
                EvidenceUpdate(
                    ("synapse_dedicated_dwu_prices", "base_rates_100dwu", tier), "price", cell["price"], replacement
                )
            )
            dirty = True
    _stamp_retrieved(updates, evidence, "synapse_dedicated_dwu_prices", today=today, dirty=dirty)


def _refresh_synapse_serverless(evidence: dict, updates: list[EvidenceUpdate], *, today: str) -> None:
    section = evidence["synapse_serverless_price_per_tb"]
    match = {
        "product": section["match_product"],
        "meter": section["match_meter"],
        "unit": section["match_unit"],
    }
    dirty = False
    for region, recorded in section["regions"].items():
        rows = fetch_azure_region_items("Azure Synapse Analytics", region)
        fetched = select_azure_meter(rows, service="Azure Synapse Analytics", region=region, **match)
        replacement = plan_price_update(recorded, fetched, min_places=1, max_places=2)
        if replacement is not None:
            updates.append(
                EvidenceUpdate(("synapse_serverless_price_per_tb", "regions"), region, recorded, replacement)
            )
            dirty = True
    _stamp_retrieved(updates, evidence, "synapse_serverless_price_per_tb", today=today, dirty=dirty)


def _refresh_fabric(evidence: dict, updates: list[EvidenceUpdate], *, today: str) -> None:
    section = evidence["fabric_cu_prices"]
    dirty = False
    for tier in COST_TIERS:
        cell = section["tiers"][tier]
        rows = fetch_azure_region_items("Microsoft Fabric", cell["region"])
        fetched = select_fabric_cu_price(rows, region=cell["region"])
        replacement = plan_price_update(cell["price"], fetched, min_places=2, max_places=2)
        if replacement is not None:
            updates.append(EvidenceUpdate(("fabric_cu_prices", "tiers", tier), "price", cell["price"], replacement))
            dirty = True
    _stamp_retrieved(updates, evidence, "fabric_cu_prices", today=today, dirty=dirty)


def _refresh_databricks_azure(evidence: dict, updates: list[EvidenceUpdate], *, today: str) -> None:
    section = evidence["databricks_dbu_prices_azure"]
    region = section["region"]
    # One query returns both the "Azure Databricks" and "Azure Databricks
    # Regional" product families (every row carries the same serviceName);
    # the triple match below tells them apart by productName.
    rows = fetch_azure_region_items(_AZURE_DATABRICKS, region)
    by_meter: dict[tuple[str, str, str], str] = {}
    for triple in {
        DATABRICKS_CELL_METER[(tier, workload)] for tier in DATABRICKS_TIERS for workload in DATABRICKS_WORKLOADS
    }:
        matches = [
            row for row in rows if (row.get("serviceName"), row.get("productName"), row.get("meterName")) == triple
        ]
        if len(matches) != 1:
            raise PricingGeneratorError(f"databricks meter {triple!r} matched {len(matches)} rows in {region}")
        row = matches[0]
        if row.get("unitOfMeasure") != "1 Hour":
            raise PricingGeneratorError(f"databricks meter {triple!r} changed unit to {row.get('unitOfMeasure')!r}")
        if row.get("currencyCode") != "USD":
            raise PricingGeneratorError(f"databricks meter {triple!r} is no longer USD")
        if not isinstance(row.get("retailPrice"), (int, float)):
            raise PricingGeneratorError(f"databricks meter {triple!r} carries no numeric retailPrice")
        by_meter[triple] = str(row["retailPrice"])
    dirty = False
    for tier in DATABRICKS_TIERS:
        for workload in DATABRICKS_WORKLOADS:
            cell = section["cells"][f"{tier}.{workload}"]
            triple = DATABRICKS_CELL_METER[(tier, workload)]
            replacement = plan_price_update(cell["price"], by_meter[triple], min_places=2, max_places=2)
            if replacement is not None:
                updates.append(
                    EvidenceUpdate(
                        ("databricks_dbu_prices_azure", "cells", f"{tier}.{workload}"),
                        "price",
                        cell["price"],
                        replacement,
                    )
                )
                dirty = True
    _stamp_retrieved(updates, evidence, "databricks_dbu_prices_azure", today=today, dirty=dirty)


def run_refresh(
    evidence_path: Path = EVIDENCE_PATH,
    pricing_path: Path = PRICING_PATH,
    *,
    today: str | None = None,
) -> int:
    """Re-pull the vendor APIs into the evidence file, then regenerate the tables."""
    stamp = today or str(_datetime.datetime.now(_datetime.timezone.utc).date())
    evidence = load_evidence(evidence_path)
    updates = collect_refresh_updates(evidence, today=stamp)
    if updates:
        revised = apply_evidence_updates(evidence_path.read_text(encoding="utf-8"), updates)
        evidence_path.write_text(revised, encoding="utf-8")
        print(f"wrote {_display(evidence_path)} ({len(updates)} observations refreshed)")
    else:
        print("vendor APIs match the recorded evidence; no upstream drift")
    return run_regenerate(evidence_path, pricing_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Regenerate in memory and exit 1 when the committed pricing data drifts.",
    )
    mode.add_argument(
        "--refresh",
        action="store_true",
        help="Re-pull the vendor APIs into the evidence file, then regenerate (network; scheduled only).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Dispatch the requested mode; return the process exit code."""
    args = parse_args(argv)
    try:
        if args.check:
            return run_check()
        if args.refresh:
            return run_refresh()
        return run_regenerate()
    except PricingGeneratorError as exc:
        print(f"generate_pricing_data: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
