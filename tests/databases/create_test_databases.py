#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import sys
from pathlib import Path

import duckdb

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def create_basic_test_database(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))

    conn.execute("""
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name VARCHAR(50),
            value DECIMAL(10,2),
            created_date DATE
        )
    """)

    conn.execute("""
        INSERT INTO test_table VALUES
        (1, 'test_record_1', 100.50, '2023-01-01'),
        (2, 'test_record_2', 200.75, '2023-01-02'),
        (3, 'test_record_3', 300.25, '2023-01-03')
    """)

    conn.execute("""
        CREATE TABLE test_metadata (
            test_id INTEGER,
            category VARCHAR(20),
            description TEXT
        )
    """)

    conn.execute("""
        INSERT INTO test_metadata VALUES
        (1, 'category_a', 'Description for test record 1'),
        (2, 'category_b', 'Description for test record 2'),
        (3, 'category_a', 'Description for test record 3')
    """)

    conn.close()


def create_tpch_test_database(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))

    conn.execute("""
        CREATE TABLE region (
            r_regionkey INTEGER PRIMARY KEY,
            r_name VARCHAR(25),
            r_comment VARCHAR(152)
        )
    """)

    conn.execute("""
        INSERT INTO region VALUES
        (0, 'AFRICA', 'lar deposits. blithely final packages cajole'),
        (1, 'AMERICA', 'hs use ironic, even requests'),
        (2, 'ASIA', 'ges. thinly even pinto beans ca'),
        (3, 'EUROPE', 'ly final courts cajole furiously'),
        (4, 'MIDDLE EAST', 'uickly special requests')
    """)

    conn.execute("""
        CREATE TABLE nation (
            n_nationkey INTEGER PRIMARY KEY,
            n_name VARCHAR(25),
            n_regionkey INTEGER,
            n_comment VARCHAR(152)
        )
    """)

    conn.execute("""
        INSERT INTO nation VALUES
        (0, 'ALGERIA', 0, 'haggle. carefully final deposits detect slyly'),
        (1, 'ARGENTINA', 1, 'al foxes promise slyly according to the regular accounts'),
        (2, 'BRAZIL', 1, 'y alongside of the pending deposits'),
        (3, 'CANADA', 1, 'eas hang ironic, silent packages'),
        (4, 'EGYPT', 4, 'y above the carefully unusual theodolites'),
        (5, 'ETHIOPIA', 0, 'ven packages wake quickly'),
        (6, 'FRANCE', 3, 'refully final requests'),
        (7, 'GERMANY', 3, 'l platelets'),
        (8, 'INDIA', 2, 'ss excuses cajole slyly across the packages'),
        (9, 'INDONESIA', 2, 'slyly express asymptotes')
    """)

    conn.execute("""
        CREATE TABLE customer (
            c_custkey INTEGER PRIMARY KEY,
            c_name VARCHAR(25),
            c_address VARCHAR(40),
            c_nationkey INTEGER,
            c_phone VARCHAR(15),
            c_acctbal DECIMAL(15,2),
            c_mktsegment VARCHAR(10),
            c_comment VARCHAR(117)
        )
    """)

    conn.execute("""
        INSERT INTO customer VALUES
        (1, 'Customer#000000001', 'IVhzIApeRb ot,c,E', 15, '25-989-741-2988', 711.56, 'BUILDING', 'to the even, regular platelets'),
        (2, 'Customer#000000002', 'XSTf4,NCwDVaWNe6tEgvwfmRchLXak', 13, '23-768-687-3665', 121.65, 'AUTOMOBILE', 'l accounts'),
        (3, 'Customer#000000003', 'MG9kdTD2WBHm', 1, '11-719-748-3364', 7498.12, 'AUTOMOBILE', 'deposits eat slyly ironic, even instructions')
    """)

    conn.execute("""
        CREATE TABLE supplier (
            s_suppkey INTEGER PRIMARY KEY,
            s_name VARCHAR(25),
            s_address VARCHAR(40),
            s_nationkey INTEGER,
            s_phone VARCHAR(15),
            s_acctbal DECIMAL(15,2),
            s_comment VARCHAR(101)
        )
    """)

    conn.execute("""
        INSERT INTO supplier VALUES
        (1, 'Supplier#000000001', 'N kD4on9OM Ipw3,gf0JBoQDd7tgrzrddZ', 17, '27-918-335-1736', 5755.94, 'each slyly above the careful'),
        (2, 'Supplier#000000002', '89eJ5ksX3ImxJQBvxObC,', 5, '15-679-861-2259', 4032.68, 'furiously stealthy frays'),
        (3, 'Supplier#000000003', 'q1,G3Pj6OjIuUYfUoH18BFTKP5aU9bEV3', 1, '11-383-516-1199', 4192.40, 'blithely silent requests')
    """)

    conn.execute("""
        CREATE TABLE part (
            p_partkey INTEGER PRIMARY KEY,
            p_name VARCHAR(55),
            p_mfgr VARCHAR(25),
            p_brand VARCHAR(10),
            p_type VARCHAR(25),
            p_size INTEGER,
            p_container VARCHAR(10),
            p_retailprice DECIMAL(15,2),
            p_comment VARCHAR(23)
        )
    """)

    conn.execute("""
        INSERT INTO part VALUES
        (1, 'goldenrod lavender spring chocolate lace', 'Manufacturer#1', 'Brand#13', 'PROMO BURNISHED COPPER', 7, 'JUMBO PKG', 901.00, 'ly. slyly ironic'),
        (2, 'blush thistle blue yellow saddle', 'Manufacturer#1', 'Brand#13', 'LARGE BRUSHED BRASS', 1, 'LG CASE', 902.00, 'lar accounts hang'),
        (3, 'spring green yellow purple cornsilk', 'Manufacturer#4', 'Brand#42', 'STANDARD POLISHED BRASS', 21, 'WRAP CASE', 903.00, 'egular deposits hag')
    """)

    conn.execute("""
        CREATE TABLE partsupp (
            ps_partkey INTEGER,
            ps_suppkey INTEGER,
            ps_availqty INTEGER,
            ps_supplycost DECIMAL(15,2),
            ps_comment VARCHAR(199),
            PRIMARY KEY (ps_partkey, ps_suppkey)
        )
    """)

    conn.execute("""
        INSERT INTO partsupp VALUES
        (1, 1, 3325, 771.64, 'final excuses'),
        (1, 2, 8076, 993.49, 'ven ideas'),
        (2, 1, 4069, 337.09, 'ironic, even requests'),
        (2, 3, 4809, 357.84, 'iro dependencies'),
        (3, 1, 4651, 804.15, 'final dependencies'),
        (3, 2, 6377, 471.15, 'express deposits')
    """)

    conn.execute("""
        CREATE TABLE orders (
            o_orderkey INTEGER PRIMARY KEY,
            o_custkey INTEGER,
            o_orderstatus VARCHAR(1),
            o_totalprice DECIMAL(15,2),
            o_orderdate DATE,
            o_orderpriority VARCHAR(15),
            o_clerk VARCHAR(15),
            o_shippriority INTEGER,
            o_comment VARCHAR(79)
        )
    """)

    conn.execute("""
        INSERT INTO orders VALUES
        (1, 1, 'O', 173665.47, '1996-01-02', '5-LOW', 'Clerk#000000951', 0, 'nstructions sleep furiously among'),
        (2, 2, 'O', 46929.18, '1996-12-01', '1-URGENT', 'Clerk#000000880', 0, 'foxes. pending accounts'),
        (3, 3, 'F', 205654.30, '1993-10-14', '5-LOW', 'Clerk#000000955', 0, 'sly final accounts boost'),
        (4, 1, 'O', 56000.91, '1995-10-11', '5-LOW', 'Clerk#000000124', 0, 'sits. slyly regular warthogs'),
        (5, 2, 'F', 105367.67, '1994-07-30', '5-LOW', 'Clerk#000000925', 0, 'quickly. bold deposits sleep')
    """)

    conn.execute("""
        CREATE TABLE lineitem (
            l_orderkey INTEGER,
            l_partkey INTEGER,
            l_suppkey INTEGER,
            l_linenumber INTEGER,
            l_quantity DECIMAL(15,2),
            l_extendedprice DECIMAL(15,2),
            l_discount DECIMAL(15,2),
            l_tax DECIMAL(15,2),
            l_returnflag VARCHAR(1),
            l_linestatus VARCHAR(1),
            l_shipdate DATE,
            l_commitdate DATE,
            l_receiptdate DATE,
            l_shipinstruct VARCHAR(25),
            l_shipmode VARCHAR(10),
            l_comment VARCHAR(44),
            PRIMARY KEY (l_orderkey, l_linenumber)
        )
    """)

    conn.execute("""
        INSERT INTO lineitem VALUES
        (1, 1, 1, 1, 17.00, 21168.23, 0.04, 0.02, 'N', 'O', '1996-03-13', '1996-02-12', '1996-03-22', 'DELIVER IN PERSON', 'TRUCK', 'egular courts above the'),
        (1, 2, 2, 2, 36.00, 45983.16, 0.09, 0.06, 'N', 'O', '1996-04-12', '1996-02-28', '1996-04-20', 'TAKE BACK RETURN', 'MAIL', 'ly final dependencies'),
        (2, 3, 3, 1, 38.00, 44694.46, 0.00, 0.05, 'N', 'O', '1997-01-28', '1997-01-14', '1997-02-02', 'TAKE BACK RETURN', 'RAIL', 'ven requests'),
        (3, 1, 1, 1, 45.00, 54058.05, 0.06, 0.00, 'R', 'F', '1994-02-02', '1994-01-04', '1994-02-23', 'NONE', 'AIR', 'ongside of the furiously'),
        (3, 2, 2, 2, 49.00, 46796.47, 0.10, 0.00, 'R', 'F', '1993-11-09', '1993-12-20', '1993-11-24', 'TAKE BACK RETURN', 'RAIL', 'unusual accounts')
    """)

    conn.close()


