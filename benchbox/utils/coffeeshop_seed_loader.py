from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources


@dataclass(frozen=True)
class LocationSeed:
    record_id: int
    location_id: str
    city: str
    state: str
    country: str
    region: str


@dataclass(frozen=True)
class ProductSeed:
    record_id: int
    product_id: int
    name: str
    category: str
    subcategory: str
    standard_cost: float
    standard_price: float
    from_date: str
    to_date: str


def _read_csv(package: str, resource: str) -> Iterable[dict[str, str]]:

    with resources.files(package).joinpath(resource).open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        yield from reader


@lru_cache(maxsize=1)
def load_location_seeds() -> list[LocationSeed]:

    package = "benchbox.data.coffeeshop"
    rows = []
    for row in _read_csv(package, "dim_locations.csv"):
        rows.append(
            LocationSeed(
                record_id=int(row["record_id"]),
                location_id=row["location_id"].strip(),
                city=row["city"].strip(),
                state=row["state"].strip(),
                country=row["country"].strip(),
                region=row["region"].strip(),
            )
        )
    return rows


@lru_cache(maxsize=1)
def load_product_seeds() -> list[ProductSeed]:

    package = "benchbox.data.coffeeshop"
    rows = []
    for row in _read_csv(package, "dim_products.csv"):
        rows.append(
            ProductSeed(
                record_id=int(row["record_id"]),
                product_id=int(row["product_id"]),
                name=row["name"].strip(),
                category=row["category"].strip(),
                subcategory=row["subcategory"].strip(),
                standard_cost=float(row["standard_cost"]),
                standard_price=float(row["standard_price"]),
                from_date=row["from_date"].strip(),
                to_date=row["to_date"].strip(),
            )
        )
    return rows


__all__ = [
    "LocationSeed",
    "ProductSeed",
    "load_location_seeds",
    "load_product_seeds",
]
