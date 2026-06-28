# Dialect Translation Reference

Test SQL compatibility and platform rewrites.

## Check

- Source SQL parses.
- sqlglot translation for target platforms.
- BenchBox compatibility rules applied in the correct phase.
- DDL rewrites registered under `benchbox/sql_compat/rules/ddl_optimize/<platform>_ddl_rewrites.py`.
- Round-trip or execution smoke when feasible.

## Output

Show source, target dialect, transformed SQL summary, unsupported constructs, rule file touched, and verification command.
