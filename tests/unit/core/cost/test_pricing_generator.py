"""Tests for scripts/generate_pricing_data.py, the pricing drift guard.

The guard regenerates the vendor-derived sections of pricing_data.yaml from
the checked-in vendor evidence and fails on drift; the network-touching
refresh runs on a schedule, never in the PR-blocking path, so every test
here is offline (the fetchers are covered through fixture-shaped payloads).
"""

from __future__ import annotations

import shutil
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPTS_DIR = str(REPO_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import generate_pricing_data as generator  # noqa: E402

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

EVIDENCE_PATH = REPO_ROOT / "benchbox" / "core" / "cost" / "pricing_vendor_evidence.yaml"
PRICING_PATH = REPO_ROOT / "benchbox" / "core" / "cost" / "pricing_data.yaml"

GENERATED_SECTIONS = [
    "redshift_node_prices",
    "athena_price_per_tb",
    "synapse_dedicated_dwu_prices",
    "synapse_serverless_price_per_tb",
    "fabric_cu_prices",
    "databricks.azure",
    "provenance.redshift_node_prices",
    "provenance.athena_price_per_tb",
    "provenance.synapse_dedicated_dwu_prices",
    "provenance.synapse_serverless_price_per_tb",
    "provenance.fabric_cu_prices",
]

MANUAL_TABLES = [
    "snowflake_credit_prices",
    "bigquery_on_demand_prices",
    "firebolt_node_fbu_rates",
    "firebolt_fbu_price",
    "databricks_dbu_prices",
]


@pytest.fixture()
def scratch_copy(tmp_path):
    """Private evidence + pricing copies the generator can rewrite freely."""
    evidence = tmp_path / "pricing_vendor_evidence.yaml"
    pricing = tmp_path / "pricing_data.yaml"
    shutil.copy(EVIDENCE_PATH, evidence)
    shutil.copy(PRICING_PATH, pricing)
    return evidence, pricing


def test_check_passes_on_committed_data():
    """The guard arrives green: committed tables match the evidence, unstubbed."""
    assert generator.main(["--check"]) == 0


def test_regeneration_is_byte_stable(scratch_copy):
    """Regenerating onto a scratch copy produces no diff when upstream is unchanged."""
    evidence, pricing = scratch_copy
    before = pricing.read_bytes()
    assert generator.run_regenerate(evidence, pricing) == 0
    assert pricing.read_bytes() == before


def test_check_fails_on_edited_value(scratch_copy, capsys):
    """A deliberately edited generated value makes --check fail."""
    evidence, pricing = scratch_copy
    text = pricing.read_text(encoding="utf-8")
    assert "  dw100c:\n    us: 1.51" in text
    pricing.write_text(text.replace("  dw100c:\n    us: 1.51", "  dw100c:\n    us: 1.52", 1), encoding="utf-8")
    assert generator.run_check(evidence, pricing) == 1
    assert "dw100c" in capsys.readouterr().err


def test_check_fails_when_manual_review_due_missing(scratch_copy):
    """A hand-maintained table without a review date fails the guard."""
    evidence, pricing = scratch_copy
    text = pricing.read_text(encoding="utf-8")
    due_line = "    manual_review_due: '2026-12-17'\n"
    assert text.count(due_line) == len(MANUAL_TABLES)
    pricing.write_text(text.replace(due_line, "", 1), encoding="utf-8")
    with pytest.raises(generator.PricingGeneratorError, match="manual_review_due"):
        generator.run_check(evidence, pricing)


def test_manual_tables_carry_review_due_dates():
    """Every hand-maintained table pins its next manual review as an ISO date."""
    payload = yaml.safe_load(PRICING_PATH.read_text(encoding="utf-8"))
    for table in MANUAL_TABLES:
        due = payload["provenance"][table]["manual_review_due"]
        assert date.fromisoformat(due) > date(2026, 9, 18)


def test_evidence_regions_match_runtime_tables():
    """The evidence region maps must equal the tables pricing.py resolves.

    Region-parameter pricing resolves each run by region key, so an evidence
    region missing from (or extra to) the runtime table would silently move
    published totals; the generator pins the two to each other, keys and
    values.
    """
    from benchbox.core.cost import pricing

    evidence = generator.load_evidence()
    for table, runtime in (
        ("athena_price_per_tb", pricing.ATHENA_PRICE_PER_TB),
        ("synapse_serverless_price_per_tb", pricing.SYNAPSE_SERVERLESS_PRICE_PER_TB),
    ):
        regions = evidence[table]["regions"]
        assert set(regions) == set(runtime), table
        for region, price in regions.items():
            assert Decimal(str(runtime[region])) == Decimal(price), (table, region)


def test_region_tables_render_every_observed_region():
    """Athena/Synapse serverless render one cell per observed region, never a scalar."""
    evidence = generator.load_evidence()
    rendered = generator.render_all_sections(evidence)
    athena = "\n".join(rendered["athena_price_per_tb"])
    assert "us-east-1: 5.0" in athena
    assert "sa-east-1: 9.0" in athena
    assert "athena_price_per_tb: 5.0" not in athena
    serverless = "\n".join(rendered["synapse_serverless_price_per_tb"])
    assert "southeastasia: 6.75" in serverless
    assert "brazilsouth: 9.0" in serverless
    assert "synapse_serverless_price_per_tb: 5.0" not in serverless


def test_committed_file_marks_every_generated_section():
    """Each generated section has exactly one BEGIN/END marker pair."""
    text = PRICING_PATH.read_text(encoding="utf-8")
    for section in GENERATED_SECTIONS:
        assert text.count(f"# BEGIN GENERATED {section} ") == 1, section
        assert text.count(f"# END GENERATED {section}") == 1, section


def test_dwu_levels_scale_linearly_from_base_rates():
    """Every DWU level is its base rate times its multiplier; spot-check literals."""
    evidence = generator.load_evidence()
    rendered = generator.render_all_sections(evidence)
    block = "\n".join(rendered["synapse_dedicated_dwu_prices"])
    assert "  us: 453.00" in block
    assert "  ap: 27.15" in block
    assert "  ca: 66.50" in block
    bases = evidence["synapse_dedicated_dwu_prices"]["base_rates_100dwu"]
    expected_lines: list[str] = []
    for level, multiplier in generator.DWU_LEVELS:
        expected_lines.append(f"{level}:")
        for tier in generator.COST_TIERS:
            expected_lines.append(f"  {tier}: {Decimal(bases[tier]['price']) * multiplier:.2f}")
    assert rendered["synapse_dedicated_dwu_prices"] == expected_lines


def test_other_bucket_carries_the_sa_east_1_observation():
    """The `other` bucket fails high: it always renders the sa-east-1 value."""
    evidence = generator.load_evidence()
    block = "\n".join(generator.render_all_sections(evidence)["redshift_node_prices"])
    nodes = evidence["redshift_node_prices"]["nodes"]
    for node in ("dc2.large", "ra3.16xlarge", "rg.12xlarge"):
        assert f"{node}:" in block
        assert f"  other: {nodes[node]['sa-east-1']}" in block


def test_evidence_strings_are_canonical():
    """Every recorded price is already in canonical form, so refresh diffs are real moves."""
    evidence = generator.load_evidence()
    section = evidence["redshift_node_prices"]
    for node, regions in section["nodes"].items():
        for region, price in regions.items():
            assert generator.canonical_decimal(price, min_places=2, max_places=4) == price, (node, region)
    for tier, cell in evidence["synapse_dedicated_dwu_prices"]["base_rates_100dwu"].items():
        assert generator.canonical_decimal(cell["price"], min_places=2, max_places=2) == cell["price"], tier
    for table in ("athena_price_per_tb", "synapse_serverless_price_per_tb"):
        for key, price in evidence[table]["regions"].items():
            assert generator.canonical_decimal(price, min_places=1, max_places=2) == price, (table, key)


def test_canonical_decimal_refuses_precision_loss():
    """A value needing more places raises instead of rounding silently."""
    with pytest.raises(generator.PricingGeneratorError):
        generator.canonical_decimal("0.30005", min_places=2, max_places=4)
    with pytest.raises(generator.PricingGeneratorError):
        generator.canonical_decimal("not-a-number", min_places=2, max_places=4)


def test_canonical_decimal_refuses_non_positive_rates():
    """Zero and negative rates fail closed instead of rendering into tables."""
    with pytest.raises(generator.PricingGeneratorError):
        generator.canonical_decimal("0.00", min_places=2, max_places=4)
    with pytest.raises(generator.PricingGeneratorError):
        generator.canonical_decimal("-1.50", min_places=2, max_places=4)


def test_plan_price_update_keeps_date_on_match():
    """Numerically equal fetches keep the recorded string (no false drift)."""
    assert generator.plan_price_update("0.30", "0.3000000000", min_places=2, max_places=4) is None
    assert generator.plan_price_update("0.40", "0.4", min_places=2, max_places=2) is None
    assert generator.plan_price_update("0.30", "0.31", min_places=2, max_places=4) == "0.31"


def test_refresh_compares_at_emitted_precision():
    """Feed digits past the table standard narrow half-up instead of flagging drift."""
    assert generator.plan_price_update("3.0427", "3.0426700000", min_places=2, max_places=4) is None
    assert generator.plan_price_update("3.5401", "3.5401300000", min_places=2, max_places=4) is None
    assert generator.plan_price_update("2.42", "2.4194", min_places=2, max_places=2) is None
    assert generator.plan_price_update("3.0427", "3.0428", min_places=2, max_places=4) == "3.0428"
    with pytest.raises(generator.PricingGeneratorError):
        generator.plan_price_update("0.18", "0.00", min_places=2, max_places=2)
    with pytest.raises(generator.PricingGeneratorError):
        generator.plan_price_update("0.18", "not-a-rate", min_places=2, max_places=2)


def test_apply_evidence_updates_is_line_local(scratch_copy):
    """Evidence edits replace one guarded line and preserve comments."""
    evidence, _ = scratch_copy
    text = evidence.read_text(encoding="utf-8")
    update = generator.EvidenceUpdate(("redshift_node_prices", "nodes", "dc2.large"), "us-east-1", "0.25", "0.26")
    revised = generator.apply_evidence_updates(text, [update])
    assert "      us-east-1: '0.26'" in revised
    assert revised.count("us-east-1: '0.26'") == 1
    assert "# Vendor pricing observations" in revised
    with pytest.raises(generator.PricingGeneratorError):
        stale = generator.EvidenceUpdate(("redshift_node_prices", "nodes", "dc2.large"), "us-east-1", "0.25", "0.27")
        generator.apply_evidence_updates(revised, [stale])


def test_splice_rejects_unknown_and_duplicate_markers():
    """Stray or doubled markers fail closed instead of generating around them."""
    evidence = generator.load_evidence()
    rendered = generator.render_all_sections(evidence)
    original = PRICING_PATH.read_text(encoding="utf-8")
    with pytest.raises(generator.PricingGeneratorError):
        generator.splice_sections(original + "# BEGIN GENERATED phantom -- x\n", rendered)
    doubled = original.replace(
        "# END GENERATED fabric_cu_prices",
        "# END GENERATED fabric_cu_prices\n  # BEGIN GENERATED fabric_cu_prices -- x",
        1,
    )
    with pytest.raises(generator.PricingGeneratorError):
        generator.splice_sections(doubled, rendered)


def test_extract_aws_prices_indexes_by_attribute():
    """The AWS bulk parser finds the OnDemand USD dimension per product key."""
    products = {
        "sku-a": {
            "productFamily": "Compute Instance",
            "attributes": {"instanceType": "dc2.large", "usagetype": "Node:dc2.large"},
        },
        "sku-b": {
            "productFamily": "Compute Instance",
            "attributes": {"instanceType": "ra3.large", "usagetype": "Node:ra3.large"},
        },
        "sku-c": {
            "productFamily": "Redshift Managed Storage",
            "attributes": {"usagetype": "Storage"},
        },
    }
    terms = {
        "sku-a": {"term-a": {"priceDimensions": {"dim": {"unit": "Hrs", "pricePerUnit": {"USD": "0.2500000000"}}}}},
        "sku-b": {"term-b": {"priceDimensions": {"dim": {"unit": "Hrs", "pricePerUnit": {"USD": "0.5430000000"}}}}},
        "sku-c": {"term-c": {"priceDimensions": {"dim": {"unit": "GB-Mo", "pricePerUnit": {"USD": "0.024"}}}}},
    }
    found = generator.extract_aws_prices(
        products, terms, product_family="Compute Instance", unit="Hrs", key_attribute="usagetype"
    )
    assert found == {"Node:dc2.large": "0.2500000000", "Node:ra3.large": "0.5430000000"}


def test_select_azure_meter_requires_exact_match():
    """The Azure selector takes one exact meter and rejects unit or currency drift."""
    rows = [
        {
            "serviceName": "Azure Synapse Analytics",
            "productName": "Azure Synapse Analytics SQL Provisioned DWU",
            "meterName": "100 DWU",
            "unitOfMeasure": "1/Hour",
            "currencyCode": "USD",
            "retailPrice": 1.51,
        }
    ]
    assert (
        generator.select_azure_meter(
            rows,
            service="Azure Synapse Analytics",
            region="eastus",
            product="Azure Synapse Analytics SQL Provisioned DWU",
            meter="100 DWU",
            unit="1/Hour",
        )
        == "1.51"
    )
    with pytest.raises(generator.PricingGeneratorError):
        generator.select_azure_meter(
            rows + [dict(rows[0])],
            service="Azure Synapse Analytics",
            region="eastus",
            product="Azure Synapse Analytics SQL Provisioned DWU",
            meter="100 DWU",
            unit="1/Hour",
        )


def test_select_fabric_cu_price_requires_agreement():
    """Fabric CU meters must speak with one price, or refresh fails loudly."""
    rows = [
        {
            "productName": "Fabric Capacity",
            "meterName": "A Capacity Usage CU",
            "unitOfMeasure": "1 Hour",
            "currencyCode": "USD",
            "retailPrice": 0.18,
        },
        {
            "productName": "Fabric Capacity",
            "meterName": "B Capacity Usage CU",
            "unitOfMeasure": "1 Hour",
            "currencyCode": "USD",
            "retailPrice": 0.18,
        },
        {
            "productName": "Fabric Capacity",
            "meterName": "Capacity Overage Capacity Usage CU",
            "unitOfMeasure": "1 Hour",
            "currencyCode": "USD",
            "retailPrice": 0.54,
        },
    ]
    assert generator.select_fabric_cu_price(rows, region="eastus") == "0.18"
    rows[1]["retailPrice"] = 0.19
    with pytest.raises(generator.PricingGeneratorError):
        generator.select_fabric_cu_price(rows, region="eastus")


def test_refresh_with_unchanged_upstream_writes_nothing(scratch_copy, monkeypatch):
    """A refresh that finds no moves leaves evidence and tables byte-identical."""
    evidence, pricing = scratch_copy
    before_evidence = evidence.read_bytes()
    before_pricing = pricing.read_bytes()
    monkeypatch.setattr(generator, "fetch_aws_region_offer", _recorded_aws_offer)
    monkeypatch.setattr(generator, "fetch_azure_region_items", _recorded_azure_rows)
    assert generator.run_refresh(evidence, pricing, today="2026-09-19") == 0
    assert evidence.read_bytes() == before_evidence
    assert pricing.read_bytes() == before_pricing


def test_refresh_fails_closed_when_node_missing_from_offer(scratch_copy, monkeypatch):
    """A node the upstream offer no longer lists aborts the refresh loudly."""
    evidence, pricing = scratch_copy

    def _missing_node_offer(url_template, region):
        publication, products, terms = _recorded_aws_offer(url_template, region)
        if "AmazonRedshift" in url_template:
            omitted = next(iter(products))
            del products[omitted]
            del terms[omitted]
        return publication, products, terms

    monkeypatch.setattr(generator, "fetch_aws_region_offer", _missing_node_offer)
    monkeypatch.setattr(generator, "fetch_azure_region_items", _recorded_azure_rows)
    with pytest.raises(generator.PricingGeneratorError):
        generator.run_refresh(evidence, pricing, today="2026-09-19")


def test_refresh_records_moved_price_with_new_date(scratch_copy, monkeypatch):
    """A moved upstream price updates the cell and stamps the refresh date."""
    evidence, pricing = scratch_copy
    monkeypatch.setattr(generator, "fetch_aws_region_offer", _recorded_aws_offer)
    monkeypatch.setattr(generator, "fetch_azure_region_items", _moved_fabric_rows)
    assert generator.run_refresh(evidence, pricing, today="2026-09-19") == 0
    revised = yaml.safe_load(evidence.read_text(encoding="utf-8"))
    assert revised["fabric_cu_prices"]["tiers"]["us"]["price"] == "0.19"
    assert revised["fabric_cu_prices"]["retrieved"] == "2026-09-19"
    assert revised["redshift_node_prices"]["retrieved"] == "2026-09-18"
    assert b"  us: 0.19" in pricing.read_bytes()


def _recorded_aws_offer(url_template, region):
    """Replay the recorded evidence as fetch results (offer keyed by template)."""
    evidence = generator.load_evidence()
    if "AmazonRedshift" in url_template:
        section = evidence["redshift_node_prices"]
        products = {
            f"sku-{node}": {
                "productFamily": "Compute Instance",
                "attributes": {"instanceType": node, "usagetype": f"Node:{node}"},
            }
            for node in generator.REDSHIFT_NODES
        }
        terms = {
            f"sku-{node}": {
                "term": {
                    "priceDimensions": {
                        "dim": {"unit": "Hrs", "pricePerUnit": {"USD": f"{section['nodes'][node][region]}0000000"}}
                    }
                }
            }
            for node in generator.REDSHIFT_NODES
        }
        return section["upstream_published"], products, terms
    section = evidence["athena_price_per_tb"]
    products = {
        "sku-athena": {"productFamily": "Athena Queries", "attributes": {"usagetype": "DataScannedInTB"}},
    }
    terms = {
        "sku-athena": {
            "term": {
                "priceDimensions": {
                    "dim": {"unit": "Terabytes", "pricePerUnit": {"USD": f"{section['regions'][region]}000000000"}}
                }
            }
        }
    }
    return section["upstream_published"], products, terms


def _recorded_azure_rows(service, region):
    """Replay the recorded evidence as Azure Retail Prices rows."""
    evidence = generator.load_evidence()
    rows = []
    dedicated = evidence["synapse_dedicated_dwu_prices"]
    for tier, cell in dedicated["base_rates_100dwu"].items():
        if service == "Azure Synapse Analytics" and region == cell["region"]:
            rows.append(
                _azure_row(service, dedicated["match_product"], dedicated["match_meter"], cell["price"], "1/Hour")
            )
    serverless = evidence["synapse_serverless_price_per_tb"]
    if service == "Azure Synapse Analytics" and region in serverless["regions"]:
        rows.append(
            _azure_row(
                service, serverless["match_product"], serverless["match_meter"], serverless["regions"][region], "1 TB"
            )
        )
    fabric = evidence["fabric_cu_prices"]
    for tier, cell in fabric["tiers"].items():
        if service == "Microsoft Fabric" and region == cell["region"]:
            rows.append(_azure_row(service, fabric["match_product"], f"{tier} Capacity Usage CU", cell["price"]))
    databricks = evidence["databricks_dbu_prices_azure"]
    if region == databricks["region"]:
        seen: set[tuple[str, str, str]] = set()
        for key, cell in databricks["cells"].items():
            triple = (cell["service"], cell["product"], cell["meter"])
            if cell["service"] == service and triple not in seen:
                seen.add(triple)
                rows.append(_azure_row(service, cell["product"], cell["meter"], cell["price"]))
    return rows


def _azure_row(service, product, meter, price, unit="1 Hour"):
    return {
        "serviceName": service,
        "productName": product,
        "meterName": meter,
        "unitOfMeasure": unit,
        "currencyCode": "USD",
        "retailPrice": float(price),
    }


def _moved_fabric_rows(service, region):
    """Recorded rows except the eastus Fabric CU meter, which moved to 0.19."""
    rows = _recorded_azure_rows(service, region)
    for row in rows:
        if service == "Microsoft Fabric" and region == "eastus":
            row["retailPrice"] = 0.19
    return rows
