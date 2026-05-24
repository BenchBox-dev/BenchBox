"""Multi-channel union helper for TPC-DS DataFrame queries.

TPC-DS has three sales channels (store, catalog, web) with different column
naming conventions. Many queries require UNION ALL across channels with
column name standardization.

This module provides:
- Column mapping definitions for each channel
- Helper functions for creating unified multi-channel views
- Support for both sales and returns fact tables

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    pass

# =============================================================================
# Column Mappings
# =============================================================================


# Channel mapping data is loaded from package data to keep this module focused on behavior.
def _load_channel_mappings() -> dict[str, Any]:
    with (Path(__file__).with_name("channel_mappings.yaml")).open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("TPC-DS channel mappings must be a mapping")
    return payload


_CHANNEL_MAPPINGS = _load_channel_mappings()
SALES_COLUMN_MAPPINGS = _CHANNEL_MAPPINGS["sales_columns"]
RETURNS_COLUMN_MAPPINGS = _CHANNEL_MAPPINGS["returns_columns"]
SALES_TABLE_NAMES = _CHANNEL_MAPPINGS["sales_tables"]
RETURNS_TABLE_NAMES = _CHANNEL_MAPPINGS["returns_tables"]


# =============================================================================
# Union Helper Functions
# =============================================================================


def union_sales_channels_expression(
    ctx: Any,
    channels: list[str],
    columns: list[str],
    add_channel_col: bool = True,
) -> Any:
    """Union sales fact tables from multiple channels (expression family).

    Creates a UNION ALL of sales data from specified channels with
    standardized column names.

    Args:
        ctx: DataFrameContext (expression family)
        channels: List of channels to include: "store", "catalog", "web"
        columns: List of standard column names to select
        add_channel_col: Whether to add a 'channel' column (default True)

    Returns:
        Combined LazyFrame with standardized columns

    Example:
        ```python
        # Union store and web sales with quantity and price
        sales = union_sales_channels_expression(
            ctx,
            channels=["store", "web"],
            columns=["sold_date_sk", "item_sk", "quantity", "ext_sales_price"]
        )
        ```
    """

    col = ctx.col
    lit = ctx.lit
    channel_dfs = []

    for channel in channels:
        if channel not in SALES_COLUMN_MAPPINGS:
            raise ValueError(f"Unknown channel: {channel}. Valid: store, catalog, web")

        table_name = SALES_TABLE_NAMES[channel]
        mapping = SALES_COLUMN_MAPPINGS[channel]

        # Get table
        df = ctx.get_table(table_name)

        # Build select expressions: rename channel-specific columns to standard names
        select_exprs = []
        for std_col in columns:
            if std_col not in mapping:
                raise ValueError(
                    f"Column '{std_col}' not available for channel '{channel}'. "
                    f"Available columns: {list(mapping.keys())}"
                )
            channel_col = mapping[std_col]
            select_exprs.append(col(channel_col).alias(std_col))

        # Add channel indicator if requested
        if add_channel_col:
            select_exprs.append(lit(channel).alias("channel"))

        # Select and append
        channel_df = df.select(select_exprs)
        channel_dfs.append(channel_df)

    # Union all channels
    return ctx.concat(channel_dfs)


def union_sales_channels_pandas(
    ctx: Any,
    channels: list[str],
    columns: list[str],
    add_channel_col: bool = True,
) -> Any:
    """Union sales fact tables from multiple channels (pandas family).

    Creates a UNION ALL of sales data from specified channels with
    standardized column names.

    Args:
        ctx: DataFrameContext (pandas family)
        channels: List of channels to include: "store", "catalog", "web"
        columns: List of standard column names to select
        add_channel_col: Whether to add a 'channel' column (default True)

    Returns:
        Combined DataFrame with standardized columns
    """
    channel_dfs = []

    for channel in channels:
        if channel not in SALES_COLUMN_MAPPINGS:
            raise ValueError(f"Unknown channel: {channel}. Valid: store, catalog, web")

        table_name = SALES_TABLE_NAMES[channel]
        mapping = SALES_COLUMN_MAPPINGS[channel]

        # Get table
        df = ctx.get_table(table_name)

        # Build column selection: channel-specific -> standard
        select_cols = {}
        for std_col in columns:
            if std_col not in mapping:
                raise ValueError(f"Column '{std_col}' not available for channel '{channel}'")
            channel_col = mapping[std_col]
            select_cols[channel_col] = std_col

        # Select and rename columns
        channel_df = df[list(select_cols.keys())].rename(columns=select_cols)

        # Add channel indicator if requested
        if add_channel_col:
            channel_df = channel_df.copy()
            channel_df["channel"] = channel

        channel_dfs.append(channel_df)

    # Union all channels using ctx.concat for Dask compatibility
    return ctx.concat(channel_dfs)


def union_returns_channels_expression(
    ctx: Any,
    channels: list[str],
    columns: list[str],
    add_channel_col: bool = True,
) -> Any:
    """Union returns fact tables from multiple channels (expression family).

    Similar to union_sales_channels but for returns tables.

    Args:
        ctx: DataFrameContext (expression family)
        channels: List of channels to include: "store", "catalog", "web"
        columns: List of standard column names to select
        add_channel_col: Whether to add a 'channel' column (default True)

    Returns:
        Combined LazyFrame with standardized columns
    """

    col = ctx.col
    lit = ctx.lit
    channel_dfs = []

    for channel in channels:
        if channel not in RETURNS_COLUMN_MAPPINGS:
            raise ValueError(f"Unknown channel: {channel}. Valid: store, catalog, web")

        table_name = RETURNS_TABLE_NAMES[channel]
        mapping = RETURNS_COLUMN_MAPPINGS[channel]

        # Get table
        df = ctx.get_table(table_name)

        # Build select expressions
        select_exprs = []
        for std_col in columns:
            if std_col not in mapping:
                raise ValueError(f"Column '{std_col}' not available for channel '{channel}'")
            channel_col = mapping[std_col]
            select_exprs.append(col(channel_col).alias(std_col))

        if add_channel_col:
            select_exprs.append(lit(channel).alias("channel"))

        channel_df = df.select(select_exprs)
        channel_dfs.append(channel_df)

    return ctx.concat(channel_dfs)


def union_returns_channels_pandas(
    ctx: Any,
    channels: list[str],
    columns: list[str],
    add_channel_col: bool = True,
) -> Any:
    """Union returns fact tables from multiple channels (pandas family)."""
    channel_dfs = []

    for channel in channels:
        if channel not in RETURNS_COLUMN_MAPPINGS:
            raise ValueError(f"Unknown channel: {channel}. Valid: store, catalog, web")

        table_name = RETURNS_TABLE_NAMES[channel]
        mapping = RETURNS_COLUMN_MAPPINGS[channel]

        df = ctx.get_table(table_name)

        select_cols = {}
        for std_col in columns:
            if std_col not in mapping:
                raise ValueError(f"Column '{std_col}' not available for channel '{channel}'")
            channel_col = mapping[std_col]
            select_cols[channel_col] = std_col

        channel_df = df[list(select_cols.keys())].rename(columns=select_cols)

        if add_channel_col:
            channel_df = channel_df.copy()
            channel_df["channel"] = channel

        channel_dfs.append(channel_df)

    # Union all channels using ctx.concat for Dask compatibility
    return ctx.concat(channel_dfs)


# =============================================================================
# Convenience Functions
# =============================================================================


def get_sales_column(channel: str, standard_name: str) -> str:
    """Get the channel-specific column name for a standard column.

    Args:
        channel: Channel name ("store", "catalog", "web")
        standard_name: Standard column name

    Returns:
        Channel-specific column name
    """
    if channel not in SALES_COLUMN_MAPPINGS:
        raise ValueError(f"Unknown channel: {channel}")
    if standard_name not in SALES_COLUMN_MAPPINGS[channel]:
        raise ValueError(f"Unknown column: {standard_name} for channel {channel}")
    return SALES_COLUMN_MAPPINGS[channel][standard_name]


def get_returns_column(channel: str, standard_name: str) -> str:
    """Get the channel-specific returns column name."""
    if channel not in RETURNS_COLUMN_MAPPINGS:
        raise ValueError(f"Unknown channel: {channel}")
    if standard_name not in RETURNS_COLUMN_MAPPINGS[channel]:
        raise ValueError(f"Unknown column: {standard_name} for channel {channel}")
    return RETURNS_COLUMN_MAPPINGS[channel][standard_name]


def get_available_sales_columns(channel: str | None = None) -> list[str]:
    """Get list of available standard column names for sales tables.

    Args:
        channel: Optional specific channel, or None for all channels

    Returns:
        List of standard column names
    """
    if channel:
        return list(SALES_COLUMN_MAPPINGS.get(channel, {}).keys())

    # Find columns available in all channels
    all_cols = set(SALES_COLUMN_MAPPINGS["store"].keys())
    all_cols &= set(SALES_COLUMN_MAPPINGS["catalog"].keys())
    all_cols &= set(SALES_COLUMN_MAPPINGS["web"].keys())
    return sorted(all_cols)


def get_available_returns_columns(channel: str | None = None) -> list[str]:
    """Get list of available standard column names for returns tables."""
    if channel:
        return list(RETURNS_COLUMN_MAPPINGS.get(channel, {}).keys())

    all_cols = set(RETURNS_COLUMN_MAPPINGS["store"].keys())
    all_cols &= set(RETURNS_COLUMN_MAPPINGS["catalog"].keys())
    all_cols &= set(RETURNS_COLUMN_MAPPINGS["web"].keys())
    return sorted(all_cols)
