"""Declarative table definitions for the TPC-DS schema."""

from __future__ import annotations

from typing import TypeAlias as _TypeAlias

from .models import Column, DataType, Table

_ColumnSpec: _TypeAlias = tuple[str, DataType, int | None, bool, bool, tuple[str, str] | None]


def _column(spec: _ColumnSpec) -> Column:
    name, data_type, size, nullable, primary_key, foreign_key = spec
    return Column(name, data_type, size=size, nullable=nullable, primary_key=primary_key, foreign_key=foreign_key)


def _table(name: str, columns: tuple[_ColumnSpec, ...]) -> Table:
    return Table(name, [_column(column) for column in columns])


STORE = _table(
    "store",
    (
        ("s_store_sk", DataType.INTEGER, None, False, True, None),
        ("s_store_id", DataType.CHAR, 16, False, False, None),
        ("s_rec_start_date", DataType.DATE, None, True, False, None),
        ("s_rec_end_date", DataType.DATE, None, True, False, None),
        ("s_closed_date_sk", DataType.INTEGER, None, True, False, None),
        ("s_store_name", DataType.VARCHAR, 50, True, False, None),
        ("s_number_employees", DataType.INTEGER, None, True, False, None),
        ("s_floor_space", DataType.INTEGER, None, True, False, None),
        ("s_hours", DataType.CHAR, 20, True, False, None),
        ("s_manager", DataType.VARCHAR, 40, True, False, None),
        ("s_market_id", DataType.INTEGER, None, True, False, None),
        ("s_geography_class", DataType.VARCHAR, 100, True, False, None),
        ("s_market_desc", DataType.VARCHAR, 100, True, False, None),
        ("s_market_manager", DataType.VARCHAR, 40, True, False, None),
        ("s_division_id", DataType.INTEGER, None, True, False, None),
        ("s_division_name", DataType.VARCHAR, 50, True, False, None),
        ("s_company_id", DataType.INTEGER, None, True, False, None),
        ("s_company_name", DataType.VARCHAR, 50, True, False, None),
        ("s_street_number", DataType.VARCHAR, 10, True, False, None),
        ("s_street_name", DataType.VARCHAR, 60, True, False, None),
        ("s_street_type", DataType.CHAR, 15, True, False, None),
        ("s_suite_number", DataType.CHAR, 10, True, False, None),
        ("s_city", DataType.VARCHAR, 60, True, False, None),
        ("s_county", DataType.VARCHAR, 30, True, False, None),
        ("s_state", DataType.CHAR, 2, True, False, None),
        ("s_zip", DataType.CHAR, 10, True, False, None),
        ("s_country", DataType.VARCHAR, 20, True, False, None),
        ("s_gmt_offset", DataType.DECIMAL, None, True, False, None),
        ("s_tax_percentage", DataType.DECIMAL, None, True, False, None),
    ),
)

DATE_DIM = _table(
    "date_dim",
    (
        ("d_date_sk", DataType.INTEGER, None, False, True, None),
        ("d_date_id", DataType.CHAR, 16, False, False, None),
        ("d_date", DataType.DATE, None, False, False, None),
        ("d_month_seq", DataType.INTEGER, None, True, False, None),
        ("d_week_seq", DataType.INTEGER, None, True, False, None),
        ("d_quarter_seq", DataType.INTEGER, None, True, False, None),
        ("d_year", DataType.INTEGER, None, True, False, None),
        ("d_dow", DataType.INTEGER, None, True, False, None),
        ("d_moy", DataType.INTEGER, None, True, False, None),
        ("d_dom", DataType.INTEGER, None, True, False, None),
        ("d_qoy", DataType.INTEGER, None, True, False, None),
        ("d_fy_year", DataType.INTEGER, None, True, False, None),
        ("d_fy_quarter_seq", DataType.INTEGER, None, True, False, None),
        ("d_fy_week_seq", DataType.INTEGER, None, True, False, None),
        ("d_day_name", DataType.CHAR, 9, True, False, None),
        ("d_quarter_name", DataType.CHAR, 6, True, False, None),
        ("d_holiday", DataType.CHAR, 1, True, False, None),
        ("d_weekend", DataType.CHAR, 1, True, False, None),
        ("d_following_holiday", DataType.CHAR, 1, True, False, None),
        ("d_first_dom", DataType.INTEGER, None, True, False, None),
        ("d_last_dom", DataType.INTEGER, None, True, False, None),
        ("d_same_day_ly", DataType.INTEGER, None, True, False, None),
        ("d_same_day_lq", DataType.INTEGER, None, True, False, None),
        ("d_current_day", DataType.CHAR, 1, True, False, None),
        ("d_current_week", DataType.CHAR, 1, True, False, None),
        ("d_current_month", DataType.CHAR, 1, True, False, None),
        ("d_current_quarter", DataType.CHAR, 1, True, False, None),
        ("d_current_year", DataType.CHAR, 1, True, False, None),
    ),
)

