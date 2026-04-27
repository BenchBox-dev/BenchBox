"""DuckDB-based transformer for the TPC-DS One Big Table benchmark."""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from benchbox.core.tpcds.schema.registry import TABLES_BY_NAME
from benchbox.core.tpcds.schema.tables import (
    CALL_CENTER,
    CATALOG_PAGE,
    CUSTOMER,
    CUSTOMER_ADDRESS,
    CUSTOMER_DEMOGRAPHICS,
    DATE_DIM,
    HOUSEHOLD_DEMOGRAPHICS,
    INCOME_BAND,
    ITEM,
    PROMOTION,
    REASON,
    SHIP_MODE,
    STORE,
    TIME_DIM,
    WAREHOUSE,
    WEB_PAGE,
    WEB_SITE,
)
from benchbox.core.tpcds_obt.schema import OBT_TABLE_NAME, get_obt_columns

logger = logging.getLogger(__name__)

SUPPORTED_CHANNELS = ("store", "web", "catalog")


class TPCDSOBTTransformer:
    """Transforms TPC-DS star schema data into a single OBT table using DuckDB."""

    def __init__(self, duckdb_module: Any | None = None) -> None:
        """Initialize the transformer.

        Args:
            duckdb_module: Optional injected DuckDB module (for testing).
        """
        self._duckdb = duckdb_module

    def transform(
        self,
        tpcds_dir: Path,
        output_dir: Path,
        *,
        mode: str = "full",
        channels: Sequence[str] | None = None,
        output_format: str = "parquet",
        scale_factor: float | None = None,
    ) -> dict[str, Path]:
        """Transform TPC-DS data into the unified OBT table.

        Args:
            tpcds_dir: Directory containing generated TPC-DS data files.
            output_dir: Directory where the OBT output should be written.
            mode: Column group to emit ('full' or 'minimal').
            channels: Optional subset of channels to include.
            output_format: 'parquet' (default) or 'dat' (pipe-delimited).
            scale_factor: Optional scale factor for manifest metadata.

        Returns:
            Mapping containing the output table path and manifest path.
        """
        channel_list = [c.lower() for c in (channels or SUPPORTED_CHANNELS)]
        self._validate_channels(channel_list)

        columns = get_obt_columns(mode)

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{OBT_TABLE_NAME}.{output_format}"
        manifest_path = output_dir / f"{OBT_TABLE_NAME}_manifest.json"

        # Use a file-backed temp database so DuckDB can spill to disk effectively
        # during the large multi-channel UNION+JOIN transformation.
        tmp_dir = tempfile.mkdtemp(prefix="benchbox_obt_")
        tmp_db_path = Path(tmp_dir) / "obt.duckdb"

        conn = self._connect(tmp_db_path)
        try:
            self._load_source_tables(conn, tpcds_dir, channel_list)
            union_sql = self._build_union_query(columns, channel_list)
            conn.execute(union_sql)

            self._export_table(conn, output_path, output_format)
            manifest = self._build_manifest(
                conn,
                output_path,
                mode=mode,
                channels=channel_list,
                scale_factor=scale_factor,
                column_count=len(columns),
                output_format=output_format,
            )
            manifest_path.write_text(json.dumps(manifest, indent=2))

            logger.info(
                "Generated %s with %s rows (%s format)",
                OBT_TABLE_NAME,
                manifest["rows_total"],
                output_format,
            )

            return {"table": output_path, "manifest": manifest_path}
        finally:
            conn.close()
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _connect(self, db_path: Path | None = None) -> Any:
        """Create a DuckDB connection configured for large ETL workloads.

        Args:
            db_path: Path to a file-backed database. If None, uses in-memory.
        """
        target = str(db_path) if db_path else ":memory:"
        if self._duckdb is None:
            import duckdb

            conn = duckdb.connect(target)
        else:
            conn = self._duckdb.connect(target)

        # Configure for large-scale ETL: disable insertion-order preservation
        # to reduce memory pressure during multi-way joins.
        conn.execute("SET preserve_insertion_order = false")
        return conn

    def _validate_channels(self, channels: Sequence[str]) -> None:
        """Validate requested channels."""
        invalid = [c for c in channels if c not in SUPPORTED_CHANNELS]
        if invalid:
            raise ValueError(f"Unsupported channels: {invalid}. Supported: {SUPPORTED_CHANNELS}")

    def _load_source_tables(self, conn: Any, tpcds_dir: Path, channels: Sequence[str]) -> None:
        """Load TPC-DS source tables into DuckDB."""
        base_tables = {
            DATE_DIM.name,
            TIME_DIM.name,
            ITEM.name,
            PROMOTION.name,
            REASON.name,
            CUSTOMER.name,
            CUSTOMER_DEMOGRAPHICS.name,
            HOUSEHOLD_DEMOGRAPHICS.name,
            INCOME_BAND.name,
            CUSTOMER_ADDRESS.name,
            SHIP_MODE.name,
            WAREHOUSE.name,
        }

        if "store" in channels:
            base_tables.update({STORE.name, "store_sales", "store_returns"})
        if "web" in channels:
            base_tables.update({"web_sales", "web_returns", WEB_SITE.name, WEB_PAGE.name})
        if "catalog" in channels:
            base_tables.update({"catalog_sales", "catalog_returns", CALL_CENTER.name, CATALOG_PAGE.name})

        for table_name in sorted(base_tables):
            path = self._resolve_source_path(tpcds_dir, table_name)
            columns = [col.name for col in TABLES_BY_NAME[table_name].columns]
            conn.execute(self._read_csv_sql(path, table_name, columns))

    def _resolve_source_path(self, base_dir: Path, table_name: str) -> Path | list[str]:
        """Resolve the path to TPC-DS source file(s).

        Supports:
            - Single uncompressed files: table.dat, table.tbl
            - Single compressed files: table.dat.zst, table.dat.gz
            - Parallel uncompressed files: table_1_10.dat, table_2_10.dat
            - Parallel compressed files: table_1_10.dat.zst, table_1_10.dat.gz

        Returns either a single Path for a single file, or a list of file path strings
        for parallel-generated files.
        """
        # Check for single-file candidates first (ordered by preference)
        # zstd is preferred as it's the default compression type
        candidates = [
            base_dir / f"{table_name}.dat",
            base_dir / f"{table_name}.dat.zst",
            base_dir / f"{table_name}.dat.gz",
            base_dir / f"{table_name}.tbl",
            base_dir / f"{table_name}.tbl.zst",
            base_dir / f"{table_name}.tbl.gz",
            base_dir / table_name,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

        # Check for parallel-generated files (e.g., table_1_10.dat, table_2_10.dat)
        # Pattern: {table_name}_{chunk_id}_{total_chunks}{extension}
        # Check each extension type in order of preference
        for extension in [".dat", ".dat.zst", ".dat.gz"]:
            parallel_files = self._find_parallel_files(base_dir, table_name, extension)
            if parallel_files:
                file_list = [str(f) for f in sorted(parallel_files)]
                return file_list

        raise FileNotFoundError(f"Source file for {table_name} not found in {base_dir}")

    def _find_parallel_files(self, base_dir: Path, table_name: str, extension: str) -> list[Path]:
        """Find parallel-generated files for a specific table.

        Parallel files follow the pattern: {table_name}_{chunk_id}_{total_chunks}{extension}
        For example: customer_1_10.dat, customer_2_10.dat, ..., customer_10_10.dat

        This method validates that files match the exact pattern to avoid false matches
        like 'customer_demographics_1_10.dat' when looking for 'customer' files.

        Args:
            base_dir: Directory containing the data files.
            table_name: Exact table name to find files for.
            extension: File extension including the dot (e.g., '.dat' or '.dat.gz').

        Returns:
            List of Path objects for matching parallel files, empty if none found.
        """
        # Pattern: table_name_N_M.ext where N and M are integers
        pattern = re.compile(rf"^{re.escape(table_name)}_(\d+)_(\d+){re.escape(extension)}$")

        matching_files: list[Path] = []
        for candidate in base_dir.iterdir():
            if candidate.is_file() and pattern.match(candidate.name):
                matching_files.append(candidate)

        return matching_files

    def _read_csv_sql(self, path: Path | str | list[str], table_name: str, columns: list[str]) -> str:
        """Build DuckDB SQL to load pipe-delimited file(s).

        Uses strict parsing (ignore_errors=false) to ensure data quality.
        Benchmarking requires consistent data; silent row drops could invalidate results.

        Args:
            path: Either a Path to a single file, a glob pattern string, or a list of file paths.
            table_name: Name of the table to create.
            columns: List of column names.
        """
        col_list = ", ".join(f"'{c}'" for c in columns)

        # Format the path argument for DuckDB's read_csv
        if isinstance(path, list):
            # List of files - format as DuckDB list literal
            file_list_str = ", ".join(f"'{f}'" for f in path)
            path_arg = f"[{file_list_str}]"
        else:
            # Single file or glob pattern
            path_arg = f"'{path}'"

        return f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT * FROM read_csv(
                {path_arg},
                delim='|',
                header=false,
                names=[{col_list}],
                ignore_errors=false
            );
        """

    def _build_union_query(self, columns: Sequence[Any], channels: Sequence[str]) -> str:
        """Build the union-all SQL that populates the OBT table."""
        select_statements = [self._channel_select(channel, columns) for channel in channels]
        union_body = "\nUNION ALL\n".join(select_statements)
        return f"CREATE OR REPLACE TABLE {OBT_TABLE_NAME} AS\n{union_body}"

    def _channel_select(self, channel: str, columns: Sequence[Any]) -> str:
        """Build a channel-specific SELECT aligned with the canonical column order."""
        fact_map = self._fact_map(channel)
        role_aliases = self._role_aliases(channel)
        income_band_aliases = self._income_band_aliases(channel)
        joins = self._joins(channel)

        select_parts: list[str] = []
        for col in columns:
            if col.role == "fact":
                expr = fact_map.get(col.name)
                if expr is None:
                    select_parts.append(f"{self._null_expr(col)} AS {col.name}")
                else:
                    select_parts.append(f"{self._cast_expr(expr, col)} AS {col.name}")
            elif col.source_table == "income_band":
                # Income band columns are accessed via household_demographics FK
                ib_alias = income_band_aliases.get(col.role or "")
                if ib_alias is None:
                    select_parts.append(f"{self._null_expr(col)} AS {col.name}")
                else:
                    source_col = (col.source_column or "").lower()
                    select_parts.append(f"{self._cast_expr(f'{ib_alias}.{source_col}', col)} AS {col.name}")
            else:
                alias = role_aliases.get(col.role or "")
                if alias is None:
                    select_parts.append(f"{self._null_expr(col)} AS {col.name}")
                    continue
                source_col = (col.source_column or "").lower()
                select_parts.append(f"{self._cast_expr(f'{alias}.{source_col}', col)} AS {col.name}")

        select_sql = ",\n    ".join(select_parts)
        if channel == "store":
            from_clause = "FROM store_sales ss"
        elif channel == "web":
            from_clause = "FROM web_sales ws"
        else:
            from_clause = "FROM catalog_sales cs"

        return f"SELECT\n    {select_sql}\n{from_clause}\n    " + "\n    ".join(joins)

    def _fact_map(self, channel: str) -> dict[str, str | None]:
        """Return channel-specific mapping for fact columns."""
        if channel == "store":
            return {
                "channel": "'store'",
                "sale_id": "ss.ss_ticket_number",
                "item_sk": "ss.ss_item_sk",
                "sold_date_sk": "ss.ss_sold_date_sk",
                "sold_time_sk": "ss.ss_sold_time_sk",
                "ship_date_sk": None,
                "returned_date_sk": "sr.sr_returned_date_sk",
                "returned_time_sk": "sr.sr_return_time_sk",
                "bill_customer_sk": "ss.ss_customer_sk",
                "bill_cdemo_sk": "ss.ss_cdemo_sk",
                "bill_hdemo_sk": "ss.ss_hdemo_sk",
                "bill_addr_sk": "ss.ss_addr_sk",
                "ship_customer_sk": "ss.ss_customer_sk",
                "ship_cdemo_sk": "ss.ss_cdemo_sk",
                "ship_hdemo_sk": "ss.ss_hdemo_sk",
                "ship_addr_sk": "ss.ss_addr_sk",
                "store_sk": "ss.ss_store_sk",
                "web_site_sk": None,
                "web_page_sk": None,
                "call_center_sk": None,
                "catalog_page_sk": None,
                "ship_mode_sk": None,
                "warehouse_sk": None,
                "promo_sk": "ss.ss_promo_sk",
                "reason_sk": "sr.sr_reason_sk",
                "quantity": "ss.ss_quantity",
                "wholesale_cost": "ss.ss_wholesale_cost",
                "list_price": "ss.ss_list_price",
                "sales_price": "ss.ss_sales_price",
                "ext_discount_amt": "ss.ss_ext_discount_amt",
                "ext_sales_price": "ss.ss_ext_sales_price",
                "ext_wholesale_cost": "ss.ss_ext_wholesale_cost",
                "ext_list_price": "ss.ss_ext_list_price",
                "ext_tax": "ss.ss_ext_tax",
                "coupon_amt": "ss.ss_coupon_amt",
                "ext_ship_cost": None,
                "net_paid": "ss.ss_net_paid",
                "net_paid_inc_tax": "ss.ss_net_paid_inc_tax",
                "net_paid_inc_ship": None,
                "net_paid_inc_ship_tax": None,
                "net_profit": "ss.ss_net_profit",
                "return_quantity": "sr.sr_return_quantity",
                "return_amount": "sr.sr_return_amt",
                "return_tax": "sr.sr_return_tax",
                "return_amount_inc_tax": "sr.sr_return_amt_inc_tax",
                "return_fee": "sr.sr_fee",
                "return_ship_cost": "sr.sr_return_ship_cost",
                "refunded_cash": "sr.sr_refunded_cash",
                "reversed_charge": "sr.sr_reversed_charge",
                "account_credit": None,
                "store_credit": "sr.sr_store_credit",
                "return_net_loss": "sr.sr_net_loss",
                "has_return": "CASE WHEN sr.sr_ticket_number IS NULL THEN 'N' ELSE 'Y' END",
            }

        if channel == "web":
            return {
                "channel": "'web'",
                "sale_id": "ws.ws_order_number",
                "item_sk": "ws.ws_item_sk",
                "sold_date_sk": "ws.ws_sold_date_sk",
                "sold_time_sk": "ws.ws_sold_time_sk",
                "ship_date_sk": "ws.ws_ship_date_sk",
                "returned_date_sk": "wr.wr_returned_date_sk",
                "returned_time_sk": "wr.wr_returned_time_sk",
                "bill_customer_sk": "ws.ws_bill_customer_sk",
                "bill_cdemo_sk": "ws.ws_bill_cdemo_sk",
                "bill_hdemo_sk": "ws.ws_bill_hdemo_sk",
                "bill_addr_sk": "ws.ws_bill_addr_sk",
                "ship_customer_sk": "ws.ws_ship_customer_sk",
                "ship_cdemo_sk": "ws.ws_ship_cdemo_sk",
                "ship_hdemo_sk": "ws.ws_ship_hdemo_sk",
                "ship_addr_sk": "ws.ws_ship_addr_sk",
                "store_sk": None,
                "web_site_sk": "ws.ws_web_site_sk",
                "web_page_sk": "ws.ws_web_page_sk",
                "call_center_sk": None,
                "catalog_page_sk": None,
                "ship_mode_sk": "ws.ws_ship_mode_sk",
                "warehouse_sk": "ws.ws_warehouse_sk",
                "promo_sk": "ws.ws_promo_sk",
                "reason_sk": "wr.wr_reason_sk",
                "quantity": "ws.ws_quantity",
                "wholesale_cost": "ws.ws_wholesale_cost",
                "list_price": "ws.ws_list_price",
                "sales_price": "ws.ws_sales_price",
                "ext_discount_amt": "ws.ws_ext_discount_amt",
                "ext_sales_price": "ws.ws_ext_sales_price",
                "ext_wholesale_cost": "ws.ws_ext_wholesale_cost",
                "ext_list_price": "ws.ws_ext_list_price",
                "ext_tax": "ws.ws_ext_tax",
                "coupon_amt": "ws.ws_coupon_amt",
                "ext_ship_cost": "ws.ws_ext_ship_cost",
                "net_paid": "ws.ws_net_paid",
                "net_paid_inc_tax": "ws.ws_net_paid_inc_tax",
                "net_paid_inc_ship": "ws.ws_net_paid_inc_ship",
                "net_paid_inc_ship_tax": "ws.ws_net_paid_inc_ship_tax",
                "net_profit": "ws.ws_net_profit",
                "return_quantity": "wr.wr_return_quantity",
                "return_amount": "wr.wr_return_amt",
                "return_tax": "wr.wr_return_tax",
                "return_amount_inc_tax": "wr.wr_return_amt_inc_tax",
                "return_fee": "wr.wr_fee",
                "return_ship_cost": "wr.wr_return_ship_cost",
                "refunded_cash": "wr.wr_refunded_cash",
                "reversed_charge": "wr.wr_reversed_charge",
                "account_credit": "wr.wr_account_credit",
                "store_credit": None,
                "return_net_loss": "wr.wr_net_loss",
                "has_return": "CASE WHEN wr.wr_order_number IS NULL THEN 'N' ELSE 'Y' END",
            }

        # catalog
        return {
            "channel": "'catalog'",
            "sale_id": "cs.cs_order_number",
            "item_sk": "cs.cs_item_sk",
            "sold_date_sk": "cs.cs_sold_date_sk",
            "sold_time_sk": "cs.cs_sold_time_sk",
            "ship_date_sk": "cs.cs_ship_date_sk",
            "returned_date_sk": "cr.cr_returned_date_sk",
            "returned_time_sk": "cr.cr_returned_time_sk",
            "bill_customer_sk": "cs.cs_bill_customer_sk",
            "bill_cdemo_sk": "cs.cs_bill_cdemo_sk",
            "bill_hdemo_sk": "cs.cs_bill_hdemo_sk",
            "bill_addr_sk": "cs.cs_bill_addr_sk",
            "ship_customer_sk": "cs.cs_ship_customer_sk",
            "ship_cdemo_sk": "cs.cs_ship_cdemo_sk",
            "ship_hdemo_sk": "cs.cs_ship_hdemo_sk",
            "ship_addr_sk": "cs.cs_ship_addr_sk",
            "store_sk": None,
            "web_site_sk": None,
            "web_page_sk": None,
            "call_center_sk": "cs.cs_call_center_sk",
            "catalog_page_sk": "cs.cs_catalog_page_sk",
            "ship_mode_sk": "cs.cs_ship_mode_sk",
            "warehouse_sk": "cs.cs_warehouse_sk",
            "promo_sk": "cs.cs_promo_sk",
            "reason_sk": "cr.cr_reason_sk",
            "quantity": "cs.cs_quantity",
            "wholesale_cost": "cs.cs_wholesale_cost",
            "list_price": "cs.cs_list_price",
            "sales_price": "cs.cs_sales_price",
            "ext_discount_amt": "cs.cs_ext_discount_amt",
            "ext_sales_price": "cs.cs_ext_sales_price",
            "ext_wholesale_cost": "cs.cs_ext_wholesale_cost",
            "ext_list_price": "cs.cs_ext_list_price",
            "ext_tax": "cs.cs_ext_tax",
            "coupon_amt": "cs.cs_coupon_amt",
            "ext_ship_cost": "cs.cs_ext_ship_cost",
            "net_paid": "cs.cs_net_paid",
            "net_paid_inc_tax": "cs.cs_net_paid_inc_tax",
            "net_paid_inc_ship": "cs.cs_net_paid_inc_ship",
            "net_paid_inc_ship_tax": "cs.cs_net_paid_inc_ship_tax",
            "net_profit": "cs.cs_net_profit",
            "return_quantity": "cr.cr_return_quantity",
            "return_amount": "cr.cr_return_amount",
            "return_tax": "cr.cr_return_tax",
            "return_amount_inc_tax": "cr.cr_return_amt_inc_tax",
            "return_fee": "cr.cr_fee",
            "return_ship_cost": "cr.cr_return_ship_cost",
            "refunded_cash": "cr.cr_refunded_cash",
            "reversed_charge": "cr.cr_reversed_charge",
            "account_credit": None,
            "store_credit": "cr.cr_store_credit",
            "return_net_loss": "cr.cr_net_loss",
            "has_return": "CASE WHEN cr.cr_order_number IS NULL THEN 'N' ELSE 'Y' END",
        }

    def _role_aliases(self, channel: str) -> dict[str, str | None]:
        """Return dimension role aliases for the channel."""
        if channel == "store":
            return {
                "sold_date": "ssd",
                "sold_time": "sst",
                "ship_date": None,
                "return_date": "srd",
                "return_time": "srt",
                "item": "i",
                "promotion": "p",
                "reason": "r",
                "store": "st",
                "web_site": None,
                "web_page": None,
                "call_center": None,
                "catalog_page": None,
                "ship_mode": None,
                "warehouse": None,
                "bill_customer": "c_bill",
                "ship_customer": "c_bill",
                "returning_customer": "c_ret",
                "refunded_customer": "c_ret",
                "bill_cdemo": "cd_bill",
                "ship_cdemo": "cd_bill",
                "returning_cdemo": "cd_ret",
                "refunded_cdemo": "cd_ret",
                "bill_hdemo": "hd_bill",
                "ship_hdemo": "hd_bill",
                "returning_hdemo": "hd_ret",
                "refunded_hdemo": "hd_ret",
                "bill_address": "ca_bill",
                "ship_address": "ca_bill",
                "returning_address": "ca_ret",
                "refunded_address": "ca_ret",
            }

        if channel == "web":
            return {
                "sold_date": "wsd",
                "sold_time": "wst",
                "ship_date": "wshipd",
                "return_date": "wrd",
                "return_time": "wrt",
                "item": "i",
                "promotion": "p",
                "reason": "r",
                "store": None,
                "web_site": "wsit",
                "web_page": "wp",
                "call_center": None,
                "catalog_page": None,
                "ship_mode": "sm",
                "warehouse": "w",
                "bill_customer": "c_bill",
                "ship_customer": "c_ship",
                "returning_customer": "c_ret",
                "refunded_customer": "c_ref",
                "bill_cdemo": "cd_bill",
                "ship_cdemo": "cd_ship",
                "returning_cdemo": "cd_ret",
                "refunded_cdemo": "cd_ref",
                "bill_hdemo": "hd_bill",
                "ship_hdemo": "hd_ship",
                "returning_hdemo": "hd_ret",
                "refunded_hdemo": "hd_ref",
                "bill_address": "ca_bill",
                "ship_address": "ca_ship",
                "returning_address": "ca_ret",
                "refunded_address": "ca_ref",
            }

        return {
            "sold_date": "csd",
            "sold_time": "cst",
            "ship_date": "cshipd",
            "return_date": "crd",
            "return_time": "crt",
            "item": "i",
            "promotion": "p",
            "reason": "r",
            "store": None,
            "web_site": None,
            "web_page": None,
            "call_center": "cc",
            "catalog_page": "cp",
            "ship_mode": "sm",
            "warehouse": "w",
            "bill_customer": "c_bill",
            "ship_customer": "c_ship",
            "returning_customer": "c_ret",
            "refunded_customer": "c_ref",
            "bill_cdemo": "cd_bill",
            "ship_cdemo": "cd_ship",
            "returning_cdemo": "cd_ret",
            "refunded_cdemo": "cd_ref",
            "bill_hdemo": "hd_bill",
            "ship_hdemo": "hd_ship",
            "returning_hdemo": "hd_ret",
            "refunded_hdemo": "hd_ref",
            "bill_address": "ca_bill",
            "ship_address": "ca_ship",
            "returning_address": "ca_ret",
            "refunded_address": "ca_ref",
        }

    def _income_band_aliases(self, channel: str) -> dict[str, str | None]:
        """Return income_band table aliases for each household_demographics role."""
        if channel == "store":
            return {
                "bill_hdemo": "ib_bill",
                "ship_hdemo": "ib_bill",  # Store sales: bill = ship
                "returning_hdemo": "ib_ret",
                "refunded_hdemo": "ib_ret",  # Store returns: ret = refunded
            }
        if channel == "web":
            return {
                "bill_hdemo": "ib_bill",
                "ship_hdemo": "ib_ship",
                "returning_hdemo": "ib_ret",
                "refunded_hdemo": "ib_ref",
            }
        # catalog
        return {
            "bill_hdemo": "ib_bill",
            "ship_hdemo": "ib_ship",
            "returning_hdemo": "ib_ret",
            "refunded_hdemo": "ib_ref",
        }

    def _joins(self, channel: str) -> list[str]:
        """Return LEFT JOIN clauses for the channel."""
        if channel == "store":
            return [
                "LEFT JOIN store_returns sr ON ss.ss_ticket_number = sr.sr_ticket_number "
                "AND ss.ss_item_sk = sr.sr_item_sk",
                "LEFT JOIN date_dim ssd ON ss.ss_sold_date_sk = ssd.d_date_sk",
                "LEFT JOIN time_dim sst ON ss.ss_sold_time_sk = sst.t_time_sk",
                "LEFT JOIN date_dim srd ON sr.sr_returned_date_sk = srd.d_date_sk",
                "LEFT JOIN time_dim srt ON sr.sr_return_time_sk = srt.t_time_sk",
                "LEFT JOIN item i ON ss.ss_item_sk = i.i_item_sk",
                "LEFT JOIN promotion p ON ss.ss_promo_sk = p.p_promo_sk",
                "LEFT JOIN reason r ON sr.sr_reason_sk = r.r_reason_sk",
                "LEFT JOIN store st ON ss.ss_store_sk = st.s_store_sk",
                "LEFT JOIN customer c_bill ON ss.ss_customer_sk = c_bill.c_customer_sk",
                "LEFT JOIN customer_demographics cd_bill ON ss.ss_cdemo_sk = cd_bill.cd_demo_sk",
                "LEFT JOIN household_demographics hd_bill ON ss.ss_hdemo_sk = hd_bill.hd_demo_sk",
                "LEFT JOIN income_band ib_bill ON hd_bill.hd_income_band_sk = ib_bill.ib_income_band_sk",
                "LEFT JOIN customer_address ca_bill ON ss.ss_addr_sk = ca_bill.ca_address_sk",
                "LEFT JOIN customer c_ret ON sr.sr_customer_sk = c_ret.c_customer_sk",
                "LEFT JOIN customer_demographics cd_ret ON sr.sr_cdemo_sk = cd_ret.cd_demo_sk",
                "LEFT JOIN household_demographics hd_ret ON sr.sr_hdemo_sk = hd_ret.hd_demo_sk",
                "LEFT JOIN income_band ib_ret ON hd_ret.hd_income_band_sk = ib_ret.ib_income_band_sk",
                "LEFT JOIN customer_address ca_ret ON sr.sr_addr_sk = ca_ret.ca_address_sk",
            ]

        if channel == "web":
            return [
                "LEFT JOIN web_returns wr ON ws.ws_order_number = wr.wr_order_number AND ws.ws_item_sk = wr.wr_item_sk",
                "LEFT JOIN date_dim wsd ON ws.ws_sold_date_sk = wsd.d_date_sk",
                "LEFT JOIN time_dim wst ON ws.ws_sold_time_sk = wst.t_time_sk",
                "LEFT JOIN date_dim wshipd ON ws.ws_ship_date_sk = wshipd.d_date_sk",
                "LEFT JOIN date_dim wrd ON wr.wr_returned_date_sk = wrd.d_date_sk",
                "LEFT JOIN time_dim wrt ON wr.wr_returned_time_sk = wrt.t_time_sk",
                "LEFT JOIN item i ON ws.ws_item_sk = i.i_item_sk",
                "LEFT JOIN promotion p ON ws.ws_promo_sk = p.p_promo_sk",
                "LEFT JOIN reason r ON wr.wr_reason_sk = r.r_reason_sk",
                "LEFT JOIN web_site wsit ON ws.ws_web_site_sk = wsit.web_site_sk",
                "LEFT JOIN web_page wp ON ws.ws_web_page_sk = wp.wp_web_page_sk",
                "LEFT JOIN ship_mode sm ON ws.ws_ship_mode_sk = sm.sm_ship_mode_sk",
                "LEFT JOIN warehouse w ON ws.ws_warehouse_sk = w.w_warehouse_sk",
                "LEFT JOIN customer c_bill ON ws.ws_bill_customer_sk = c_bill.c_customer_sk",
                "LEFT JOIN customer_demographics cd_bill ON ws.ws_bill_cdemo_sk = cd_bill.cd_demo_sk",
                "LEFT JOIN household_demographics hd_bill ON ws.ws_bill_hdemo_sk = hd_bill.hd_demo_sk",
                "LEFT JOIN income_band ib_bill ON hd_bill.hd_income_band_sk = ib_bill.ib_income_band_sk",
                "LEFT JOIN customer_address ca_bill ON ws.ws_bill_addr_sk = ca_bill.ca_address_sk",
                "LEFT JOIN customer c_ship ON ws.ws_ship_customer_sk = c_ship.c_customer_sk",
                "LEFT JOIN customer_demographics cd_ship ON ws.ws_ship_cdemo_sk = cd_ship.cd_demo_sk",
                "LEFT JOIN household_demographics hd_ship ON ws.ws_ship_hdemo_sk = hd_ship.hd_demo_sk",
                "LEFT JOIN income_band ib_ship ON hd_ship.hd_income_band_sk = ib_ship.ib_income_band_sk",
                "LEFT JOIN customer_address ca_ship ON ws.ws_ship_addr_sk = ca_ship.ca_address_sk",
                "LEFT JOIN customer c_ret ON wr.wr_returning_customer_sk = c_ret.c_customer_sk",
                "LEFT JOIN customer_demographics cd_ret ON wr.wr_returning_cdemo_sk = cd_ret.cd_demo_sk",
                "LEFT JOIN household_demographics hd_ret ON wr.wr_returning_hdemo_sk = hd_ret.hd_demo_sk",
                "LEFT JOIN income_band ib_ret ON hd_ret.hd_income_band_sk = ib_ret.ib_income_band_sk",
                "LEFT JOIN customer_address ca_ret ON wr.wr_returning_addr_sk = ca_ret.ca_address_sk",
                "LEFT JOIN customer c_ref ON wr.wr_refunded_customer_sk = c_ref.c_customer_sk",
                "LEFT JOIN customer_demographics cd_ref ON wr.wr_refunded_cdemo_sk = cd_ref.cd_demo_sk",
                "LEFT JOIN household_demographics hd_ref ON wr.wr_refunded_hdemo_sk = hd_ref.hd_demo_sk",
                "LEFT JOIN income_band ib_ref ON hd_ref.hd_income_band_sk = ib_ref.ib_income_band_sk",
                "LEFT JOIN customer_address ca_ref ON wr.wr_refunded_addr_sk = ca_ref.ca_address_sk",
            ]

        return [
            "LEFT JOIN catalog_returns cr ON cs.cs_order_number = cr.cr_order_number AND cs.cs_item_sk = cr.cr_item_sk",
            "LEFT JOIN date_dim csd ON cs.cs_sold_date_sk = csd.d_date_sk",
            "LEFT JOIN time_dim cst ON cs.cs_sold_time_sk = cst.t_time_sk",
            "LEFT JOIN date_dim cshipd ON cs.cs_ship_date_sk = cshipd.d_date_sk",
            "LEFT JOIN date_dim crd ON cr.cr_returned_date_sk = crd.d_date_sk",
            "LEFT JOIN time_dim crt ON cr.cr_returned_time_sk = crt.t_time_sk",
            "LEFT JOIN item i ON cs.cs_item_sk = i.i_item_sk",
            "LEFT JOIN promotion p ON cs.cs_promo_sk = p.p_promo_sk",
            "LEFT JOIN reason r ON cr.cr_reason_sk = r.r_reason_sk",
            "LEFT JOIN call_center cc ON cs.cs_call_center_sk = cc.cc_call_center_sk",
            "LEFT JOIN catalog_page cp ON cs.cs_catalog_page_sk = cp.cp_catalog_page_sk",
            "LEFT JOIN ship_mode sm ON cs.cs_ship_mode_sk = sm.sm_ship_mode_sk",
            "LEFT JOIN warehouse w ON cs.cs_warehouse_sk = w.w_warehouse_sk",
            "LEFT JOIN customer c_bill ON cs.cs_bill_customer_sk = c_bill.c_customer_sk",
            "LEFT JOIN customer_demographics cd_bill ON cs.cs_bill_cdemo_sk = cd_bill.cd_demo_sk",
            "LEFT JOIN household_demographics hd_bill ON cs.cs_bill_hdemo_sk = hd_bill.hd_demo_sk",
            "LEFT JOIN income_band ib_bill ON hd_bill.hd_income_band_sk = ib_bill.ib_income_band_sk",
            "LEFT JOIN customer_address ca_bill ON cs.cs_bill_addr_sk = ca_bill.ca_address_sk",
            "LEFT JOIN customer c_ship ON cs.cs_ship_customer_sk = c_ship.c_customer_sk",
            "LEFT JOIN customer_demographics cd_ship ON cs.cs_ship_cdemo_sk = cd_ship.cd_demo_sk",
            "LEFT JOIN household_demographics hd_ship ON cs.cs_ship_hdemo_sk = hd_ship.hd_demo_sk",
            "LEFT JOIN income_band ib_ship ON hd_ship.hd_income_band_sk = ib_ship.ib_income_band_sk",
            "LEFT JOIN customer_address ca_ship ON cs.cs_ship_addr_sk = ca_ship.ca_address_sk",
            "LEFT JOIN customer c_ret ON cr.cr_returning_customer_sk = c_ret.c_customer_sk",
            "LEFT JOIN customer_demographics cd_ret ON cr.cr_returning_cdemo_sk = cd_ret.cd_demo_sk",
            "LEFT JOIN household_demographics hd_ret ON cr.cr_returning_hdemo_sk = hd_ret.hd_demo_sk",
            "LEFT JOIN income_band ib_ret ON hd_ret.hd_income_band_sk = ib_ret.ib_income_band_sk",
            "LEFT JOIN customer_address ca_ret ON cr.cr_returning_addr_sk = ca_ret.ca_address_sk",
            "LEFT JOIN customer c_ref ON cr.cr_refunded_customer_sk = c_ref.c_customer_sk",
            "LEFT JOIN customer_demographics cd_ref ON cr.cr_refunded_cdemo_sk = cd_ref.cd_demo_sk",
            "LEFT JOIN household_demographics hd_ref ON cr.cr_refunded_hdemo_sk = hd_ref.hd_demo_sk",
            "LEFT JOIN income_band ib_ref ON hd_ref.hd_income_band_sk = ib_ref.ib_income_band_sk",
            "LEFT JOIN customer_address ca_ref ON cr.cr_refunded_addr_sk = ca_ref.ca_address_sk",
        ]

    def _cast_expr(self, expr: str, column: Any) -> str:
        """Cast an expression to the OBT column type."""
        return f"CAST({expr} AS {column.sql_type()})"

    def _null_expr(self, column: Any) -> str:
        """Render a typed NULL expression."""
        return f"CAST(NULL AS {column.sql_type()})"

    def _export_table(self, conn: Any, output_path: Path, output_format: str) -> None:
        """Export the OBT table to disk."""
        if output_format == "parquet":
            conn.execute(f"COPY {OBT_TABLE_NAME} TO '{output_path}' (FORMAT PARQUET)")
        elif output_format == "dat":
            conn.execute(f"COPY {OBT_TABLE_NAME} TO '{output_path}' (DELIMITER '|', HEADER FALSE, NULL '')")
        else:
            raise ValueError(f"Unsupported output_format: {output_format}")

    def _build_manifest(
        self,
        conn: Any,
        output_path: Path,
        *,
        mode: str,
        channels: Sequence[str],
        scale_factor: float | None,
        column_count: int,
        output_format: str,
    ) -> dict[str, Any]:
        """Build manifest metadata for the generated table."""
        rows_total = int(conn.execute(f"SELECT COUNT(*) FROM {OBT_TABLE_NAME}").fetchone()[0])
        rows_by_channel = dict(
            conn.execute(f"SELECT channel, COUNT(*) FROM {OBT_TABLE_NAME} GROUP BY channel").fetchall()
        )
        return_rows = int(conn.execute(f"SELECT COUNT(*) FROM {OBT_TABLE_NAME} WHERE has_return = 'Y'").fetchone()[0])

        file_size = output_path.stat().st_size if output_path.exists() else 0

        return {
            "table": OBT_TABLE_NAME,
            "mode": mode,
            "channels": list(channels),
            "column_count": column_count,
            "rows_total": rows_total,
            "rows_by_channel": rows_by_channel,
            "rows_with_returns": return_rows,
            "output_file": str(output_path.name),
            "output_format": output_format,
            "file_size_bytes": file_size,
            "scale_factor": scale_factor,
        }
