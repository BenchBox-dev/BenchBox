# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TypeComplexity(Enum):
    SCALAR = "scalar"
    BASIC = "basic"
    NESTED = "nested"


class ConstraintDensity(Enum):
    NONE = "none"
    SPARSE = "sparse"
    DENSE = "dense"


class PermissionDensity(Enum):
    NONE = "none"
    SPARSE = "sparse"
    MODERATE = "moderate"
    DENSE = "dense"


class RoleHierarchyDepth(Enum):
    FLAT = "flat"
    SHALLOW = "shallow"
    MODERATE = "moderate"
    DEEP = "deep"


@dataclass
class MetadataComplexityConfig:
    width_factor: int = 50
    view_depth: int = 1
    type_complexity: TypeComplexity = TypeComplexity.SCALAR
    catalog_size: int = 10
    constraint_density: ConstraintDensity = ConstraintDensity.NONE
    schema_count: int = 1
    prefix: str = "benchbox_"

    acl_role_count: int = 0
    acl_permission_density: PermissionDensity = PermissionDensity.NONE
    acl_hierarchy_depth: RoleHierarchyDepth = RoleHierarchyDepth.FLAT
    acl_column_grants: bool = False
    acl_grant_with_grant_option: bool = False

    def __post_init__(self) -> None:
        if self.width_factor < 1:
            raise ValueError(f"width_factor must be >= 1, got {self.width_factor}")
        if self.width_factor > 10000:
            raise ValueError(f"width_factor must be <= 10000, got {self.width_factor}")

        if self.view_depth < 0:
            raise ValueError(f"view_depth must be >= 0, got {self.view_depth}")
        if self.view_depth > 10:
            raise ValueError(f"view_depth must be <= 10, got {self.view_depth}")

        if self.catalog_size < 1:
            raise ValueError(f"catalog_size must be >= 1, got {self.catalog_size}")
        if self.catalog_size > 5000:
            raise ValueError(f"catalog_size must be <= 5000, got {self.catalog_size}")

        if self.schema_count < 1:
            raise ValueError(f"schema_count must be >= 1, got {self.schema_count}")

        if isinstance(self.type_complexity, str):
            self.type_complexity = TypeComplexity(self.type_complexity)

        if isinstance(self.constraint_density, str):
            self.constraint_density = ConstraintDensity(self.constraint_density)

        if self.acl_role_count < 0:
            raise ValueError(f"acl_role_count must be >= 0, got {self.acl_role_count}")
        if self.acl_role_count > 500:
            raise ValueError(f"acl_role_count must be <= 500, got {self.acl_role_count}")

        if isinstance(self.acl_permission_density, str):
            self.acl_permission_density = PermissionDensity(self.acl_permission_density)

        if isinstance(self.acl_hierarchy_depth, str):
            self.acl_hierarchy_depth = RoleHierarchyDepth(self.acl_hierarchy_depth)

    def to_dict(self) -> dict[str, Any]:
        return {
            "width_factor": self.width_factor,
            "view_depth": self.view_depth,
            "type_complexity": self.type_complexity.value,
            "catalog_size": self.catalog_size,
            "constraint_density": self.constraint_density.value,
            "schema_count": self.schema_count,
            "prefix": self.prefix,
            "acl_role_count": self.acl_role_count,
            "acl_permission_density": self.acl_permission_density.value,
            "acl_hierarchy_depth": self.acl_hierarchy_depth.value,
            "acl_column_grants": self.acl_column_grants,
            "acl_grant_with_grant_option": self.acl_grant_with_grant_option,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetadataComplexityConfig:
        return cls(
            width_factor=data.get("width_factor", 50),
            view_depth=data.get("view_depth", 1),
            type_complexity=TypeComplexity(data.get("type_complexity", "scalar")),
            catalog_size=data.get("catalog_size", 10),
            constraint_density=ConstraintDensity(data.get("constraint_density", "none")),
            schema_count=data.get("schema_count", 1),
            prefix=data.get("prefix", "benchbox_"),
            acl_role_count=data.get("acl_role_count", 0),
            acl_permission_density=PermissionDensity(data.get("acl_permission_density", "none")),
            acl_hierarchy_depth=RoleHierarchyDepth(data.get("acl_hierarchy_depth", "flat")),
            acl_column_grants=data.get("acl_column_grants", False),
            acl_grant_with_grant_option=data.get("acl_grant_with_grant_option", False),
        )


COMPLEXITY_PRESETS: dict[str, MetadataComplexityConfig] = {
    "minimal": MetadataComplexityConfig(
        width_factor=20,
        view_depth=1,
        type_complexity=TypeComplexity.SCALAR,
        catalog_size=5,
        constraint_density=ConstraintDensity.NONE,
    ),
    "baseline": MetadataComplexityConfig(
        width_factor=50,
        view_depth=1,
        type_complexity=TypeComplexity.SCALAR,
        catalog_size=10,
        constraint_density=ConstraintDensity.NONE,
    ),
    "wide_tables": MetadataComplexityConfig(
        width_factor=500,
        view_depth=1,
        type_complexity=TypeComplexity.SCALAR,
        catalog_size=10,
        constraint_density=ConstraintDensity.NONE,
    ),
    "deep_views": MetadataComplexityConfig(
        width_factor=50,
        view_depth=4,
        type_complexity=TypeComplexity.SCALAR,
        catalog_size=10,
        constraint_density=ConstraintDensity.NONE,
    ),
    "complex_types": MetadataComplexityConfig(
        width_factor=50,
        view_depth=1,
        type_complexity=TypeComplexity.NESTED,
        catalog_size=10,
        constraint_density=ConstraintDensity.NONE,
    ),
    "large_catalog": MetadataComplexityConfig(
        width_factor=30,
        view_depth=1,
        type_complexity=TypeComplexity.SCALAR,
        catalog_size=100,
        constraint_density=ConstraintDensity.NONE,
    ),
    "full": MetadataComplexityConfig(
        width_factor=200,
        view_depth=3,
        type_complexity=TypeComplexity.BASIC,
        catalog_size=50,
        constraint_density=ConstraintDensity.SPARSE,
    ),
    "stress": MetadataComplexityConfig(
        width_factor=1000,
        view_depth=5,
        type_complexity=TypeComplexity.NESTED,
        catalog_size=200,
        constraint_density=ConstraintDensity.DENSE,
    ),
    "acl_sparse": MetadataComplexityConfig(
        width_factor=20,
        view_depth=0,
        type_complexity=TypeComplexity.SCALAR,
        catalog_size=5,
        constraint_density=ConstraintDensity.NONE,
        acl_role_count=5,
        acl_permission_density=PermissionDensity.SPARSE,
        acl_hierarchy_depth=RoleHierarchyDepth.FLAT,
    ),
    "acl_moderate": MetadataComplexityConfig(
        width_factor=30,
        view_depth=0,
        type_complexity=TypeComplexity.SCALAR,
        catalog_size=10,
        constraint_density=ConstraintDensity.NONE,
        acl_role_count=20,
        acl_permission_density=PermissionDensity.MODERATE,
        acl_hierarchy_depth=RoleHierarchyDepth.SHALLOW,
    ),
    "acl_dense": MetadataComplexityConfig(
        width_factor=30,
        view_depth=0,
        type_complexity=TypeComplexity.SCALAR,
        catalog_size=20,
        constraint_density=ConstraintDensity.NONE,
        acl_role_count=50,
        acl_permission_density=PermissionDensity.DENSE,
        acl_hierarchy_depth=RoleHierarchyDepth.MODERATE,
        acl_grant_with_grant_option=True,
    ),
    "acl_hierarchy": MetadataComplexityConfig(
        width_factor=20,
        view_depth=0,
        type_complexity=TypeComplexity.SCALAR,
        catalog_size=5,
        constraint_density=ConstraintDensity.NONE,
        acl_role_count=30,
        acl_permission_density=PermissionDensity.SPARSE,
        acl_hierarchy_depth=RoleHierarchyDepth.DEEP,
    ),
    "acl_full": MetadataComplexityConfig(
        width_factor=50,
        view_depth=1,
        type_complexity=TypeComplexity.BASIC,
        catalog_size=20,
        constraint_density=ConstraintDensity.SPARSE,
        acl_role_count=30,
        acl_permission_density=PermissionDensity.MODERATE,
        acl_hierarchy_depth=RoleHierarchyDepth.MODERATE,
        acl_column_grants=True,
        acl_grant_with_grant_option=True,
    ),
}


def get_complexity_preset(name: str) -> MetadataComplexityConfig:
    if name not in COMPLEXITY_PRESETS:
        available = ", ".join(sorted(COMPLEXITY_PRESETS.keys()))
        raise ValueError(f"Unknown complexity preset '{name}'. Available: {available}")
    return COMPLEXITY_PRESETS[name]


@dataclass
class AclGrant:
    grantee: str
    object_type: str
    object_name: str
    privileges: list[str] = field(default_factory=list)
    with_grant_option: bool = False


@dataclass
class GeneratedMetadata:
    tables: list[str] = field(default_factory=list)
    views: list[str] = field(default_factory=list)
    schemas: list[str] = field(default_factory=list)
    prefix: str = "benchbox_"
    config: MetadataComplexityConfig | None = None
    roles: list[str] = field(default_factory=list)
    grants: list[AclGrant] = field(default_factory=list)

    @property
    def total_objects(self) -> int:
        return len(self.tables) + len(self.views) + len(self.schemas) + len(self.roles)

    @property
    def total_grants(self) -> int:
        return len(self.grants)

    def summary(self) -> dict[str, Any]:
        return {
            "tables": len(self.tables),
            "views": len(self.views),
            "schemas": len(self.schemas),
            "roles": len(self.roles),
            "grants": len(self.grants),
            "total": self.total_objects,
            "prefix": self.prefix,
        }


__all__ = [
    "AclGrant",
    "ConstraintDensity",
    "GeneratedMetadata",
    "MetadataComplexityConfig",
    "PermissionDensity",
    "RoleHierarchyDepth",
    "TypeComplexity",
    "COMPLEXITY_PRESETS",
    "get_complexity_preset",
]