TIME_DIM = _table(
    "time_dim",
    (
        ("t_time_sk", DataType.INTEGER, None, False, True, None),
        ("t_time_id", DataType.CHAR, 16, False, False, None),
        ("t_time", DataType.INTEGER, None, True, False, None),
        ("t_hour", DataType.INTEGER, None, True, False, None),
        ("t_minute", DataType.INTEGER, None, True, False, None),
        ("t_second", DataType.INTEGER, None, True, False, None),
        ("t_am_pm", DataType.CHAR, 2, True, False, None),
        ("t_shift", DataType.CHAR, 20, True, False, None),
        ("t_sub_shift", DataType.CHAR, 20, True, False, None),
        ("t_meal_time", DataType.CHAR, 20, True, False, None),
    ),
)

ITEM = _table(
    "item",
    (
        ("i_item_sk", DataType.INTEGER, None, False, True, None),
        ("i_item_id", DataType.CHAR, 16, False, False, None),
        ("i_rec_start_date", DataType.DATE, None, True, False, None),
        ("i_rec_end_date", DataType.DATE, None, True, False, None),
        ("i_item_desc", DataType.VARCHAR, 200, True, False, None),
        ("i_current_price", DataType.DECIMAL, None, True, False, None),
        ("i_wholesale_cost", DataType.DECIMAL, None, True, False, None),
        ("i_brand_id", DataType.INTEGER, None, True, False, None),
        ("i_brand", DataType.CHAR, 50, True, False, None),
        ("i_class_id", DataType.INTEGER, None, True, False, None),
        ("i_class", DataType.CHAR, 50, True, False, None),
        ("i_category_id", DataType.INTEGER, None, True, False, None),
        ("i_category", DataType.CHAR, 50, True, False, None),
        ("i_manufact_id", DataType.INTEGER, None, True, False, None),
        ("i_manufact", DataType.CHAR, 50, True, False, None),
        ("i_size", DataType.CHAR, 20, True, False, None),
        ("i_formulation", DataType.CHAR, 20, True, False, None),
        ("i_color", DataType.CHAR, 20, True, False, None),
        ("i_units", DataType.CHAR, 10, True, False, None),
        ("i_container", DataType.CHAR, 10, True, False, None),
        ("i_manager_id", DataType.INTEGER, None, True, False, None),
        ("i_product_name", DataType.CHAR, 50, True, False, None),
    ),
)

CUSTOMER = _table(
    "customer",
    (
        ("c_customer_sk", DataType.INTEGER, None, False, True, None),
        ("c_customer_id", DataType.CHAR, 16, False, False, None),
        ("c_current_cdemo_sk", DataType.INTEGER, None, True, False, None),
        ("c_current_hdemo_sk", DataType.INTEGER, None, True, False, None),
        ("c_current_addr_sk", DataType.INTEGER, None, True, False, None),
        ("c_first_shipto_date_sk", DataType.INTEGER, None, True, False, None),
        ("c_first_sales_date_sk", DataType.INTEGER, None, True, False, None),
        ("c_salutation", DataType.CHAR, 10, True, False, None),
        ("c_first_name", DataType.CHAR, 20, True, False, None),
        ("c_last_name", DataType.CHAR, 30, True, False, None),
        ("c_preferred_cust_flag", DataType.CHAR, 1, True, False, None),
        ("c_birth_day", DataType.INTEGER, None, True, False, None),
        ("c_birth_month", DataType.INTEGER, None, True, False, None),
        ("c_birth_year", DataType.INTEGER, None, True, False, None),
        ("c_birth_country", DataType.VARCHAR, 20, True, False, None),
        ("c_login", DataType.CHAR, 13, True, False, None),
        ("c_email_address", DataType.CHAR, 50, True, False, None),
        ("c_last_review_date_sk", DataType.INTEGER, None, True, False, None),
    ),
)

