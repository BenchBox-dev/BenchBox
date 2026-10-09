#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as _datetime
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path

import yaml

from benchbox.utils.clock import elapsed_seconds, mono_time

CLI_DESCRIPTION = "Regenerate the vendor-derived pricing tables from checked-in vendor evidence."

REPO_ROOT = Path(__file__).resolve().parent.parent
COST_DIR = REPO_ROOT / "benchbox" / "core" / "cost"
EVIDENCE_PATH = COST_DIR / "pricing_vendor_evidence.yaml"
PRICING_PATH = COST_DIR / "pricing_data.yaml"

EVIDENCE_VERSION = 1
REQUEST_TIMEOUT_SECONDS = 60
HTTP_ATTEMPTS = 3
HTTP_RETRY_BUDGET_SECONDS = 120
RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "BenchBox-pricing-generator"

MANUAL_TABLES = (
    "snowflake_credit_prices",
    "bigquery_on_demand_prices",
    "firebolt_node_fbu_rates",
    "firebolt_fbu_price",
    "databricks_dbu_prices",
)

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
    pass


def canonical_decimal(raw: str, *, min_places: int, max_places: int) -> str:
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
    regions = section.get("regions", {})
    if not isinstance(regions, dict) or not regions:
        raise PricingGeneratorError(f"{table} has no observed regions")
    return list(regions)


SECTION_PATHS: dict[str, tuple[tuple[str, ...], bool]] = {
    "redshift_node_prices": (("redshift_node_prices",), False),
    "athena_price_per_tb": (("athena_price_per_tb",), True),
    "synapse_dedicated_dwu_prices": (("synapse_dedicated_dwu_prices",), False),
    "synapse_serverless_price_per_tb": (("synapse_serverless_price_per_tb",), True),
    "fabric_cu_prices": (("fabric_cu_prices",), False),
    "databricks.azure": (("databricks_dbu_prices", "azure"), False),
    "provenance.redshift_node_prices": (("provenance", "redshift_node_prices"), True),
    "provenance.athena_price_per_tb": (("provenance", "athena_price_per_tb"), True),
    "provenance.synapse_dedicated_dwu_prices": (("provenance", "synapse_dedicated_dwu_prices"), True),
    "provenance.synapse_serverless_price_per_tb": (("provenance", "synapse_serverless_price_per_tb"), True),
    "provenance.fabric_cu_prices": (("provenance", "fabric_cu_prices"), True),
}
_KEY_LINE = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_.-]+):(?:\s|$)")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _key_line(lines: list[str], path: tuple[str, ...]) -> int:
    stack: list[tuple[int, str]] = []
    found = []
    for index, line in enumerate(lines):
        match = _KEY_LINE.match(line)
        if not match:
            continue
        indent = len(match.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, match.group("key")))
        if tuple(key for _, key in stack) == path:
            found.append(index)
    if len(found) != 1:
        raise PricingGeneratorError(f"expected one key for {'.'.join(path)}, found {len(found)}")
    return found[0]


def _block_end(lines: list[str], start: int) -> int:
    indent = _indent(lines[start])
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) > indent):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return end


def splice_sections(original_text: str, rendered: dict[str, list[str]]) -> str:
    unknown = set(rendered) - set(SECTION_PATHS)
    if unknown:
        raise PricingGeneratorError(f"rendered sections without a key path: {sorted(unknown)}")
    missing = set(SECTION_PATHS) - set(rendered)
    if missing:
        raise PricingGeneratorError(f"key paths without a renderer: {sorted(missing)}")
    lines = original_text.split("\n")
    for section, block in rendered.items():
        path, whole = SECTION_PATHS[section]
        key = _key_line(lines, path)
        end = _block_end(lines, key)
        if not whole and lines[key].split(":", 1)[1].split("#", 1)[0].strip():
            raise PricingGeneratorError(f"{section} key has an inline value, so its body cannot be replaced")
        first = key if whole else key + 1
        indent = " " * (_indent(lines[key]) if whole else _indent(lines[key]) + 2)
        lines[first:end] = [(indent + text) if text else "" for text in block]
    spliced = "\n".join(lines)
    before, after = yaml.safe_load(original_text), yaml.safe_load(spliced)
    if not isinstance(after, dict) or list(after) != list(before or {}):
        raise PricingGeneratorError("splicing changed the top-level keys of pricing_data.yaml")
    return spliced


def validate_manual_sections(pricing_text: str) -> None:
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
    original, updated, count = regenerated_text(evidence_path, pricing_path)
    if updated == original:
        print(f"pricing data already matches vendor evidence ({count} generated sections)")
        return 0
    pricing_path.write_text(updated, encoding="utf-8")
    print(f"wrote {_display(pricing_path)} ({count} generated sections)")
    return 0


def _retry_after_seconds(value: str | None, *, now: _datetime.datetime | None = None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdecimal():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            return None
        observed_at = now if now is not None else _datetime.datetime.now(_datetime.timezone.utc)
        return max(0.0, (retry_at - observed_at).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None


def _http_get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    started = mono_time()
    for attempt in range(1, HTTP_ATTEMPTS + 1):
        remaining = HTTP_RETRY_BUDGET_SECONDS - elapsed_seconds(started)
        if remaining <= 0:
            raise PricingGeneratorError(f"GET {url} exhausted its HTTP retry budget")
        try:
            with urllib.request.urlopen(request, timeout=min(REQUEST_TIMEOUT_SECONDS, remaining)) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
            exc.close()
            if exc.code not in RETRYABLE_HTTP_STATUSES or attempt == HTTP_ATTEMPTS:
                raise PricingGeneratorError(f"GET {url} failed after {attempt} attempt(s): {exc}") from exc
            delay = _retry_after_seconds(retry_after)
            if delay is None:
                delay = float(2**attempt)
            remaining = HTTP_RETRY_BUDGET_SECONDS - elapsed_seconds(started)
            if delay >= remaining:
                raise PricingGeneratorError(f"GET {url} cannot honor Retry-After within its HTTP retry budget") from exc
            time.sleep(delay)
            continue
        except Exception as exc:
            raise PricingGeneratorError(f"GET {url} failed: {exc}") from exc
        if elapsed_seconds(started) >= HTTP_RETRY_BUDGET_SECONDS:
            raise PricingGeneratorError(f"GET {url} exhausted its HTTP retry budget")
        if not isinstance(payload, dict):
            raise PricingGeneratorError(f"GET {url} returned a non-object payload")
        return payload
    raise PricingGeneratorError(f"GET {url} exhausted its HTTP attempts")


def fetch_aws_region_offer(url_template: str, region: str) -> tuple[str, dict, dict]:
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
    candidates = [
        row
        for row in rows
        if row.get("productName") == "Fabric Capacity"
        and row.get("unitOfMeasure") == "1 Hour"
        and "Capacity Usage" in str(row.get("meterName", ""))
        and "Overage" not in str(row.get("meterName", ""))
        and "Custom Connector" not in str(row.get("meterName", ""))
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
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
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
