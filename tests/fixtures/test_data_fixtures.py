"""Shared test data fixtures for BenchBox tests.

This module provides session-scoped fixtures that generate test data once
and reuse it across all tests, significantly improving test performance.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import csv
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def tpch_sample_data_session() -> Generator[Path, None, None]:
    """Create TPC-H sample data once per test session for reuse across all tests.

    This fixture creates a temporary directory with sample TPC-H data that
    persists for the entire test session, eliminating redundant data generation.

    Returns:
        Path: Directory containing generated CSV files
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="benchbox_test_data_"))

    # Create sample region data
    region_file = temp_dir / "region.csv"
    region_data = [
        ["0", "AFRICA", "lar deposits. blithely final packages cajole"],
        ["1", "AMERICA", "hs use ironic, even requests"],
        ["2", "ASIA", "ges. thinly even pinto beans ca"],
        ["3", "EUROPE", "ly final courts cajole furiously"],
        ["4", "MIDDLE EAST", "uickly special requests"],
    ]

    with open(region_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(region_data)

    # Create sample nation data
    nation_file = temp_dir / "nation.csv"
    nation_data = [
        ["0", "ALGERIA", "0", "haggle. carefully final deposits detect"],
        ["1", "ARGENTINA", "1", "al foxes promise slyly according to the"],
        ["2", "BRAZIL", "1", "y alongside of the pending deposits"],
        ["3", "CANADA", "1", "eas hang ironic, silent packages"],
        ["4", "EGYPT", "4", "y above the carefully unusual theodolites"],
        ["5", "ETHIOPIA", "0", "ven packages wake quickly"],
    ]

    with open(nation_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(nation_data)

    # Create sample customer data
    customer_file = temp_dir / "customer.csv"
    customer_data = [
        [
            "1",
            "Customer#000000001",
            "IVhzIApeRb ot,c,E",
            "0",
            "25-989-741-2988",
            "711.56",
            "BUILDING",
            "foxes. pending, express",
        ],
        [
            "2",
            "Customer#000000002",
            "XSTf4,NCwDVaWNe6tEgvwfmRchLXak",
            "1",
            "23-768-687-3665",
            "121.65",
            "AUTOMOBILE",
            "l accounts. even, express",
        ],
        [
            "3",
            "Customer#000000003",
            "MG9kdTD2WBHm",
            "1",
            "11-719-748-3364",
            "7498.12",
            "AUTOMOBILE",
            "deposits eat slyly ironic, even",
        ],
        [
            "4",
            "Customer#000000004",
            "XxVSJsLAGtn",
            "2",
            "14-128-190-5944",
            "2866.83",
            "MACHINERY",
            "n accounts about the fluffily",
        ],
        [
            "5",
            "Customer#000000005",
            "KvpyuHCplrB84WgAiGV6sYpZq7Tj",
            "0",
            "13-750-942-6364",
            "794.47",
            "HOUSEHOLD",
            "g, express deposits according to the",
        ],
    ]

    with open(customer_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(customer_data)

    # Create sample orders data
    orders_file = temp_dir / "orders.csv"
    orders_data = [
        [
            "1",
            "1",
            "O",
            "173665.47",
            "1996-01-02",
            "5-LOW",
            "Clerk#000000951",
            "0",
            "nstructions sleep furiously among",
        ],
        ["2", "2", "O", "46929.18", "1996-12-01", "1-URGENT", "Clerk#000000880", "0", "foxes. pending, express"],
        ["3", "3", "F", "205654.30", "1993-10-14", "5-LOW", "Clerk#000000955", "0", "sly final accounts boost"],
        ["4", "4", "O", "32151.78", "1995-10-11", "5-LOW", "Clerk#000000124", "0", "sits. slyly regular"],
        ["5", "5", "F", "144659.20", "1994-07-30", "5-LOW", "Clerk#000000925", "0", "quickly. bold deposits sleep"],
    ]

    with open(orders_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(orders_data)

    # Create sample lineitem data
    lineitem_file = temp_dir / "lineitem.csv"
    lineitem_data = [
        [
            "1",
            "1",
            "1",
            "1",
            "17",
            "21168.23",
            "0.04",
            "0.02",
            "N",
            "O",
            "1996-03-13",
            "1996-02-12",
            "1996-03-22",
            "DELIVER IN PERSON",
            "TRUCK",
            "egular courts above the",
        ],
        [
            "1",
            "2",
            "2",
            "2",
            "36",
            "45983.16",
            "0.09",
            "0.06",
            "N",
            "O",
            "1996-04-12",
            "1996-02-28",
            "1996-04-20",
            "TAKE BACK RETURN",
            "MAIL",
            "ly final dependencies",
        ],
        [
            "2",
            "3",
            "3",
            "1",
            "8",
            "13309.60",
            "0.10",
            "0.02",
            "N",
            "O",
            "1997-01-28",
            "1997-01-14",
            "1997-02-02",
            "TAKE BACK RETURN",
            "RAIL",
            "uests eat slyly across",
        ],
        [
            "3",
            "4",
            "4",
            "1",
            "45",
            "54058.05",
            "0.06",
            "0.00",
            "R",
            "F",
            "1994-02-02",
            "1994-01-04",
            "1994-02-23",
            "NONE",
            "AIR",
            "ongside of the furiously",
        ],
        [
            "4",
            "5",
            "5",
            "1",
            "49",
            "46796.47",
            "0.10",
            "0.00",
            "R",
            "F",
            "1996-01-10",
            "1995-12-14",
            "1996-01-18",
            "DELIVER IN PERSON",
            "AIR",
            "ar requests. deposits",
        ],
    ]

    with open(lineitem_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(lineitem_data)

    yield temp_dir

    # Cleanup after session
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def tpch_detailed_data_session() -> Generator[Path, None, None]:
    """Create detailed TPC-H sample data once per test session.

    This fixture creates comprehensive TPC-H test data including all standard
    tables with more records for complex query testing.

    Returns:
        Path: Directory containing generated CSV files
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="benchbox_detailed_data_"))

    # Region data
    region_file = temp_dir / "region.csv"
    region_data = [
        [
            "0",
            "AFRICA",
            "lar deposits. blithely final packages cajole. regular waters are final requests. regular accounts are according to",
        ],
        [
            "1",
            "AMERICA",
            "hs use ironic, even requests. platelets haggle slyly. carefully final deposits detect slyly agai",
        ],
        [
            "2",
            "ASIA",
            "ges. thinly even pinto beans ca refully. final, express gifts cajole around the furiously regular foxes",
        ],
        [
            "3",
            "EUROPE",
            "ly final courts cajole furiously final excuse. even, express ideas integrate slyly. regular, express instru",
        ],
        [
            "4",
            "MIDDLE EAST",
            "uickly special requests. carefully final deposits detect slyly against the furiously regular platelets",
        ],
    ]

    with open(region_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(region_data)

    # Nation data (expanded)
    nation_file = temp_dir / "nation.csv"
    nation_data = [
        ["0", "ALGERIA", "0", "haggle. carefully final deposits detect slyly against the furiously regular foxes"],
        ["1", "ARGENTINA", "1", "al foxes promise slyly according to the regular accounts. bold requests alon"],
        [
            "2",
            "BRAZIL",
            "1",
            "y alongside of the pending deposits. carefully special packages are about the ironic forges",
        ],
        ["3", "CANADA", "1", "eas hang ironic, silent packages. slyly regular packages are furiously over the tithes"],
        [
            "4",
            "EGYPT",
            "4",
            "y above the carefully unusual theodolites. final dugouts are quickly across the furiously regular",
        ],
        [
            "5",
            "ETHIOPIA",
            "0",
            "ven packages wake quickly. riously final dugouts are furiously regular. express waters are carefully",
        ],
        [
            "6",
            "FRANCE",
            "3",
            "refully final requests. regular, ironic theodolites are according to the carefully bold packages",
        ],
        [
            "7",
            "GERMANY",
            "3",
            "l platelets. regular accounts x-ray: unusual, regular requests according to the furiously regular deposits",
        ],
        [
            "8",
            "INDIA",
            "2",
            "ss excuses cajole slyly across the packages. deposits print aroun the carefully regular deposits",
        ],
        ["9", "INDONESIA", "2", "slyly express asymptotes. regular deposits haggle slyly. carefully ironic hockey"],
    ]

    with open(nation_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(nation_data)

    # Supplier data
    supplier_file = temp_dir / "supplier.csv"
    supplier_data = [
        [
            "1",
            "Supplier#000000001",
            "N kD4on9OM Ipw3,gf0JBoQDd7tgrzrddZ",
            "7",
            "27-918-335-1736",
            "5755.94",
            "each slyly above the careful",
        ],
        [
            "2",
            "Supplier#000000002",
            "89eJ5ksX3ImxJQBvxObC,",
            "5",
            "15-679-861-2259",
            "4032.68",
            "slyly bold instructions. idle dependen",
        ],
        [
            "3",
            "Supplier#000000003",
            "q1,G3Pj6OjIuUYfUoH18BFTKP5aU9bEV3",
            "1",
            "11-383-516-1199",
            "4192.40",
            "blithely silent requests after the exp",
        ],
        [
            "4",
            "Supplier#000000004",
            "Bk7ah4CK8SYQTepEmvMkkgMwg",
            "0",
            "25-843-787-7479",
            "4641.08",
            "riously even requests above the exp",
        ],
        [
            "5",
            "Supplier#000000005",
            "gcdm2rJRzl5qlTVzc",
            "2",
            "21-151-690-3663",
            "-283.84",
            "regular deposits above the even packages",
        ],
    ]

    with open(supplier_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(supplier_data)

    # Part data
    part_file = temp_dir / "part.csv"
    part_data = [
        [
            "1",
            "goldenrod lavender spring chocolate lace",
            "Manufacturer#1",
            "Brand#13",
            "PROMO BURNISHED COPPER",
            "7",
            "JUMBO PKG",
            "901.00",
            "ly. slyly ironic requests are furiously",
        ],
        [
            "2",
            "blush thistle blue yellow saddle",
            "Manufacturer#1",
            "Brand#13",
            "LARGE BRUSHED BRASS",
            "1",
            "LG CASE",
            "902.00",
            "ular accounts are quickly",
        ],
        [
            "3",
            "spring green yellow purple cornsilk",
            "Manufacturer#4",
            "Brand#42",
            "STANDARD POLISHED BRASS",
            "21",
            "WRAP CASE",
            "903.00",
            "egular deposits hinder furiously",
        ],
        [
            "4",
            "cornflower chocolate smoke green pink",
            "Manufacturer#3",
            "Brand#34",
            "SMALL PLATED BRASS",
            "14",
            "MED DRUM",
            "904.00",
            "p furiously special foxes",
        ],
        [
            "5",
            "forest brown coral puff cream",
            "Manufacturer#3",
            "Brand#32",
            "STANDARD POLISHED TIN",
            "15",
            "SM PKG",
            "905.00",
            "wake fluffily alongside of the regular",
        ],
    ]

    with open(part_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(part_data)

    # Customer data (expanded with 10 customers)
    customer_file = temp_dir / "customer.csv"
    customer_data = [
        [
            "1",
            "Customer#000000001",
            "IVhzIApeRb ot,c,E",
            "0",
            "25-989-741-2988",
            "711.56",
            "BUILDING",
            "to the even, regular platelets. regular, ironic epitaphs nag e",
        ],
        [
            "2",
            "Customer#000000002",
            "XSTf4,NCwDVaWNe6tEgvwfmRchLXak",
            "1",
            "23-768-687-3665",
            "121.65",
            "AUTOMOBILE",
            "l accounts. even, express packages wake about the slyly fina",
        ],
        [
            "3",
            "Customer#000000003",
            "MG9kdTD2WBHm",
            "1",
            "11-719-748-3364",
            "7498.12",
            "AUTOMOBILE",
            "deposits eat slyly ironic, even instructions. express foxes det",
        ],
        [
            "4",
            "Customer#000000004",
            "XxVSJsLAGtn",
            "4",
            "14-128-190-5944",
            "2866.83",
            "MACHINERY",
            "requests. final, regular ideas sleep final accou",
        ],
        [
            "5",
            "Customer#000000005",
            "KvpyuHCplrB84WgAiGV6sYpZq7Tj",
            "3",
            "13-750-942-6364",
            "794.47",
            "HOUSEHOLD",
            "g to the carefully final braids. blithely regular requests nag. slyly express",
        ],
        [
            "6",
            "Customer#000000006",
            "sKZz0CsnMD7mp4Xd0YrBvx,LREYKUWAh yVn",
            "2",
            "30-114-968-4951",
            "7638.57",
            "AUTOMOBILE",
            "tions. even deposits boost according to the slyly bold packages. final accoun",
        ],
        [
            "7",
            "Customer#000000007",
            "TcGe5gaZNgVePxU5kRrvXBfkasDTea",
            "8",
            "28-190-982-9759",
            "9561.95",
            "AUTOMOBILE",
            "ainst the ironic, express theodolites. express, even pinto beans among",
        ],
        [
            "8",
            "Customer#000000008",
            "I0B10bB0AymmC, 0PrRYBCP1yGJ8xcBPmWhl5",
            "7",
            "27-147-574-9335",
            "6819.74",
            "BUILDING",
            "among the slyly regular theodolites kindle blithely courts. carefully even theodo",
        ],
        [
            "9",
            "Customer#000000009",
            "xKiAFTjUsCuxfeleNqefumTrjS",
            "8",
            "18-338-906-3675",
            "8324.07",
            "MACHINERY",
            "r theodolites according to the requests wake slyly alongside of the pending deposits using",
        ],
        [
            "10",
            "Customer#000000010",
            "6LrEaV6KR6PLVcgl2ArL Q3rqzLzcT1 v2",
            "5",
            "15-741-346-9870",
            "2753.54",
            "HOUSEHOLD",
            "es regular deposits haggle. fur",
        ],
    ]

    with open(customer_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(customer_data)

    # Orders data (expanded with 10 orders)
    orders_file = temp_dir / "orders.csv"
    orders_data = [
        [
            "1",
            "1",
            "O",
            "173665.47",
            "1996-01-02",
            "5-LOW",
            "Clerk#000000951",
            "0",
            "nstructions sleep furiously among",
        ],
        [
            "2",
            "2",
            "O",
            "46929.18",
            "1996-12-01",
            "1-URGENT",
            "Clerk#000000880",
            "0",
            "foxes. pending, express instructions affix",
        ],
        [
            "3",
            "3",
            "F",
            "205654.30",
            "1993-10-14",
            "5-LOW",
            "Clerk#000000955",
            "0",
            "sly final accounts boost. carefully regular ideas cajole carefully",
        ],
        [
            "4",
            "4",
            "O",
            "32151.78",
            "1995-10-11",
            "5-LOW",
            "Clerk#000000124",
            "0",
            "sits. slyly regular warthogs cajole. regular, regular theodolites",
        ],
        [
            "5",
            "5",
            "F",
            "144659.20",
            "1994-07-30",
            "5-LOW",
            "Clerk#000000925",
            "0",
            "quickly. bold deposits sleep slyly. packages use slyly",
        ],
        [
            "6",
            "6",
            "F",
            "58749.59",
            "1992-02-21",
            "4-NOT SPECIFIED",
            "Clerk#000000058",
            "0",
            "ggle. special, final requests are against the furiously specia",
        ],
        [
            "7",
            "7",
            "O",
            "252004.18",
            "1996-01-10",
            "2-HIGH",
            "Clerk#000000470",
            "0",
            "ly special requests are furiously across the express, final requests",
        ],
        [
            "32",
            "8",
            "O",
            "208660.75",
            "1995-07-16",
            "2-HIGH",
            "Clerk#000000616",
            "0",
            "ise blithely bold, regular requests. quickly unusual dep",
        ],
        [
            "33",
            "9",
            "F",
            "163243.98",
            "1993-10-27",
            "3-MEDIUM",
            "Clerk#000000409",
            "0",
            "uriously. furiously final request",
        ],
        [
            "34",
            "10",
            "O",
            "40340.78",
            "1998-07-21",
            "3-MEDIUM",
            "Clerk#000000223",
            "0",
            "ly final packages. fluffily final deposits wake blithely ideas",
        ],
    ]

    with open(orders_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(orders_data)

    # PartSupp data
    partsupp_file = temp_dir / "partsupp.csv"
    partsupp_data = [
        ["1", "1", "325", "771.64", "even, express ideas haggle blithely"],
        ["1", "2", "1000", "993.49", "ven ideas. quickly, final packages across the furiously regular"],
        ["2", "1", "1500", "402.35", "furiously pending notornis"],
        ["2", "2", "2000", "352.94", "regular, ironic packages across the unusual, even theodolites"],
        ["3", "1", "750", "357.84", "ironic, unusual deposits. express, pending packages cajole"],
        ["3", "2", "1250", "76.17", "blithely pending dolphins use even, express frets"],
        ["4", "1", "1200", "762.23", "unusual, regular packages wake. slyly regular packages"],
        ["4", "2", "1100", "365.96", "carefully regular deposits. blithely ironic packages"],
    ]

    with open(partsupp_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(partsupp_data)

    # Lineitem data (expanded)
    lineitem_file = temp_dir / "lineitem.csv"
    lineitem_data = [
        [
            "1",
            "1",
            "1",
            "1",
            "17",
            "21168.23",
            "0.04",
            "0.02",
            "N",
            "O",
            "1996-03-13",
            "1996-02-12",
            "1996-03-22",
            "DELIVER IN PERSON",
            "TRUCK",
            "egular courts above the",
        ],
        [
            "1",
            "2",
            "2",
            "2",
            "36",
            "45983.16",
            "0.09",
            "0.06",
            "N",
            "O",
            "1996-04-12",
            "1996-02-28",
            "1996-04-20",
            "TAKE BACK RETURN",
            "MAIL",
            "ly final dependencies",
        ],
        [
            "2",
            "3",
            "3",
            "1",
            "38",
            "44694.46",
            "0.00",
            "0.05",
            "N",
            "O",
            "1997-01-28",
            "1997-01-14",
            "1997-02-02",
            "TAKE BACK RETURN",
            "RAIL",
            "uests eat slyly across",
        ],
        [
            "3",
            "4",
            "4",
            "1",
            "45",
            "54058.05",
            "0.06",
            "0.00",
            "R",
            "F",
            "1994-02-02",
            "1994-01-04",
            "1994-02-23",
            "NONE",
            "AIR",
            "ongside of the furiously",
        ],
        [
            "4",
            "5",
            "5",
            "1",
            "30",
            "28955.25",
            "0.03",
            "0.05",
            "N",
            "O",
            "1996-01-10",
            "1995-12-14",
            "1996-01-18",
            "DELIVER IN PERSON",
            "AIR",
            "ar requests. deposits",
        ],
        [
            "5",
            "1",
            "1",
            "1",
            "15",
            "22734.81",
            "0.02",
            "0.04",
            "R",
            "F",
            "1994-08-17",
            "1994-08-06",
            "1994-08-25",
            "NONE",
            "AIR",
            "w pinto beans nag",
        ],
        [
            "6",
            "2",
            "2",
            "1",
            "34",
            "43058.34",
            "0.09",
            "0.04",
            "R",
            "F",
            "1992-04-27",
            "1992-05-15",
            "1992-05-02",
            "TAKE BACK RETURN",
            "TRUCK",
            "p furiously special foxes",
        ],
        [
            "7",
            "3",
            "3",
            "1",
            "12",
            "22824.48",
            "0.07",
            "0.03",
            "N",
            "O",
            "1996-02-01",
            "1996-01-02",
            "1996-02-19",
            "DELIVER IN PERSON",
            "MAIL",
            "ly alongside of the pending",
        ],
        [
            "32",
            "4",
            "4",
            "1",
            "28",
            "47227.52",
            "0.05",
            "0.08",
            "N",
            "O",
            "1995-10-23",
            "1995-08-27",
            "1995-10-26",
            "TAKE BACK RETURN",
            "TRUCK",
            "sleep quickly. req",
        ],
        [
            "33",
            "5",
            "5",
            "1",
            "36",
            "60449.16",
            "0.02",
            "0.00",
            "R",
            "F",
            "1993-11-09",
            "1993-12-20",
            "1993-11-24",
            "TAKE BACK RETURN",
            "MAIL",
            "unusual accounts. eve",
        ],
        [
            "34",
            "1",
            "1",
            "1",
            "13",
            "22824.68",
            "0.00",
            "0.07",
            "N",
            "O",
            "1998-10-23",
            "1998-09-14",
            "1998-11-06",
            "NONE",
            "AIR",
            "lar accounts nag carefully",
        ],
        [
            "34",
            "2",
            "2",
            "2",
            "22",
            "35271.10",
            "0.08",
            "0.06",
            "N",
            "O",
            "1998-10-09",
            "1998-10-16",
            "1998-10-12",
            "NONE",
            "FOB",
            "deposits are slyly alongside",
        ],
    ]

    with open(lineitem_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(lineitem_data)

    yield temp_dir

    # Cleanup after session
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_data_dir(tpch_sample_data_session: Path) -> Path:
    """Provide per-test access to session-scoped sample data.

    This function-scoped fixture provides access to the session-scoped data
    directory, making it easy to use in tests without changing test signatures.

    Args:
        tpch_sample_data_session: Session-scoped fixture with sample data

    Returns:
        Path: Directory containing sample CSV files
    """
    return tpch_sample_data_session


@pytest.fixture
def detailed_data_dir(tpch_detailed_data_session: Path) -> Path:
    """Provide per-test access to session-scoped detailed data.

    This function-scoped fixture provides access to the session-scoped detailed
    data directory, making it easy to use in tests without changing test signatures.

    Args:
        tpch_detailed_data_session: Session-scoped fixture with detailed data

    Returns:
        Path: Directory containing detailed CSV files
    """
    return tpch_detailed_data_session