CUSTOMER_DEMOGRAPHICS = _table(
    "customer_demographics",
    (
        ("cd_demo_sk", DataType.INTEGER, None, False, True, None),
        ("cd_gender", DataType.CHAR, 1, True, False, None),
        ("cd_marital_status", DataType.CHAR, 1, True, False, None),
        ("cd_education_status", DataType.CHAR, 20, True, False, None),
        ("cd_purchase_estimate", DataType.INTEGER, None, True, False, None),
        ("cd_credit_rating", DataType.CHAR, 10, True, False, None),
        ("cd_dep_count", DataType.INTEGER, None, True, False, None),
        ("cd_dep_employed_count", DataType.INTEGER, None, True, False, None),
        ("cd_dep_college_count", DataType.INTEGER, None, True, False, None),
    ),
)

HOUSEHOLD_DEMOGRAPHICS = _table(
    "household_demographics",
    (
        ("hd_demo_sk", DataType.INTEGER, None, False, True, None),
        ("hd_income_band_sk", DataType.INTEGER, None, True, False, None),
        ("hd_buy_potential", DataType.CHAR, 15, True, False, None),
        ("hd_dep_count", DataType.INTEGER, None, True, False, None),
        ("hd_vehicle_count", DataType.INTEGER, None, True, False, None),
    ),
)

INCOME_BAND = _table(
    "income_band",
    (
        ("ib_income_band_sk", DataType.INTEGER, None, False, True, None),
        ("ib_lower_bound", DataType.INTEGER, None, True, False, None),
        ("ib_upper_bound", DataType.INTEGER, None, True, False, None),
    ),
)

PROMOTION = _table(
    "promotion",
    (
        ("p_promo_sk", DataType.INTEGER, None, False, True, None),
        ("p_promo_id", DataType.CHAR, 16, False, False, None),
        ("p_start_date_sk", DataType.INTEGER, None, True, False, None),
        ("p_end_date_sk", DataType.INTEGER, None, True, False, None),
        ("p_item_sk", DataType.INTEGER, None, True, False, None),
        ("p_cost", DataType.DECIMAL, None, True, False, None),
        ("p_response_target", DataType.INTEGER, None, True, False, None),
        ("p_promo_name", DataType.CHAR, 50, True, False, None),
        ("p_channel_dmail", DataType.CHAR, 1, True, False, None),
        ("p_channel_email", DataType.CHAR, 1, True, False, None),
        ("p_channel_catalog", DataType.CHAR, 1, True, False, None),
        ("p_channel_tv", DataType.CHAR, 1, True, False, None),
        ("p_channel_radio", DataType.CHAR, 1, True, False, None),
        ("p_channel_press", DataType.CHAR, 1, True, False, None),
        ("p_channel_event", DataType.CHAR, 1, True, False, None),
        ("p_channel_demo", DataType.CHAR, 1, True, False, None),
        ("p_channel_details", DataType.VARCHAR, 100, True, False, None),
        ("p_purpose", DataType.CHAR, 15, True, False, None),
        ("p_discount_active", DataType.CHAR, 1, True, False, None),
    ),
)

CUSTOMER_ADDRESS = _table(
    "customer_address",
    (
        ("ca_address_sk", DataType.INTEGER, None, False, True, None),
        ("ca_address_id", DataType.CHAR, 16, False, False, None),
        ("ca_street_number", DataType.CHAR, 10, True, False, None),
        ("ca_street_name", DataType.VARCHAR, 60, True, False, None),
        ("ca_street_type", DataType.CHAR, 15, True, False, None),
        ("ca_suite_number", DataType.CHAR, 10, True, False, None),
        ("ca_city", DataType.VARCHAR, 60, True, False, None),
        ("ca_county", DataType.VARCHAR, 30, True, False, None),
        ("ca_state", DataType.CHAR, 2, True, False, None),
        ("ca_zip", DataType.CHAR, 10, True, False, None),
        ("ca_country", DataType.VARCHAR, 20, True, False, None),
        ("ca_gmt_offset", DataType.DECIMAL, None, True, False, None),
        ("ca_location_type", DataType.CHAR, 20, True, False, None),
    ),
)