def create_tpcds_test_database(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))

    conn.execute("""
        CREATE TABLE call_center (
            cc_call_center_sk INTEGER PRIMARY KEY,
            cc_call_center_id VARCHAR(16),
            cc_name VARCHAR(50),
            cc_class VARCHAR(50)
        )
    """)

    conn.execute("""
        INSERT INTO call_center VALUES
        (1, 'AAAAAAAABAAAAAAA', 'NY Metro', 'large'),
        (2, 'AAAAAAAACAAAAAAA', 'Mid Atlantic', 'medium'),
        (3, 'AAAAAAAADAAAAAAA', 'North Central', 'small')
    """)

    conn.execute("""
        CREATE TABLE catalog_page (
            cp_catalog_page_sk INTEGER PRIMARY KEY,
            cp_catalog_page_id VARCHAR(16),
            cp_department VARCHAR(50),
            cp_type VARCHAR(100)
        )
    """)

    conn.execute("""
        INSERT INTO catalog_page VALUES
        (1, 'AAAAAAAABAAAAAAA', 'ELECTRONICS', 'bi-annual'),
        (2, 'AAAAAAAACAAAAAAA', 'CLOTHING', 'quarterly'),
        (3, 'AAAAAAAADAAAAAAA', 'HOME', 'monthly')
    """)

    conn.execute("""
        CREATE TABLE date_dim (
            d_date_sk INTEGER PRIMARY KEY,
            d_date_id VARCHAR(16),
            d_date DATE,
            d_month_seq INTEGER,
            d_week_seq INTEGER,
            d_quarter_seq INTEGER,
            d_year INTEGER,
            d_dow INTEGER,
            d_moy INTEGER,
            d_dom INTEGER,
            d_qoy INTEGER,
            d_fy_year INTEGER,
            d_fy_quarter_seq INTEGER,
            d_fy_week_seq INTEGER,
            d_day_name VARCHAR(9),
            d_quarter_name VARCHAR(6),
            d_holiday VARCHAR(1),
            d_weekend VARCHAR(1),
            d_following_holiday VARCHAR(1),
            d_first_dom INTEGER,
            d_last_dom INTEGER,
            d_same_day_ly INTEGER,
            d_same_day_lq INTEGER,
            d_current_day VARCHAR(1),
            d_current_week VARCHAR(1),
            d_current_month VARCHAR(1),
            d_current_quarter VARCHAR(1),
            d_current_year VARCHAR(1)
        )
    """)

    conn.execute("""
        INSERT INTO date_dim VALUES
        (1, 'AAAAAAAABAAAAAAA', '1998-01-01', 1, 1, 1, 1998, 5, 1, 1, 1, 1998, 1, 1, 'Thursday', '1998Q1', 'N', 'N', 'N', 1, 31, 0, 0, 'N', 'N', 'N', 'N', 'N'),
        (2, 'AAAAAAAACAAAAAAA', '1998-01-02', 1, 1, 1, 1998, 6, 1, 2, 1, 1998, 1, 1, 'Friday', '1998Q1', 'N', 'N', 'N', 1, 31, 0, 0, 'N', 'N', 'N', 'N', 'N'),
        (3, 'AAAAAAAADAAAAAAA', '1998-01-03', 1, 1, 1, 1998, 7, 1, 3, 1, 1998, 1, 1, 'Saturday', '1998Q1', 'N', 'Y', 'N', 1, 31, 0, 0, 'N', 'N', 'N', 'N', 'N')
    """)

    conn.close()


