# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from typing import Any

from benchbox.core.metadata_primitives.complexity import (
    AclGrant,
    ConstraintDensity,
    GeneratedMetadata,
    MetadataComplexityConfig,
    PermissionDensity,
    RoleHierarchyDepth,
    TypeComplexity,
)
from benchbox.core.metadata_primitives.ddl import (
    ColumnDefinition,
    TableDefinition,
    ViewDefinition,
    generate_create_role_sql,
    generate_create_table_sql,
    generate_create_view_sql,
    generate_drop_role_sql,
    generate_drop_table_sql,
    generate_drop_view_sql,
    generate_grant_role_sql,
    generate_grant_sql,
    generate_revoke_sql,
    generate_simple_table_columns,
    generate_wide_table_columns,
    map_type,
    supports_acl,
    supports_column_grants,
    supports_complex_types,
    supports_foreign_keys,
    supports_role_hierarchy,
    supports_views,
)

logger = logging.getLogger(__name__)


class MetadataGenerator:
    def setup(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
    ) -> GeneratedMetadata:
        generated = GeneratedMetadata(
            prefix=config.prefix,
            config=config,
        )

        try:
            if config.width_factor > 0:
                self._generate_wide_tables(connection, dialect, config, generated)

            if config.catalog_size > 1:
                self._generate_catalog_tables(connection, dialect, config, generated)

            if config.view_depth > 0 and supports_views(dialect):
                self._generate_view_hierarchy(connection, dialect, config, generated)

            if config.type_complexity != TypeComplexity.SCALAR and supports_complex_types(dialect):
                self._generate_complex_type_tables(connection, dialect, config, generated)

            if config.constraint_density != ConstraintDensity.NONE and supports_foreign_keys(dialect):
                self._generate_fk_tables(connection, dialect, config, generated)

            if config.acl_role_count > 0 and supports_acl(dialect):
                self._generate_acl_roles(connection, dialect, config, generated)
                self._generate_acl_grants(connection, dialect, config, generated)

                if config.acl_hierarchy_depth != RoleHierarchyDepth.FLAT and supports_role_hierarchy(dialect):
                    self._generate_role_hierarchy(connection, dialect, config, generated)

                if config.acl_column_grants and supports_column_grants(dialect):
                    self._generate_column_grants(connection, dialect, config, generated)

            logger.info(
                f"Generated {generated.total_objects} metadata objects "
                f"({len(generated.tables)} tables, {len(generated.views)} views, "
                f"{len(generated.roles)} roles, {len(generated.grants)} grants)"
            )

        except Exception as e:
            logger.error(f"Error during metadata generation: {e}")
            self.teardown(connection, dialect, generated)
            raise

        return generated

    def teardown(
        self,
        connection: Any,
        dialect: str,
        generated: GeneratedMetadata,
    ) -> None:
        for grant in reversed(generated.grants):
            try:
                sql = generate_revoke_sql(
                    grantee=grant.grantee,
                    object_name=grant.object_name,
                    privileges=grant.privileges,
                    dialect=dialect,
                    object_type=grant.object_type.upper(),
                )
                self._execute(connection, sql)
            except Exception as e:
                logger.warning(f"Failed to revoke grant on {grant.object_name}: {e}")

        for view_name in reversed(generated.views):
            try:
                sql = generate_drop_view_sql(view_name, dialect)
                self._execute(connection, sql)
            except Exception as e:
                logger.warning(f"Failed to drop view {view_name}: {e}")

        for table_name in reversed(generated.tables):
            try:
                sql = generate_drop_table_sql(table_name, dialect)
                self._execute(connection, sql)
            except Exception as e:
                logger.warning(f"Failed to drop table {table_name}: {e}")

        for role_name in reversed(generated.roles):
            try:
                sql = generate_drop_role_sql(role_name, dialect)
                self._execute(connection, sql)
            except Exception as e:
                logger.warning(f"Failed to drop role {role_name}: {e}")

        logger.info(
            f"Cleaned up {generated.total_objects} generated metadata objects ({len(generated.grants)} grants revoked)"
        )

    def cleanup_all(
        self,
        connection: Any,
        dialect: str,
        prefix: str = "benchbox_",
    ) -> int:
        dropped = 0

        views = self._find_objects_with_prefix(connection, dialect, prefix, "view")
        for view_name in views:
            try:
                sql = generate_drop_view_sql(view_name, dialect)
                self._execute(connection, sql)
                dropped += 1
            except Exception as e:
                logger.warning(f"Failed to drop view {view_name}: {e}")

        tables = self._find_objects_with_prefix(connection, dialect, prefix, "table")
        for table_name in tables:
            try:
                sql = generate_drop_table_sql(table_name, dialect)
                self._execute(connection, sql)
                dropped += 1
            except Exception as e:
                logger.warning(f"Failed to drop table {table_name}: {e}")

        if supports_acl(dialect):
            roles = self._find_objects_with_prefix(connection, dialect, prefix, "role")
            for role_name in roles:
                try:
                    sql = generate_drop_role_sql(role_name, dialect)
                    self._execute(connection, sql)
                    dropped += 1
                except Exception as e:
                    logger.warning(f"Failed to drop role {role_name}: {e}")

        logger.info(f"Cleaned up {dropped} objects with prefix '{prefix}'")
        return dropped

    def _generate_wide_tables(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
        generated: GeneratedMetadata,
    ) -> None:
        table_name = f"{config.prefix}wide_{config.width_factor}"
        columns = generate_wide_table_columns(
            config.width_factor,
            dialect,
            config.type_complexity,
        )

        table_def = TableDefinition(name=table_name, columns=columns)
        sql = generate_create_table_sql(table_def, dialect)
        self._execute(connection, sql)
        generated.tables.append(table_name)

        logger.debug(f"Created wide table {table_name} with {len(columns)} columns")

    def _generate_catalog_tables(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
        generated: GeneratedMetadata,
    ) -> None:
        widths = [5, 15, 30]

        for i in range(config.catalog_size):
            width = widths[i % len(widths)]
            table_name = f"{config.prefix}catalog_{i:04d}"

            columns = generate_simple_table_columns(width, dialect)
            table_def = TableDefinition(name=table_name, columns=columns)
            sql = generate_create_table_sql(table_def, dialect)

            self._execute(connection, sql)
            generated.tables.append(table_name)

        logger.debug(f"Created {config.catalog_size} catalog tables")

    def _generate_view_hierarchy(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
        generated: GeneratedMetadata,
    ) -> None:
        if not generated.tables:
            return

        base_table = generated.tables[0]

        previous_source = base_table

        for depth in range(1, config.view_depth + 1):
            view_name = f"{config.prefix}view_d{depth}"

            if depth == 1:
                source_sql = f"SELECT * FROM {previous_source}"
            elif depth == 2:
                source_sql = f"SELECT * FROM {previous_source} WHERE id IS NOT NULL"
            elif depth == 3:
                source_sql = f"SELECT * FROM {previous_source} LIMIT 10000"
            else:
                source_sql = f"SELECT * FROM {previous_source} LIMIT 1000"

            view_def = ViewDefinition(name=view_name, source_sql=source_sql)
            sql = generate_create_view_sql(view_def, dialect)

            self._execute(connection, sql)
            generated.views.append(view_name)

            previous_source = view_name

        logger.debug(f"Created view hierarchy with depth {config.view_depth}")

    def _generate_complex_type_tables(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
        generated: GeneratedMetadata,
    ) -> None:
        if config.type_complexity in (TypeComplexity.BASIC, TypeComplexity.NESTED):
            table_name = f"{config.prefix}complex_basic"
            columns = [
                ColumnDefinition("id", map_type("bigint", dialect), nullable=False, primary_key=True),
                ColumnDefinition("tags", map_type("array_varchar", dialect)),
                ColumnDefinition("scores", map_type("array_int", dialect)),
            ]
            table_def = TableDefinition(name=table_name, columns=columns)
            sql = generate_create_table_sql(table_def, dialect)
            self._execute(connection, sql)
            generated.tables.append(table_name)

        if config.type_complexity == TypeComplexity.NESTED:
            table_name = f"{config.prefix}complex_nested"
            columns = [
                ColumnDefinition("id", map_type("bigint", dialect), nullable=False, primary_key=True),
                ColumnDefinition("metadata", map_type("struct_simple", dialect)),
                ColumnDefinition("nested_data", map_type("struct_nested", dialect)),
            ]

            if dialect.lower() not in ("snowflake", "bigquery"):
                columns.append(ColumnDefinition("properties", map_type("map_simple", dialect)))

            table_def = TableDefinition(name=table_name, columns=columns)
            sql = generate_create_table_sql(table_def, dialect)
            self._execute(connection, sql)
            generated.tables.append(table_name)

        logger.debug(f"Created complex type tables (complexity: {config.type_complexity.value})")

    def _generate_fk_tables(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
        generated: GeneratedMetadata,
    ) -> None:
        parent_name = f"{config.prefix}fk_parent"
        parent_columns = [
            ColumnDefinition("id", map_type("bigint", dialect), nullable=False, primary_key=True),
            ColumnDefinition("name", map_type("varchar", dialect)),
        ]
        parent_def = TableDefinition(name=parent_name, columns=parent_columns)
        sql = generate_create_table_sql(parent_def, dialect)
        self._execute(connection, sql)
        generated.tables.append(parent_name)

        num_children = 2 if config.constraint_density == ConstraintDensity.SPARSE else 5

        for i in range(num_children):
            child_name = f"{config.prefix}fk_child_{i:02d}"

            child_columns = [
                ColumnDefinition("id", map_type("bigint", dialect), nullable=False, primary_key=True),
                ColumnDefinition("parent_id", map_type("bigint", dialect)),
                ColumnDefinition("value", map_type("varchar", dialect)),
            ]
            child_def = TableDefinition(name=child_name, columns=child_columns)
            sql = generate_create_table_sql(child_def, dialect)
            self._execute(connection, sql)
            generated.tables.append(child_name)

            fk_sql = f"""
                ALTER TABLE {child_name}
                ADD CONSTRAINT fk_{child_name}_parent
                FOREIGN KEY (parent_id) REFERENCES {parent_name}(id);
            """
            try:
                self._execute(connection, fk_sql)
            except Exception as e:
                logger.warning(f"Could not add FK constraint to {child_name}: {e}")

        logger.debug(f"Created FK relationship tables (density: {config.constraint_density.value})")

    def _generate_acl_roles(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
        generated: GeneratedMetadata,
    ) -> None:
        for i in range(config.acl_role_count):
            role_name = f"{config.prefix}role_{i:04d}"
            sql = generate_create_role_sql(role_name, dialect)

            if sql.startswith("--"):
                logger.debug(f"Skipping role creation: {sql}")
                continue

            try:
                self._execute(connection, sql)
                generated.roles.append(role_name)
            except Exception as e:
                logger.warning(f"Could not create role {role_name}: {e}")

        logger.debug(f"Created {len(generated.roles)} test roles")

    def _generate_acl_grants(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
        generated: GeneratedMetadata,
    ) -> None:
        if not generated.tables or not generated.roles:
            return

        grants_per_table = self._get_grants_per_table(config.acl_permission_density)

        privilege_sets = [
            ["SELECT"],
            ["SELECT", "INSERT"],
            ["SELECT", "UPDATE"],
            ["SELECT", "INSERT", "UPDATE"],
            ["SELECT", "INSERT", "UPDATE", "DELETE"],
        ]

        grant_index = 0
        for table_name in generated.tables:
            for i in range(min(grants_per_table, len(generated.roles))):
                role_name = generated.roles[i % len(generated.roles)]
                privileges = privilege_sets[grant_index % len(privilege_sets)]

                sql = generate_grant_sql(
                    grantee=role_name,
                    object_name=table_name,
                    privileges=privileges,
                    dialect=dialect,
                    object_type="TABLE",
                    with_grant_option=config.acl_grant_with_grant_option and (i == 0),
                )

                try:
                    self._execute(connection, sql)
                    generated.grants.append(
                        AclGrant(
                            grantee=role_name,
                            object_type="table",
                            object_name=table_name,
                            privileges=privileges,
                            with_grant_option=config.acl_grant_with_grant_option and (i == 0),
                        )
                    )
                except Exception as e:
                    logger.warning(f"Could not grant on {table_name}: {e}")

                grant_index += 1

        logger.debug(f"Created {len(generated.grants)} grants on tables")

    def _generate_role_hierarchy(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
        generated: GeneratedMetadata,
    ) -> None:
        if len(generated.roles) < 2:
            return

        depth_map = {
            RoleHierarchyDepth.FLAT: 0,
            RoleHierarchyDepth.SHALLOW: 2,
            RoleHierarchyDepth.MODERATE: 4,
            RoleHierarchyDepth.DEEP: min(6, len(generated.roles) - 1),
        }
        target_depth = depth_map.get(config.acl_hierarchy_depth, 0)

        if target_depth == 0:
            return

        roles_per_chain = target_depth + 1
        num_chains = max(1, len(generated.roles) // roles_per_chain)

        for chain_idx in range(num_chains):
            start_idx = chain_idx * roles_per_chain
            end_idx = min(start_idx + roles_per_chain, len(generated.roles))

            for i in range(start_idx, end_idx - 1):
                parent_role = generated.roles[i]
                child_role = generated.roles[i + 1]

                sql = generate_grant_role_sql(parent_role, child_role, dialect)

                if sql.startswith("--"):
                    continue

                try:
                    self._execute(connection, sql)
                except Exception as e:
                    logger.warning(f"Could not grant role {parent_role} to {child_role}: {e}")

        logger.debug(f"Created role hierarchy with depth {target_depth}")

    def _generate_column_grants(
        self,
        connection: Any,
        dialect: str,
        config: MetadataComplexityConfig,
        generated: GeneratedMetadata,
    ) -> None:
        if not generated.tables or not generated.roles:
            return

        max_tables = min(5, len(generated.tables))
        max_roles = min(3, len(generated.roles))

        for table_idx in range(max_tables):
            table_name = generated.tables[table_idx]

            columns_to_grant = ["id"]

            for col_name in columns_to_grant:
                for role_idx in range(max_roles):
                    role_name = generated.roles[role_idx]

                    sql = generate_grant_sql(
                        grantee=role_name,
                        object_name=table_name,
                        privileges=["SELECT"],
                        dialect=dialect,
                        object_type="TABLE",
                        column_name=col_name,
                    )

                    try:
                        self._execute(connection, sql)
                        generated.grants.append(
                            AclGrant(
                                grantee=role_name,
                                object_type="column",
                                object_name=f"{table_name}.{col_name}",
                                privileges=["SELECT"],
                            )
                        )
                    except Exception as e:
                        logger.warning(f"Could not grant column on {table_name}.{col_name}: {e}")

        logger.debug("Created column-level grants")

    def _get_grants_per_table(self, density: PermissionDensity) -> int:
        density_map = {
            PermissionDensity.NONE: 0,
            PermissionDensity.SPARSE: 2,
            PermissionDensity.MODERATE: 7,
            PermissionDensity.DENSE: 20,
        }
        return density_map.get(density, 0)

    _OBJECT_SQL: dict[tuple[str, str], str | None] = {
        ("table", "clickhouse"): (
            "SELECT name FROM system.tables WHERE database = currentDatabase() AND name LIKE '{prefix}%'"
        ),
        ("view", "clickhouse"): None,
        ("view", "duckdb"): "SELECT view_name FROM duckdb_views() WHERE view_name LIKE '{prefix}%'",
        ("role", "postgresql"): "SELECT rolname FROM pg_roles WHERE rolname LIKE '{prefix}%'",
        ("role", "postgres"): "SELECT rolname FROM pg_roles WHERE rolname LIKE '{prefix}%'",
        ("role", "redshift"): "SELECT rolname FROM pg_roles WHERE rolname LIKE '{prefix}%'",
        ("role", "clickhouse"): "SELECT name FROM system.roles WHERE name LIKE '{prefix}%'",
        ("role", "synapse"): ("SELECT name FROM sys.database_principals WHERE type = 'R' AND name LIKE '{prefix}%'"),
        ("role", "fabric"): ("SELECT name FROM sys.database_principals WHERE type = 'R' AND name LIKE '{prefix}%'"),
        ("role", "duckdb"): None,
        ("role", "snowflake"): None,
        ("role", "databricks"): None,
    }
    _OBJECT_SQL_DEFAULT: dict[str, str] = {
        "table": (
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_name LIKE '{prefix}%' AND table_type = 'BASE TABLE'"
        ),
        "view": "SELECT table_name FROM information_schema.views WHERE table_name LIKE '{prefix}%'",
    }

    def _find_objects_with_prefix(
        self,
        connection: Any,
        dialect: str,
        prefix: str,
        object_type: str,
    ) -> list[str]:
        d = dialect.lower()
        key = (object_type, d)
        if key in self._OBJECT_SQL:
            template = self._OBJECT_SQL[key]
        elif object_type in self._OBJECT_SQL_DEFAULT:
            template = self._OBJECT_SQL_DEFAULT[object_type]
        else:
            return []

        if template is None:
            return []

        sql = template.format(prefix=prefix)
        if sql is None:
            return []

        try:
            result = self._execute(connection, sql)
            if result is not None:
                rows = result.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            logger.warning(f"Failed to find {object_type}s with prefix '{prefix}': {e}")

        return []

    def _execute(self, connection: Any, sql: str) -> Any:
        if hasattr(connection, "execute"):
            return connection.execute(sql)
        elif hasattr(connection, "cursor"):
            cursor = connection.cursor()
            cursor.execute(sql)
            return cursor
        else:
            raise TypeError(f"Unsupported connection type: {type(connection)}")


__all__ = [
    "MetadataGenerator",
]
