"""Doc <-> catalog YAML consistency for empirical sketch-storage claims.

Closes blind-spot 2026-05-05-003357. Numeric bytes claims in the
sketch-functions doc must fall inside the matching catalog
``expected_value_min/max`` bound; this test catches drift between the
two sources without requiring the catalog comments to be machine-
readable annotations.

The mapping below is small and explicit: each entry pins one prose
claim ("XXXX bytes verified ...") to the validation_query whose
bound bracket should contain it. When either the doc text or the
catalog bound moves, the test fails with a message naming both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from benchbox.core.write_primitives.catalog.loader import (
    load_write_primitives_catalog,
)

pytestmark = [pytest.mark.fast, pytest.mark.unit]


_DOC_PATH = Path(__file__).resolve().parents[4] / "docs/benchmarks/write-primitives-sketch-functions.md"


@dataclass(frozen=True)
class _Claim:
    op_id: str
    validation_id: str
    pattern: str  # regex matching the doc fragment


# Pinned doc claims and their target validation_query bound. Add an entry
# here when a new sketch family lands a "verified <tool>" prose claim.
# This deliberately avoids structured annotations in the docs: the regexes
# bind only the compact empirical clause, so surrounding prose can stay natural
# while storage-size numbers still fail loudly when removed or re-stamped.
CLAIMS: list[_Claim] = [
    _Claim(
        op_id="sketch_query_theta_union_merge",
        validation_id="theta_storage_size_clickhouse",
        pattern=r"(\d{4,6})\s+bytes verified clickhouse-local\s+[\d.]+,\s+uniq HLL\+\+",
    ),
    _Claim(
        op_id="sketch_query_kll_quantiles_merge",
        validation_id="kll_storage_size_clickhouse",
        pattern=r"(\d{4,6})\s+bytes verified clickhouse-local\s+[\d.]+,\s+T-Digest",
    ),
    _Claim(
        op_id="sketch_query_topk_combine",
        validation_id="topk_storage_size_clickhouse",
        pattern=r"(\d{2,6})\s+bytes verified clickhouse-local\s+[\d.]+,\s+topK",
    ),
]


def _doc_text() -> str:
    return _DOC_PATH.read_text(encoding="utf-8")


def _bound_for(catalog, op_id: str, validation_id: str) -> tuple[float, float]:
    op = catalog.operations.get(op_id)
    if op is None:
        pytest.fail(f"Catalog has no op {op_id} -- update CLAIMS or restore the op")
    for vq in op.validation_queries:
        if vq.id == validation_id and vq.expected_value_min is not None:
            return (vq.expected_value_min, vq.expected_value_max)
    pytest.fail(f"Op {op_id} has no validation_query {validation_id!r} with expected_value_min/max bound")


@pytest.fixture(scope="module")
def doc_text() -> str:
    return _doc_text()


@pytest.fixture(scope="module")
def catalog():
    return load_write_primitives_catalog()


@pytest.mark.parametrize("claim", CLAIMS, ids=lambda c: c.op_id)
def test_doc_claim_within_catalog_bound(claim: _Claim, doc_text: str, catalog) -> None:
    match = re.search(claim.pattern, doc_text)
    if match is None:
        pytest.fail(
            f"Doc claim missing for {claim.op_id}/{claim.validation_id}. "
            f"Pattern {claim.pattern!r} did not match in {_DOC_PATH.name}. "
            "Either restore the prose or remove the entry from CLAIMS."
        )
    observed = float(match.group(1))
    bound_min, bound_max = _bound_for(catalog, claim.op_id, claim.validation_id)
    assert bound_min <= observed <= bound_max, (
        f"Doc says {observed:.0f} bytes for {claim.op_id}/{claim.validation_id}, "
        f"but catalog bound is [{bound_min:.0f}, {bound_max:.0f}]. "
        "If the bound moved, restamp the doc; if the doc moved, restamp the bound."
    )