def create_ssb_test_database(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))

    conn.execute("""
        CREATE TABLE date (
            d_datekey INTEGER PRIMARY KEY,
            d_date VARCHAR(18),
            d_dayofweek VARCHAR(9),
            d_month VARCHAR(9),
            d_year INTEGER,
            d_yearmonthnum INTEGER,
            d_yearmonth VARCHAR(7),
            d_daynuminweek INTEGER,
            d_daynuminmonth INTEGER,
            d_daynuminyear INTEGER,
            d_monthnuminyear INTEGER,
            d_weeknuminyear INTEGER,
            d_sellingseason VARCHAR(12),
            d_lastdayinweekfl VARCHAR(1),
            d_lastdayinmonthfl VARCHAR(1),
            d_holidayfl VARCHAR(1),
            d_weekdayfl VARCHAR(1)
        )
    """)

    conn.execute("""
        INSERT INTO date VALUES
        (19920101, 'January 1, 1992', 'Wednesday', 'January', 1992, 199201, 'Jan1992', 4, 1, 1, 1, 1, 'Winter', 'N', 'N', 'Y', 'Y'),
        (19920102, 'January 2, 1992', 'Thursday', 'January', 1992, 199201, 'Jan1992', 5, 2, 2, 1, 1, 'Winter', 'N', 'N', 'N', 'Y'),
        (19920103, 'January 3, 1992', 'Friday', 'January', 1992, 199201, 'Jan1992', 6, 3, 3, 1, 1, 'Winter', 'N', 'N', 'N', 'Y')
    """)

    conn.execute("""
        CREATE TABLE customer (
            c_custkey INTEGER PRIMARY KEY,
            c_name VARCHAR(25),
            c_address VARCHAR(40),
            c_city VARCHAR(10),
            c_nation VARCHAR(15),
            c_region VARCHAR(12),
            c_phone VARCHAR(15),
            c_mktsegment VARCHAR(10)
        )
    """)

    conn.execute("""
        INSERT INTO customer VALUES
        (1, 'Customer#000000001', 'IVhzIApeRb ot,c,E', 'ALGERIA', 'ALGERIA', 'AFRICA', '25-989-741-2988', 'BUILDING'),
        (2, 'Customer#000000002', 'XSTf4,NCwDVaWNe6tEgvwfmRchLXak', 'ARGENTINA', 'ARGENTINA', 'AMERICA', '23-768-687-3665', 'AUTOMOBILE'),
        (3, 'Customer#000000003', 'MG9kdTD2WBHm', 'BRAZIL', 'BRAZIL', 'AMERICA', '11-719-748-3364', 'AUTOMOBILE')
    """)

    conn.execute("""
        CREATE TABLE part (
            p_partkey INTEGER PRIMARY KEY,
            p_name VARCHAR(22),
            p_mfgr VARCHAR(6),
            p_category VARCHAR(7),
            p_brand1 VARCHAR(9),
            p_color VARCHAR(11),
            p_type VARCHAR(25),
            p_size INTEGER,
            p_container VARCHAR(10)
        )
    """)

    conn.execute("""
        INSERT INTO part VALUES
        (1, 'goldenrod lavender', 'MFGR#1', 'MFGR#11', 'MFGR#111', 'goldenrod', 'PROMO BURNISHED COPPER', 7, 'JUMBO PKG'),
        (2, 'blush thistle blue', 'MFGR#1', 'MFGR#11', 'MFGR#112', 'blush', 'LARGE BRUSHED BRASS', 1, 'LG CASE'),
        (3, 'spring green yellow', 'MFGR#4', 'MFGR#44', 'MFGR#441', 'spring', 'STANDARD POLISHED BRASS', 21, 'WRAP CASE')
    """)

    conn.execute("""
        CREATE TABLE supplier (
            s_suppkey INTEGER PRIMARY KEY,
            s_name VARCHAR(25),
            s_address VARCHAR(40),
            s_city VARCHAR(10),
            s_nation VARCHAR(15),
            s_region VARCHAR(12),
            s_phone VARCHAR(15)
        )
    """)

    conn.execute("""
        INSERT INTO supplier VALUES
        (1, 'Supplier#000000001', 'N kD4on9OM Ipw3,gf0JBoQDd7tgrzrddZ', 'ALGERIA', 'ALGERIA', 'AFRICA', '27-918-335-1736'),
        (2, 'Supplier#000000002', '89eJ5ksX3ImxJQBvxObC,', 'ETHIOPIA', 'ETHIOPIA', 'AFRICA', '15-679-861-2259'),
        (3, 'Supplier#000000003', 'q1,G3Pj6OjIuUYfUoH18BFTKP5aU9bEV3', 'ARGENTINA', 'ARGENTINA', 'AMERICA', '11-383-516-1199')
    """)

    conn.execute("""
        CREATE TABLE lineorder (
            lo_orderkey INTEGER,
            lo_linenumber INTEGER,
            lo_custkey INTEGER,
            lo_partkey INTEGER,
            lo_suppkey INTEGER,
            lo_orderdate INTEGER,
            lo_orderpriority VARCHAR(15),
            lo_shippriority VARCHAR(1),
            lo_quantity INTEGER,
            lo_extendedprice INTEGER,
            lo_ordtotalprice INTEGER,
            lo_discount INTEGER,
            lo_revenue INTEGER,
            lo_supplycost INTEGER,
            lo_tax INTEGER,
            lo_commitdate INTEGER,
            lo_shipmode VARCHAR(10),
            PRIMARY KEY (lo_orderkey, lo_linenumber)
        )
    """)

    conn.execute("""
        INSERT INTO lineorder VALUES
        (1, 1, 1, 1, 1, 19920101, '5-LOW', '0', 17, 2116823, 17366547, 4, 2032310, 77164, 42336, 19920212, 'TRUCK'),
        (1, 2, 1, 2, 2, 19920101, '5-LOW', '0', 36, 4598316, 17366547, 9, 4184567, 33709, 275898, 19920228, 'MAIL'),
        (2, 1, 2, 3, 3, 19920102, '1-URGENT', '0', 38, 4469446, 4692918, 0, 4469446, 80415, 223472, 19920114, 'RAIL')
    """)

    conn.close()


