"""TPC-DI source system data generators.

This module generates source system data files for the TPC-DI benchmark,
simulating the various source systems that feed into a financial services
data warehouse. Unlike the main generator.py which creates target warehouse
data, this module creates realistic source data in various formats that
would typically be processed through ETL pipelines.

The TPC-DI benchmark simulates data from these source systems:
- OLTP Database extracts (customer transactions, account changes)
- HR System (employee/broker data)
- CRM System (customer relationship data)
- External Data Providers (market prices, tax rates)

Each source system generates data in different formats:
- CSV files with different delimiters
- XML hierarchical data
- Fixed-width legacy formats
- JSON for modern APIs

The data generated is realistic for the financial services domain and includes
proper data quality issues, temporal consistency, and referential integrity
that ETL processes must handle.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import random
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def _lines(values: str) -> list[str]:
    return [line.strip() for line in values.splitlines() if line.strip()]


class TPCDISourceDataGenerator:
    """Generator for TPC-DI source system data files.

    This class generates realistic source data files that simulate the various
    systems feeding into a financial services data warehouse. The data includes
    intentional data quality issues and realistic patterns found in real-world
    source systems.

    Attributes:
        scale_factor: Scale factor for data generation (1.0 = standard size)
        output_dir: Directory to write generated data files
        start_date: Start date for temporal data generation
        end_date: End date for temporal data generation
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Path] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ):
        """Initialize the TPC-DI source data generator.

        Args:
            scale_factor: Scale factor for data generation (1.0 = standard size)
            output_dir: Directory to write generated data files
            start_date: Start date for temporal data (defaults to 2020-01-01)
            end_date: End date for temporal data (defaults to 2023-12-31)
        """
        self.scale_factor = scale_factor
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()

        # Date range for temporal data
        self.start_date = start_date or date(2020, 1, 1)
        self.end_date = end_date or date(2023, 12, 31)

        # Base record counts (scale_factor = 1.0)
        self.base_customers = 50000
        self.base_accounts = 100000
        self.base_trades = 1000000
        self.base_companies = 1000
        self.base_securities = 10000
        self.base_brokers = 500
        self.base_tax_rates = 100
        self.base_market_prices = 1000000

        # Initialize random seed for reproducible data
        random.seed(42)

        # Reference data for realistic generation
        self._init_reference_data()

    def _init_reference_data(self) -> None:
        """Initialize reference data for realistic data generation."""
        self.industries = _lines(
            """
            Technology
            Healthcare
            Financial Services
            Manufacturing
            Retail
            Energy
            Telecommunications
            Transportation
            Real Estate
            Media
            Utilities
            Consumer Goods
            Biotechnology
            Aerospace
            Automotive
            Insurance
            """
        )
        self.company_suffixes = _lines("Inc.\nCorp.\nLLC\nLtd.\nCo.\nGroup\nHoldings")
        self.exchanges = _lines("NYSE\nNASDAQ\nAMEX\nBATS\nOTC")
        self.security_types = _lines("Common Stock\nPreferred Stock\nCorporate Bond\nMunicipal Bond")
        self.trade_types = _lines(
            """
            Market Buy
            Market Sell
            Limit Buy
            Limit Sell
            Stop Buy
            Stop Sell
            Stop Limit Buy
            Stop Limit Sell
            """
        )
        self.account_types = _lines("Cash\nMargin\nRetirement\nTrust\nCorporate")
        self.statuses = _lines("Active\nInactive\nSuspended\nPending\nClosed")
        self.countries = _lines("USA\nCanada\nMexico\nUnited Kingdom\nGermany\nFrance\nJapan\nAustralia")
        self.us_states = _lines(
            """
            AL
            AK
            AZ
            AR
            CA
            CO
            CT
            DE
            FL
            GA
            HI
            ID
            IL
            IN
            IA
            KS
            KY
            LA
            ME
            MD
            MA
            MI
            MN
            MS
            MO
            MT
            NE
            NV
            NH
            NJ
            NM
            NY
            NC
            ND
            OH
            OK
            OR
            PA
            RI
            SC
            SD
            TN
            TX
            UT
            VT
            VA
            WA
            WV
            WI
            WY
            """
        )
        self.first_names = _lines(
            """
            James
            Mary
            John
            Patricia
            Robert
            Jennifer
            Michael
            Linda
            William
            Elizabeth
            David
            Barbara
            Richard
            Susan
            Joseph
            Jessica
            Thomas
            Sarah
            Christopher
            Karen
            Charles
            Nancy
            Daniel
            Lisa
            Matthew
            Betty
            Anthony
            Helen
            Mark
            Sandra
            Donald
            Donna
            """
        )
        self.last_names = _lines(
            """
            Smith
            Johnson
            Williams
            Brown
            Jones
            Garcia
            Miller
            Davis
            Rodriguez
            Martinez
            Hernandez
            Lopez
            Gonzalez
            Wilson
            Anderson
            Thomas
            Taylor
            Moore
            Jackson
            Martin
            Lee
            Perez
            Thompson
            White
            Harris
            Sanchez
            Clark
            Ramirez
            Lewis
            Robinson
            Walker
            """
        )
        self.credit_ratings = list(range(300, 851))
        self.tax_jurisdictions = _lines(
            "Federal\nCalifornia\nNew York\nTexas\nFlorida\nIllinois\nPennsylvania\nOhio\nGeorgia\nNorth Carolina\nMichigan"
        )

    def generate_all_source_data(self) -> dict[str, list[str]]:
        """Generate all source system data files.

        Returns:
            Dictionary mapping source system names to lists of generated file paths
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        file_paths = {}

        # Generate OLTP system data (CSV format)
        file_paths["oltp_system"] = self._generate_oltp_data()

        # Generate HR system data (XML format)
        file_paths["hr_system"] = self._generate_hr_data()

        # Generate CRM system data (JSON format)
        file_paths["crm_system"] = self._generate_crm_data()

        # Generate external data (mixed formats)
        file_paths["external_data"] = self._generate_external_data()

        return file_paths

    def _generate_oltp_data(self) -> list[str]:
        """Generate OLTP database extract files in CSV format.

        Returns:
            List of file paths for OLTP data files
        """
        return [self._generate_customer_extract(), self._generate_account_extract(), self._generate_trade_extract()]

    def _generate_customer_extract(self) -> str:
        """Generate customer data extract from OLTP system."""
        file_path = self.output_dir / "oltp_customer_extract.csv"
        num_customers = int(self.base_customers * self.scale_factor)

        # Generate data in batch using pandas
        data = []
        for i in range(1, num_customers + 1):
            # Basic customer info
            customer_id = i
            tax_id = f"{random.randint(100000000, 999999999)}"
            status = random.choice(self.statuses)
            last_name = random.choice(self.last_names)
            first_name = random.choice(self.first_names)
            middle_initial = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            gender = random.choice(["M", "F"])
            tier = random.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]

            # Birth date (age 18-80)
            birth_year = datetime.now().year - random.randint(18, 80)
            date_of_birth = date(birth_year, random.randint(1, 12), random.randint(1, 28))

            # Address (with some data quality issues)
            address_line1 = f"{random.randint(1, 9999)} {random.choice(['Main', 'Oak', 'First', 'Second', 'Park', 'Washington'])} St"
            address_line2 = "" if random.random() > 0.3 else f"Apt {random.randint(1, 999)}"
            postal_code = f"{random.randint(10000, 99999)}" if random.random() > 0.05 else ""  # 5% missing
            city = f"City{random.randint(1, 1000)}"
            state_province = random.choice(self.us_states)
            country = "USA"

            # Contact info (with realistic patterns)
            phone1 = f"{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}"
            phone2 = (
                ""
                if random.random() > 0.4
                else f"{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}"
            )
            phone3 = (
                ""
                if random.random() > 0.1
                else f"{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}"
            )

            email1 = f"{first_name.lower()}.{last_name.lower()}{random.randint(1, 999)}@{random.choice(['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com'])}"
            email2 = (
                ""
                if random.random() > 0.2
                else f"{first_name.lower()}{i}@{random.choice(['company.com', 'business.org'])}"
            )

            # Financial info
            credit_rating = random.choice(self.credit_ratings)
            net_worth = random.randint(10000, 10000000) if tier == 3 else random.randint(1000, 1000000)

            # Temporal info
            created_date = self.start_date + timedelta(days=random.randint(0, (self.end_date - self.start_date).days))
            modified_date = created_date + timedelta(days=random.randint(0, 365))

            data.append(
                [
                    customer_id,
                    tax_id,
                    status,
                    last_name,
                    first_name,
                    middle_initial,
                    gender,
                    tier,
                    date_of_birth,
                    address_line1,
                    address_line2,
                    postal_code,
                    city,
                    state_province,
                    country,
                    phone1,
                    phone2,
                    phone3,
                    email1,
                    email2,
                    credit_rating,
                    net_worth,
                    created_date,
                    modified_date,
                ]
            )

        # Create DataFrame and save to CSV using pandas
        columns = [
            "customer_id",
            "tax_id",
            "status",
            "last_name",
            "first_name",
            "middle_initial",
            "gender",
            "tier",
            "date_of_birth",
            "address_line1",
            "address_line2",
            "postal_code",
            "city",
            "state_province",
            "country",
            "phone1",
            "phone2",
            "phone3",
            "email1",
            "email2",
            "credit_rating",
            "net_worth",
            "created_date",
            "modified_date",
        ]

        df = pd.DataFrame(data, columns=columns)
        df.to_csv(file_path, index=False, quoting=1)  # quoting=1 is equivalent to csv.QUOTE_ALL

        return str(file_path)

    def _generate_account_extract(self) -> str:
        """Generate account data extract from OLTP system."""
        file_path = self.output_dir / "oltp_account_extract.csv"
        num_accounts = int(self.base_accounts * self.scale_factor)
        num_customers = int(self.base_customers * self.scale_factor)

        # Generate data in batch using pandas
        data = []
        for i in range(1, num_accounts + 1):
            account_id = i
            customer_id = random.randint(1, num_customers)
            account_type = random.choice(self.account_types)
            account_description = f"{account_type} Account #{i:06d}"
            status = random.choice(self.statuses)
            tax_status = random.randint(0, 2)  # 0=Taxable, 1=Tax Deferred, 2=Tax Free

            # Account balance (realistic distribution)
            if account_type == "Retirement":
                balance = random.uniform(1000, 2000000)
            elif account_type == "Corporate":
                balance = random.uniform(10000, 50000000)
            else:
                balance = random.uniform(100, 1000000)

            # Dates
            open_date = self.start_date + timedelta(days=random.randint(0, (self.end_date - self.start_date).days))
            close_date = "" if status != "Closed" else open_date + timedelta(days=random.randint(30, 1000))
            created_date = open_date
            modified_date = created_date + timedelta(days=random.randint(0, 365))

            data.append(
                [
                    account_id,
                    customer_id,
                    account_type,
                    account_description,
                    status,
                    tax_status,
                    round(balance, 2),
                    open_date,
                    close_date,
                    created_date,
                    modified_date,
                ]
            )

        # Create DataFrame and save to CSV using pandas
        columns = [
            "account_id",
            "customer_id",
            "account_type",
            "account_description",
            "status",
            "tax_status",
            "balance",
            "open_date",
            "close_date",
            "created_date",
            "modified_date",
        ]

        df = pd.DataFrame(data, columns=columns)
        df.to_csv(file_path, index=False, quoting=1)

        return str(file_path)

    def _generate_trade_extract(self) -> str:
        """Generate trade data extract from OLTP system with fixed-width format."""
        file_path = self.output_dir / "oltp_trade_extract.txt"
        num_trades = int(self.base_trades * self.scale_factor)
        num_accounts = int(self.base_accounts * self.scale_factor)
        num_securities = int(self.base_securities * self.scale_factor)

        with open(file_path, "w", encoding="utf-8") as f:
            for i in range(1, num_trades + 1):
                trade_id = i
                account_id = random.randint(1, num_accounts)
                security_id = random.randint(1, num_securities)
                trade_type = random.choice(self.trade_types)
                quantity = random.randint(1, 10000)
                price = round(random.uniform(10.0, 500.0), 2)

                # Trade datetime
                trade_date = self.start_date + timedelta(days=random.randint(0, (self.end_date - self.start_date).days))
                trade_time = time(random.randint(9, 16), random.randint(0, 59), random.randint(0, 59))

                status = random.choices(["COMPLETED", "PENDING", "CANCELLED"], weights=[0.85, 0.1, 0.05])[0]

                # Fixed-width format (common in legacy systems)
                line = (
                    f"{trade_id:010d}"
                    f"{account_id:010d}"
                    f"{security_id:010d}"
                    f"{trade_type:15s}"
                    f"{quantity:08d}"
                    f"{price:010.2f}"
                    f"{trade_date.strftime('%Y%m%d')}"
                    f"{trade_time.strftime('%H%M%S')}"
                    f"{status:10s}"
                    "\n"
                )

                f.write(line)

        return str(file_path)

    def _generate_hr_data(self) -> list[str]:
        """Generate HR system data in XML format.

        Returns:
            List of file paths for HR data files
        """
        return [self._generate_employee_xml()]

    def _generate_employee_xml(self) -> str:
        """Generate employee/broker data in XML format."""
        file_path = self.output_dir / "hr_employees.xml"
        num_brokers = int(self.base_brokers * self.scale_factor)

        # Create XML structure
        root = ET.Element("employees")
        root.set("export_date", datetime.now().strftime("%Y-%m-%d"))
        root.set("system", "HR_SYSTEM_v2.1")

        for i in range(1, num_brokers + 1):
            employee = ET.SubElement(root, "employee")
            employee.set("id", str(i))
            employee.set("type", "broker")

            # Personal information
            personal = ET.SubElement(employee, "personal_info")
            ET.SubElement(personal, "employee_id").text = str(i)
            ET.SubElement(personal, "first_name").text = random.choice(self.first_names)
            ET.SubElement(personal, "last_name").text = random.choice(self.last_names)
            ET.SubElement(personal, "middle_initial").text = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            ET.SubElement(personal, "gender").text = random.choice(["M", "F"])

            # Birth date
            birth_year = datetime.now().year - random.randint(25, 65)
            birth_date = date(birth_year, random.randint(1, 12), random.randint(1, 28))
            ET.SubElement(personal, "date_of_birth").text = birth_date.strftime("%Y-%m-%d")

            # Employment information
            employment = ET.SubElement(employee, "employment_info")
            ET.SubElement(employment, "hire_date").text = (
                self.start_date + timedelta(days=random.randint(0, 1000))
            ).strftime("%Y-%m-%d")
            ET.SubElement(employment, "department").text = "Trading"
            ET.SubElement(employment, "title").text = random.choice(
                ["Senior Broker", "Junior Broker", "Lead Broker", "Associate Broker"]
            )
            ET.SubElement(employment, "status").text = random.choice(["Active", "Inactive", "Leave"])
            ET.SubElement(employment, "salary").text = str(random.randint(50000, 200000))

            # License information
            licenses = ET.SubElement(employee, "licenses")
            for license_type in ["Series 7", "Series 63", "Series 66"]:
                if random.random() > 0.3:  # Not all brokers have all licenses
                    license_elem = ET.SubElement(licenses, "license")
                    license_elem.set("type", license_type)
                    license_elem.text = f"{license_type}-{random.randint(100000, 999999)}"

        # Write XML file
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)
        tree.write(file_path, encoding="utf-8", xml_declaration=True)

        return str(file_path)

    def _generate_crm_data(self) -> list[str]:
        """Generate CRM system data in JSON format.

        Returns:
            List of file paths for CRM data files
        """
        return [self._generate_customer_relationships_json(), self._generate_marketing_campaigns_json()]

    def _generate_customer_relationships_json(self) -> str:
        """Generate customer relationship data in JSON format."""
        file_path = self.output_dir / "crm_customer_relationships.json"
        num_customers = int(self.base_customers * self.scale_factor * 0.7)  # Not all customers in CRM

        # Generate data using pandas
        data = []
        for i in range(1, num_customers + 1):
            customer = {
                "customer_id": i,
                "crm_id": str(uuid.uuid4()),
                "customer_segment": random.choice(["Retail", "High Net Worth", "Corporate", "Institutional"]),
                "acquisition_channel": random.choice(["Online", "Branch", "Referral", "Marketing", "Cold Call"]),
                "acquisition_date": (
                    self.start_date + timedelta(days=random.randint(0, (self.end_date - self.start_date).days))
                ).strftime("%Y-%m-%d"),
                "last_contact_date": (
                    self.start_date + timedelta(days=random.randint(0, (self.end_date - self.start_date).days))
                ).strftime("%Y-%m-%d"),
                "preferred_contact_method": random.choice(["Email", "Phone", "Mail", "SMS"]),
                "marketing_opt_in": random.choice([True, False]),
                "risk_tolerance": random.choice(["Conservative", "Moderate", "Aggressive"]),
                "investment_objectives": random.choice(["Growth", "Income", "Preservation", "Speculation"]),
                "annual_income": random.randint(30000, 1000000),
                "liquid_net_worth": random.randint(10000, 5000000),
                "investment_experience": random.choice(["Novice", "Intermediate", "Advanced", "Professional"]),
                "notes": f"Customer notes for ID {i}",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            data.append(customer)

        # Create DataFrame and save to JSON using pandas
        df = pd.DataFrame(data)

        # Create the complete JSON structure
        json_data = {
            "export_metadata": {
                "system": "CRM_SYSTEM_v3.2",
                "export_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "record_count": len(data),
            },
            "customers": df.to_dict("records"),
        }

        # Write JSON file
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, default=str)

        return str(file_path)

    def _generate_marketing_campaigns_json(self) -> str:
        """Generate marketing campaign data in JSON format."""
        file_path = self.output_dir / "crm_marketing_campaigns.json"

        # Generate data using pandas
        campaign_types = ["Email", "Direct Mail", "Phone", "Online Ad", "Social Media"]
        data = []

        for i in range(1, 21):  # 20 campaigns
            campaign = {
                "campaign_id": f"CAMP_{i:04d}",
                "campaign_name": f"Campaign {i} - {random.choice(['Q1 Promotion', 'New Account', 'Retention', 'Cross-sell', 'Upgrade'])}",
                "campaign_type": random.choice(campaign_types),
                "start_date": (self.start_date + timedelta(days=random.randint(0, 300))).strftime("%Y-%m-%d"),
                "end_date": (self.start_date + timedelta(days=random.randint(300, 700))).strftime("%Y-%m-%d"),
                "target_segment": random.choice(["All", "High Net Worth", "New Customers", "Inactive", "Corporate"]),
                "budget": random.randint(10000, 500000),
                "responses": random.randint(100, 5000),
                "conversions": random.randint(10, 500),
                "roi": round(random.uniform(0.1, 3.0), 2),
            }
            data.append(campaign)

        # Create DataFrame and save to JSON using pandas
        df = pd.DataFrame(data)

        # Create the complete JSON structure
        json_data = {
            "export_metadata": {
                "system": "CRM_SYSTEM_v3.2",
                "export_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "record_count": len(data),
            },
            "campaigns": df.to_dict("records"),
        }

        # Write JSON file
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2)

        return str(file_path)

    def _generate_external_data(self) -> list[str]:
        """Generate external data provider files in mixed formats.

        Returns:
            List of file paths for external data files
        """
        return [self._generate_market_prices(), self._generate_tax_rates(), self._generate_company_data_xml()]

    def _generate_market_prices(self) -> str:
        """Generate market price data with pipe delimiter."""
        file_path = self.output_dir / "external_market_prices.csv"
        num_securities = int(self.base_securities * self.scale_factor)
        num_prices = int(self.base_market_prices * self.scale_factor)

        # Generate data in batch using pandas
        symbols = [f"SYM{i:04d}" for i in range(1, num_securities + 1)]

        data = []
        for _ in range(num_prices):
            symbol = random.choice(symbols)
            trade_date = self.start_date + timedelta(days=random.randint(0, (self.end_date - self.start_date).days))

            # Generate realistic OHLC prices
            base_price = random.uniform(10.0, 500.0)
            open_price = base_price
            high_price = open_price * random.uniform(1.0, 1.05)
            low_price = open_price * random.uniform(0.95, 1.0)
            close_price = random.uniform(low_price, high_price)
            volume = random.randint(1000, 10000000)
            adjusted_close = close_price * random.uniform(0.98, 1.02)
            source = random.choice(["NYSE", "NASDAQ", "BLOOMBERG", "REUTERS"])

            data.append(
                [
                    symbol,
                    trade_date,
                    round(open_price, 2),
                    round(high_price, 2),
                    round(low_price, 2),
                    round(close_price, 2),
                    volume,
                    round(adjusted_close, 2),
                    source,
                ]
            )

        # Create DataFrame and save to CSV using pandas
        columns = [
            "symbol",
            "date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "adjusted_close",
            "source",
        ]

        df = pd.DataFrame(data, columns=columns)
        df.to_csv(file_path, sep="|", index=False, quoting=1)

        return str(file_path)

    def _generate_tax_rates(self) -> str:
        """Generate tax rate data with tab delimiter."""
        file_path = self.output_dir / "external_tax_rates.tsv"

        # Generate data in batch using pandas
        data = []
        for jurisdiction in self.tax_jurisdictions:
            for tax_type in ["Income", "Capital Gains", "Dividend", "Interest"]:
                rate = random.uniform(0.15, 0.37) if jurisdiction == "Federal" else random.uniform(0.0, 0.13)

                effective_date = self.start_date
                end_date = "9999-12-31"
                description = f"{tax_type} tax rate for {jurisdiction}"

                data.append(
                    [
                        jurisdiction,
                        tax_type,
                        round(rate, 5),
                        effective_date,
                        end_date,
                        description,
                    ]
                )

        # Create DataFrame and save to TSV using pandas
        columns = [
            "jurisdiction",
            "tax_type",
            "rate",
            "effective_date",
            "end_date",
            "description",
        ]

        df = pd.DataFrame(data, columns=columns)
        df.to_csv(file_path, sep="\t", index=False, quoting=1)

        return str(file_path)

    def _generate_company_data_xml(self) -> str:
        """Generate company reference data in XML format."""
        file_path = self.output_dir / "external_company_data.xml"
        num_companies = int(self.base_companies * self.scale_factor)

        # Generate company data using pandas first, then convert to XML
        company_data = []
        for i in range(1, num_companies + 1):
            company = {
                "id": i,
                "name": f"Company {i:04d} {random.choice(self.company_suffixes)}",
                "ticker": f"TKR{i:04d}",
                "industry": random.choice(self.industries),
                "sector": random.choice(
                    [
                        "Technology",
                        "Healthcare",
                        "Finance",
                        "Industrial",
                        "Consumer",
                        "Energy",
                    ]
                ),
                "market_cap": random.randint(1000000, 1000000000000),
                "revenue": random.randint(1000000, 10000000000),
                "net_income": random.randint(-100000000, 1000000000),
                "total_assets": random.randint(1000000, 50000000000),
                "total_debt": random.randint(0, 10000000000),
                "sp_rating": random.choice(
                    [
                        "AAA",
                        "AA+",
                        "AA",
                        "AA-",
                        "A+",
                        "A",
                        "A-",
                        "BBB+",
                        "BBB",
                        "BBB-",
                        "BB+",
                        "BB",
                        "BB-",
                    ]
                ),
                "moody_rating": random.choice(
                    [
                        "Aaa",
                        "Aa1",
                        "Aa2",
                        "Aa3",
                        "A1",
                        "A2",
                        "A3",
                        "Baa1",
                        "Baa2",
                        "Baa3",
                    ]
                ),
                "street": f"{random.randint(1, 9999)} Corporate Blvd",
                "city": f"City{i % 100}",
                "state": random.choice(self.us_states),
                "zip_code": f"{random.randint(10000, 99999)}",
                "country": "USA",
            }
            company_data.append(company)

        # Create DataFrame for easier data manipulation
        df = pd.DataFrame(company_data)

        # Create XML structure manually (pandas to_xml doesn't provide enough control for hierarchical structure)
        root = ET.Element("companies")
        root.set("data_provider", "EXTERNAL_DATA_CORP")
        root.set("export_date", datetime.now().strftime("%Y-%m-%d"))

        for _, row in df.iterrows():
            company = ET.SubElement(root, "company")
            company.set("id", str(row["id"]))

            # Basic company info
            ET.SubElement(company, "name").text = row["name"]
            ET.SubElement(company, "ticker").text = row["ticker"]
            ET.SubElement(company, "industry").text = row["industry"]
            ET.SubElement(company, "sector").text = row["sector"]
            ET.SubElement(company, "market_cap").text = str(row["market_cap"])

            # Financial metrics
            financials = ET.SubElement(company, "financials")
            ET.SubElement(financials, "revenue").text = str(row["revenue"])
            ET.SubElement(financials, "net_income").text = str(row["net_income"])
            ET.SubElement(financials, "total_assets").text = str(row["total_assets"])
            ET.SubElement(financials, "total_debt").text = str(row["total_debt"])

            # Ratings
            ratings = ET.SubElement(company, "ratings")
            ET.SubElement(ratings, "sp_rating").text = row["sp_rating"]
            ET.SubElement(ratings, "moody_rating").text = row["moody_rating"]

            # Address
            address = ET.SubElement(company, "address")
            ET.SubElement(address, "street").text = row["street"]
            ET.SubElement(address, "city").text = row["city"]
            ET.SubElement(address, "state").text = row["state"]
            ET.SubElement(address, "zip_code").text = row["zip_code"]
            ET.SubElement(address, "country").text = row["country"]

        # Write XML file
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)
        tree.write(file_path, encoding="utf-8", xml_declaration=True)

        return str(file_path)

    def generate_data_quality_issues(self, file_path: str, issue_rate: float = 0.05) -> str:  # noqa: ARG002
        """Introduce realistic data quality issues into a generated file.

        Args:
            file_path: Path to the file to modify
            issue_rate: Percentage of records to introduce issues into (0.0-1.0)

        Returns:
            Path to the modified file with data quality issues
        """
        # This method would introduce realistic data quality issues like:
        # - Missing values
        # - Inconsistent formats
        # - Duplicate records
        # - Invalid data types
        # - Referential integrity violations

        # For brevity, returning the original file path
        # In a full implementation, this would create a modified version
        return file_path

    def get_file_format_info(self) -> dict[str, dict[str, Any]]:
        """Get information about the file formats and structures generated.

        Returns:
            Dictionary describing each generated file format
        """
        rows = """
        oltp_customer_extract.csv|CSV|,|Customer data from OLTP database
        oltp_account_extract.csv|CSV|,|Account data from OLTP database
        oltp_trade_extract.txt|Fixed-width||Trade data from legacy OLTP system
        hr_employees.xml|XML||Employee/broker data from HR system
        crm_customer_relationships.json|JSON||Customer relationship data from CRM system
        crm_marketing_campaigns.json|JSON||Marketing campaign data from CRM system
        external_market_prices.csv|CSV|PIPE|Market price data from external provider
        external_tax_rates.tsv|CSV|\\t|Tax rate data from external provider
        external_company_data.xml|XML||Company reference data from external provider
        """
        info = {}
        for name, format_name, delimiter, description in (
            line.strip().split("|") for line in rows.splitlines() if line.strip()
        ):
            info[name] = {"format": format_name}
            if delimiter:
                info[name]["delimiter"] = {"\\t": "\t", "PIPE": "|"}.get(delimiter, delimiter)
                info[name]["quote_char"] = '"'
            info[name]["encoding"] = "utf-8"
            info[name]["description"] = description
        return info

    def _generate_customer_extract_parallel(self) -> str:
        """Generate customer data extract using parallel chunking."""
        file_path = self.output_dir / "oltp_customer_extract.csv"
        num_customers = int(self.base_customers * self.scale_factor)

        # Use chunked generation for large datasets
        if self.enable_parallel and num_customers > self.parallel_config.chunk_size:
            return self._generate_customer_extract_chunked(file_path, num_customers)
        else:
            return self._generate_customer_extract()

    # Removed complex worker pool management - now using context managers

    def get_parallel_generation_metrics(self) -> dict[str, Any]:
        """Get parallel generation performance metrics."""
        if not self.enable_parallel:
            return {"error": "Parallel generation not enabled"}

        summary = self.generation_context.get_generation_summary()

        report = {
            "configuration": {
                "max_workers": self.parallel_config.max_workers,
                "use_process_pool": False,  # Simplified to use only ThreadPoolExecutor
                "chunk_size": self.parallel_config.chunk_size,
                "concurrent_formats": self.parallel_config.enable_concurrent_formats,
                "parallel_batches": self.parallel_config.enable_parallel_batches,
            },
            "generation_summary": summary,
            "performance_metrics": {},
        }

        return report

    def __enter__(self) -> "TPCDISourceDataGenerator":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit with cleanup."""
        if self.enable_parallel:
            self.shutdown_worker_pools()