WAREHOUSE = _table(
    "warehouse",
    (
        ("w_warehouse_sk", DataType.INTEGER, None, False, True, None),
        ("w_warehouse_id", DataType.CHAR, 16, False, False, None),
        ("w_warehouse_name", DataType.VARCHAR, 20, True, False, None),
        ("w_warehouse_sq_ft", DataType.INTEGER, None, True, False, None),
        ("w_street_number", DataType.CHAR, 10, True, False, None),
        ("w_street_name", DataType.VARCHAR, 60, True, False, None),
        ("w_street_type", DataType.CHAR, 15, True, False, None),
        ("w_suite_number", DataType.CHAR, 10, True, False, None),
        ("w_city", DataType.VARCHAR, 60, True, False, None),
        ("w_county", DataType.VARCHAR, 30, True, False, None),
        ("w_state", DataType.CHAR, 2, True, False, None),
        ("w_zip", DataType.CHAR, 10, True, False, None),
        ("w_country", DataType.VARCHAR, 20, True, False, None),
        ("w_gmt_offset", DataType.DECIMAL, None, True, False, None),
    ),
)

WEB_SITE = _table(
    "web_site",
    (
        ("web_site_sk", DataType.INTEGER, None, False, True, None),
        ("web_site_id", DataType.CHAR, 16, False, False, None),
        ("web_rec_start_date", DataType.DATE, None, True, False, None),
        ("web_rec_end_date", DataType.DATE, None, True, False, None),
        ("web_name", DataType.VARCHAR, 50, True, False, None),
        ("web_open_date_sk", DataType.INTEGER, None, True, False, None),
        ("web_close_date_sk", DataType.INTEGER, None, True, False, None),
        ("web_class", DataType.VARCHAR, 50, True, False, None),
        ("web_manager", DataType.VARCHAR, 40, True, False, None),
        ("web_mkt_id", DataType.INTEGER, None, True, False, None),
        ("web_mkt_class", DataType.VARCHAR, 50, True, False, None),
        ("web_mkt_desc", DataType.VARCHAR, 100, True, False, None),
        ("web_market_manager", DataType.VARCHAR, 40, True, False, None),
        ("web_company_id", DataType.INTEGER, None, True, False, None),
        ("web_company_name", DataType.CHAR, 50, True, False, None),
        ("web_street_number", DataType.CHAR, 10, True, False, None),
        ("web_street_name", DataType.VARCHAR, 60, True, False, None),
        ("web_street_type", DataType.CHAR, 15, True, False, None),
        ("web_suite_number", DataType.CHAR, 10, True, False, None),
        ("web_city", DataType.VARCHAR, 60, True, False, None),
        ("web_county", DataType.VARCHAR, 30, True, False, None),
        ("web_state", DataType.CHAR, 2, True, False, None),
        ("web_zip", DataType.CHAR, 10, True, False, None),
        ("web_country", DataType.VARCHAR, 20, True, False, None),
        ("web_gmt_offset", DataType.DECIMAL, None, True, False, None),
        ("web_tax_percentage", DataType.DECIMAL, None, True, False, None),
    ),
)

WEB_PAGE = _table(
    "web_page",
    (
        ("wp_web_page_sk", DataType.INTEGER, None, False, True, None),
        ("wp_web_page_id", DataType.CHAR, 16, False, False, None),
        ("wp_rec_start_date", DataType.DATE, None, True, False, None),
        ("wp_rec_end_date", DataType.DATE, None, True, False, None),
        ("wp_creation_date_sk", DataType.INTEGER, None, True, False, None),
        ("wp_access_date_sk", DataType.INTEGER, None, True, False, None),
        ("wp_autogen_flag", DataType.CHAR, 1, True, False, None),
        ("wp_customer_sk", DataType.INTEGER, None, True, False, None),
        ("wp_url", DataType.VARCHAR, 100, True, False, None),
        ("wp_type", DataType.CHAR, 50, True, False, None),
        ("wp_char_count", DataType.INTEGER, None, True, False, None),
        ("wp_link_count", DataType.INTEGER, None, True, False, None),
        ("wp_image_count", DataType.INTEGER, None, True, False, None),
        ("wp_max_ad_count", DataType.INTEGER, None, True, False, None),
    ),
)

REASON = _table(
    "reason",
    (
        ("r_reason_sk", DataType.INTEGER, None, False, True, None),
        ("r_reason_id", DataType.CHAR, 16, False, False, None),
        ("r_reason_desc", DataType.CHAR, 100, True, False, None),
    ),
)