def create_primitives_test_database(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))

    conn.execute("""
        CREATE TABLE sales_data (
            id INTEGER PRIMARY KEY,
            product VARCHAR(50),
            category VARCHAR(20),
            region VARCHAR(20),
            sales_amount DECIMAL(15,2),
            quantity INTEGER,
            sale_date DATE
        )
    """)

    conn.execute("""
        INSERT INTO sales_data VALUES
        (1, 'Product A', 'Electronics', 'North', 1000.00, 10, '2023-01-01'),
        (2, 'Product B', 'Electronics', 'South', 1500.00, 15, '2023-01-02'),
        (3, 'Product C', 'Clothing', 'North', 800.00, 8, '2023-01-03'),
        (4, 'Product D', 'Clothing', 'South', 1200.00, 12, '2023-01-04'),
        (5, 'Product A', 'Electronics', 'North', 1100.00, 11, '2023-01-05'),
        (6, 'Product B', 'Electronics', 'South', 1600.00, 16, '2023-01-06'),
        (7, 'Product C', 'Clothing', 'North', 850.00, 9, '2023-01-07'),
        (8, 'Product D', 'Clothing', 'South', 1300.00, 13, '2023-01-08')
    """)

    conn.execute("""
        CREATE TABLE time_periods (
            date_key DATE PRIMARY KEY,
            year INTEGER,
            quarter INTEGER,
            month INTEGER,
            day_of_week INTEGER,
            is_weekend BOOLEAN
        )
    """)

    conn.execute("""
        INSERT INTO time_periods VALUES
        ('2023-01-01', 2023, 1, 1, 1, false),
        ('2023-01-02', 2023, 1, 1, 2, false),
        ('2023-01-03', 2023, 1, 1, 3, false),
        ('2023-01-04', 2023, 1, 1, 4, false),
        ('2023-01-05', 2023, 1, 1, 5, false),
        ('2023-01-06', 2023, 1, 1, 6, false),
        ('2023-01-07', 2023, 1, 1, 7, true),
        ('2023-01-08', 2023, 1, 1, 1, false)
    """)

    conn.close()


def main():
    databases_dir = Path(__file__).parent

    databases = [
        ("basic_test.duckdb", create_basic_test_database),
        ("tpch_test.duckdb", create_tpch_test_database),
        ("tpcds_test.duckdb", create_tpcds_test_database),
        ("ssb_test.duckdb", create_ssb_test_database),
        ("primitives_test.duckdb", create_primitives_test_database),
    ]

    print("Creating test databases...")

    for db_name, create_func in databases:
        db_path = databases_dir / db_name
        print(f"Creating {db_name}...")
        try:
            create_func(db_path)
            print(f"✅ Created {db_name}")
        except Exception as e:
            print(f"❌ Failed to create {db_name}: {e}")
            return 1

    print("\nAll test databases created successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
