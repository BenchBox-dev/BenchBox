"""PRIMARY KEY capability rules for transaction_primitives lock-table DDL."""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_pk_capability_rules

register_pk_capability_rules("transaction_primitives")