CALL_CENTER = _table(
    "call_center",
    (
        ("cc_call_center_sk", DataType.INTEGER, None, False, True, None),
        ("cc_call_center_id", DataType.CHAR, 16, False, False, None),
        ("cc_rec_start_date", DataType.DATE, None, True, False, None),
        ("cc_rec_end_date", DataType.DATE, None, True, False, None),
        ("cc_closed_date_sk", DataType.INTEGER, None, True, False, None),
        ("cc_open_date_sk", DataType.INTEGER, None, True, False, None),
        ("cc_name", DataType.VARCHAR, 50, True, False, None),
        ("cc_class", DataType.VARCHAR, 50, True, False, None),
        ("cc_employees", DataType.INTEGER, None, True, False, None),
        ("cc_sq_ft", DataType.INTEGER, None, True, False, None),
        ("cc_hours", DataType.CHAR, 20, True, False, None),
        ("cc_manager", DataType.VARCHAR, 40, True, False, None),
        ("cc_mkt_id", DataType.INTEGER, None, True, False, None),
        ("cc_mkt_class", DataType.CHAR, 50, True, False, None),
        ("cc_mkt_desc", DataType.VARCHAR, 100, True, False, None),
        ("cc_market_manager", DataType.VARCHAR, 40, True, False, None),
        ("cc_division", DataType.INTEGER, None, True, False, None),
        ("cc_division_name", DataType.VARCHAR, 50, True, False, None),
        ("cc_company", DataType.INTEGER, None, True, False, None),
        ("cc_company_name", DataType.CHAR, 50, True, False, None),
        ("cc_street_number", DataType.CHAR, 10, True, False, None),
        ("cc_street_name", DataType.VARCHAR, 60, True, False, None),
        ("cc_street_type", DataType.CHAR, 15, True, False, None),
        ("cc_suite_number", DataType.CHAR, 10, True, False, None),
        ("cc_city", DataType.VARCHAR, 60, True, False, None),
        ("cc_county", DataType.VARCHAR, 30, True, False, None),
        ("cc_state", DataType.CHAR, 2, True, False, None),
        ("cc_zip", DataType.CHAR, 10, True, False, None),
        ("cc_country", DataType.VARCHAR, 20, True, False, None),
        ("cc_gmt_offset", DataType.DECIMAL, None, True, False, None),
        ("cc_tax_percentage", DataType.DECIMAL, None, True, False, None),
    ),
)

CATALOG_PAGE = _table(
    "catalog_page",
    (
        ("cp_catalog_page_sk", DataType.INTEGER, None, False, True, None),
        ("cp_catalog_page_id", DataType.CHAR, 16, False, False, None),
        ("cp_start_date_sk", DataType.INTEGER, None, True, False, None),
        ("cp_end_date_sk", DataType.INTEGER, None, True, False, None),
        ("cp_department", DataType.VARCHAR, 50, True, False, None),
        ("cp_catalog_number", DataType.INTEGER, None, True, False, None),
        ("cp_catalog_page_number", DataType.INTEGER, None, True, False, None),
        ("cp_description", DataType.VARCHAR, 100, True, False, None),
        ("cp_type", DataType.VARCHAR, 100, True, False, None),
    ),
)

SHIP_MODE = _table(
    "ship_mode",
    (
        ("sm_ship_mode_sk", DataType.INTEGER, None, False, True, None),
        ("sm_ship_mode_id", DataType.CHAR, 16, False, False, None),
        ("sm_type", DataType.CHAR, 30, True, False, None),
        ("sm_code", DataType.CHAR, 10, True, False, None),
        ("sm_carrier", DataType.CHAR, 20, True, False, None),
        ("sm_contract", DataType.CHAR, 20, True, False, None),
    ),
)

STORE_SALES = _table(
    "store_sales",
    (
        ("ss_sold_date_sk", DataType.INTEGER, None, True, False, ("date_dim", "d_date_sk")),
        ("ss_sold_time_sk", DataType.INTEGER, None, True, False, ("time_dim", "t_time_sk")),
        ("ss_item_sk", DataType.INTEGER, None, False, False, ("item", "i_item_sk")),
        ("ss_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("ss_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("ss_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("ss_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("ss_store_sk", DataType.INTEGER, None, True, False, ("store", "s_store_sk")),
        ("ss_promo_sk", DataType.INTEGER, None, True, False, ("promotion", "p_promo_sk")),
        ("ss_ticket_number", DataType.INTEGER, None, False, True, None),
        ("ss_quantity", DataType.INTEGER, None, True, False, None),
        ("ss_wholesale_cost", DataType.DECIMAL, None, True, False, None),
        ("ss_list_price", DataType.DECIMAL, None, True, False, None),
        ("ss_sales_price", DataType.DECIMAL, None, True, False, None),
        ("ss_ext_discount_amt", DataType.DECIMAL, None, True, False, None),
        ("ss_ext_sales_price", DataType.DECIMAL, None, True, False, None),
        ("ss_ext_wholesale_cost", DataType.DECIMAL, None, True, False, None),
        ("ss_ext_list_price", DataType.DECIMAL, None, True, False, None),
        ("ss_ext_tax", DataType.DECIMAL, None, True, False, None),
        ("ss_coupon_amt", DataType.DECIMAL, None, True, False, None),
        ("ss_net_paid", DataType.DECIMAL, None, True, False, None),
        ("ss_net_paid_inc_tax", DataType.DECIMAL, None, True, False, None),
        ("ss_net_profit", DataType.DECIMAL, None, True, False, None),
    ),
)

STORE_RETURNS = _table(
    "store_returns",
    (
        ("sr_returned_date_sk", DataType.INTEGER, None, True, False, ("date_dim", "d_date_sk")),
        ("sr_return_time_sk", DataType.INTEGER, None, True, False, ("time_dim", "t_time_sk")),
        ("sr_item_sk", DataType.INTEGER, None, False, False, ("item", "i_item_sk")),
        ("sr_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("sr_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("sr_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("sr_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("sr_store_sk", DataType.INTEGER, None, True, False, ("store", "s_store_sk")),
        ("sr_reason_sk", DataType.INTEGER, None, True, False, ("reason", "r_reason_sk")),
        ("sr_ticket_number", DataType.INTEGER, None, False, True, ("store_sales", "ss_ticket_number")),
        ("sr_return_quantity", DataType.INTEGER, None, True, False, None),
        ("sr_return_amt", DataType.DECIMAL, None, True, False, None),
        ("sr_return_tax", DataType.DECIMAL, None, True, False, None),
        ("sr_return_amt_inc_tax", DataType.DECIMAL, None, True, False, None),
        ("sr_fee", DataType.DECIMAL, None, True, False, None),
        ("sr_return_ship_cost", DataType.DECIMAL, None, True, False, None),
        ("sr_refunded_cash", DataType.DECIMAL, None, True, False, None),
        ("sr_reversed_charge", DataType.DECIMAL, None, True, False, None),
        ("sr_store_credit", DataType.DECIMAL, None, True, False, None),
        ("sr_net_loss", DataType.DECIMAL, None, True, False, None),
    ),
)

WEB_SALES = _table(
    "web_sales",
    (
        ("ws_sold_date_sk", DataType.INTEGER, None, True, False, ("date_dim", "d_date_sk")),
        ("ws_sold_time_sk", DataType.INTEGER, None, True, False, ("time_dim", "t_time_sk")),
        ("ws_ship_date_sk", DataType.INTEGER, None, True, False, ("date_dim", "d_date_sk")),
        ("ws_item_sk", DataType.INTEGER, None, False, False, ("item", "i_item_sk")),
        ("ws_bill_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("ws_bill_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("ws_bill_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("ws_bill_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("ws_ship_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("ws_ship_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("ws_ship_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("ws_ship_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("ws_web_page_sk", DataType.INTEGER, None, True, False, ("web_page", "wp_web_page_sk")),
        ("ws_web_site_sk", DataType.INTEGER, None, True, False, ("web_site", "web_site_sk")),
        ("ws_ship_mode_sk", DataType.INTEGER, None, True, False, ("ship_mode", "sm_ship_mode_sk")),
        ("ws_warehouse_sk", DataType.INTEGER, None, True, False, ("warehouse", "w_warehouse_sk")),
        ("ws_promo_sk", DataType.INTEGER, None, True, False, ("promotion", "p_promo_sk")),
        ("ws_order_number", DataType.INTEGER, None, False, True, None),
        ("ws_quantity", DataType.INTEGER, None, True, False, None),
        ("ws_wholesale_cost", DataType.DECIMAL, None, True, False, None),
        ("ws_list_price", DataType.DECIMAL, None, True, False, None),
        ("ws_sales_price", DataType.DECIMAL, None, True, False, None),
        ("ws_ext_discount_amt", DataType.DECIMAL, None, True, False, None),
        ("ws_ext_sales_price", DataType.DECIMAL, None, True, False, None),
        ("ws_ext_wholesale_cost", DataType.DECIMAL, None, True, False, None),
        ("ws_ext_list_price", DataType.DECIMAL, None, True, False, None),
        ("ws_ext_tax", DataType.DECIMAL, None, True, False, None),
        ("ws_coupon_amt", DataType.DECIMAL, None, True, False, None),
        ("ws_ext_ship_cost", DataType.DECIMAL, None, True, False, None),
        ("ws_net_paid", DataType.DECIMAL, None, True, False, None),
        ("ws_net_paid_inc_tax", DataType.DECIMAL, None, True, False, None),
        ("ws_net_paid_inc_ship", DataType.DECIMAL, None, True, False, None),
        ("ws_net_paid_inc_ship_tax", DataType.DECIMAL, None, True, False, None),
        ("ws_net_profit", DataType.DECIMAL, None, True, False, None),
    ),
)

WEB_RETURNS = _table(
    "web_returns",
    (
        ("wr_returned_date_sk", DataType.INTEGER, None, True, False, ("date_dim", "d_date_sk")),
        ("wr_returned_time_sk", DataType.INTEGER, None, True, False, ("time_dim", "t_time_sk")),
        ("wr_item_sk", DataType.INTEGER, None, False, False, ("item", "i_item_sk")),
        ("wr_refunded_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("wr_refunded_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("wr_refunded_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("wr_refunded_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("wr_returning_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("wr_returning_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("wr_returning_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("wr_returning_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("wr_web_page_sk", DataType.INTEGER, None, True, False, ("web_page", "wp_web_page_sk")),
        ("wr_reason_sk", DataType.INTEGER, None, True, False, ("reason", "r_reason_sk")),
        ("wr_order_number", DataType.INTEGER, None, False, True, ("web_sales", "ws_order_number")),
        ("wr_return_quantity", DataType.INTEGER, None, True, False, None),
        ("wr_return_amt", DataType.DECIMAL, None, True, False, None),
        ("wr_return_tax", DataType.DECIMAL, None, True, False, None),
        ("wr_return_amt_inc_tax", DataType.DECIMAL, None, True, False, None),
        ("wr_fee", DataType.DECIMAL, None, True, False, None),
        ("wr_return_ship_cost", DataType.DECIMAL, None, True, False, None),
        ("wr_refunded_cash", DataType.DECIMAL, None, True, False, None),
        ("wr_reversed_charge", DataType.DECIMAL, None, True, False, None),
        ("wr_account_credit", DataType.DECIMAL, None, True, False, None),
        ("wr_net_loss", DataType.DECIMAL, None, True, False, None),
    ),
)

CATALOG_SALES = _table(
    "catalog_sales",
    (
        ("cs_sold_date_sk", DataType.INTEGER, None, True, False, ("date_dim", "d_date_sk")),
        ("cs_sold_time_sk", DataType.INTEGER, None, True, False, ("time_dim", "t_time_sk")),
        ("cs_ship_date_sk", DataType.INTEGER, None, True, False, ("date_dim", "d_date_sk")),
        ("cs_bill_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("cs_bill_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("cs_bill_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("cs_bill_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("cs_ship_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("cs_ship_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("cs_ship_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("cs_ship_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("cs_call_center_sk", DataType.INTEGER, None, True, False, ("call_center", "cc_call_center_sk")),
        ("cs_catalog_page_sk", DataType.INTEGER, None, True, False, ("catalog_page", "cp_catalog_page_sk")),
        ("cs_ship_mode_sk", DataType.INTEGER, None, True, False, ("ship_mode", "sm_ship_mode_sk")),
        ("cs_warehouse_sk", DataType.INTEGER, None, True, False, ("warehouse", "w_warehouse_sk")),
        ("cs_item_sk", DataType.INTEGER, None, False, False, ("item", "i_item_sk")),
        ("cs_promo_sk", DataType.INTEGER, None, True, False, ("promotion", "p_promo_sk")),
        ("cs_order_number", DataType.INTEGER, None, False, True, None),
        ("cs_quantity", DataType.INTEGER, None, True, False, None),
        ("cs_wholesale_cost", DataType.DECIMAL, None, True, False, None),
        ("cs_list_price", DataType.DECIMAL, None, True, False, None),
        ("cs_sales_price", DataType.DECIMAL, None, True, False, None),
        ("cs_ext_discount_amt", DataType.DECIMAL, None, True, False, None),
        ("cs_ext_sales_price", DataType.DECIMAL, None, True, False, None),
        ("cs_ext_wholesale_cost", DataType.DECIMAL, None, True, False, None),
        ("cs_ext_list_price", DataType.DECIMAL, None, True, False, None),
        ("cs_ext_tax", DataType.DECIMAL, None, True, False, None),
        ("cs_coupon_amt", DataType.DECIMAL, None, True, False, None),
        ("cs_ext_ship_cost", DataType.DECIMAL, None, True, False, None),
        ("cs_net_paid", DataType.DECIMAL, None, True, False, None),
        ("cs_net_paid_inc_tax", DataType.DECIMAL, None, True, False, None),
        ("cs_net_paid_inc_ship", DataType.DECIMAL, None, True, False, None),
        ("cs_net_paid_inc_ship_tax", DataType.DECIMAL, None, True, False, None),
        ("cs_net_profit", DataType.DECIMAL, None, True, False, None),
    ),
)

CATALOG_RETURNS = _table(
    "catalog_returns",
    (
        ("cr_returned_date_sk", DataType.INTEGER, None, True, False, ("date_dim", "d_date_sk")),
        ("cr_returned_time_sk", DataType.INTEGER, None, True, False, ("time_dim", "t_time_sk")),
        ("cr_item_sk", DataType.INTEGER, None, False, False, ("item", "i_item_sk")),
        ("cr_refunded_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("cr_refunded_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("cr_refunded_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("cr_refunded_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("cr_returning_customer_sk", DataType.INTEGER, None, True, False, ("customer", "c_customer_sk")),
        ("cr_returning_cdemo_sk", DataType.INTEGER, None, True, False, ("customer_demographics", "cd_demo_sk")),
        ("cr_returning_hdemo_sk", DataType.INTEGER, None, True, False, ("household_demographics", "hd_demo_sk")),
        ("cr_returning_addr_sk", DataType.INTEGER, None, True, False, ("customer_address", "ca_address_sk")),
        ("cr_call_center_sk", DataType.INTEGER, None, True, False, ("call_center", "cc_call_center_sk")),
        ("cr_catalog_page_sk", DataType.INTEGER, None, True, False, ("catalog_page", "cp_catalog_page_sk")),
        ("cr_ship_mode_sk", DataType.INTEGER, None, True, False, ("ship_mode", "sm_ship_mode_sk")),
        ("cr_warehouse_sk", DataType.INTEGER, None, True, False, ("warehouse", "w_warehouse_sk")),
        ("cr_reason_sk", DataType.INTEGER, None, True, False, ("reason", "r_reason_sk")),
        ("cr_order_number", DataType.INTEGER, None, False, True, ("catalog_sales", "cs_order_number")),
        ("cr_return_quantity", DataType.INTEGER, None, True, False, None),
        ("cr_return_amount", DataType.DECIMAL, None, True, False, None),
        ("cr_return_tax", DataType.DECIMAL, None, True, False, None),
        ("cr_return_amt_inc_tax", DataType.DECIMAL, None, True, False, None),
        ("cr_fee", DataType.DECIMAL, None, True, False, None),
        ("cr_return_ship_cost", DataType.DECIMAL, None, True, False, None),
        ("cr_refunded_cash", DataType.DECIMAL, None, True, False, None),
        ("cr_reversed_charge", DataType.DECIMAL, None, True, False, None),
        ("cr_store_credit", DataType.DECIMAL, None, True, False, None),
        ("cr_net_loss", DataType.DECIMAL, None, True, False, None),
    ),
)

INVENTORY = _table(
    "inventory",
    (
        ("inv_date_sk", DataType.INTEGER, None, False, False, ("date_dim", "d_date_sk")),
        ("inv_item_sk", DataType.INTEGER, None, False, False, ("item", "i_item_sk")),
        ("inv_warehouse_sk", DataType.INTEGER, None, False, False, ("warehouse", "w_warehouse_sk")),
        ("inv_quantity_on_hand", DataType.INTEGER, None, True, False, None),
    ),
)

DBGEN_VERSION = _table(
    "dbgen_version",
    (
        ("dv_version", DataType.VARCHAR, 16, True, False, None),
        ("dv_create_date", DataType.VARCHAR, 10, True, False, None),
        ("dv_create_time", DataType.VARCHAR, 10, True, False, None),
        ("dv_cmdline_args", DataType.VARCHAR, 200, True, False, None),
    ),
)
