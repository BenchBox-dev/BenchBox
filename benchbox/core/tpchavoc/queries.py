"""TPC-Havoc query management module.

Loads, parameterizes, and manages TPC-Havoc queries with variants.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from typing import Any, Optional

from benchbox.core.tpch.queries import TPCHQueries
from benchbox.core.tpchavoc.variants import (
    Q1_VARIANTS,
    Q2_VARIANTS,
    Q3_VARIANTS,
    Q4_VARIANTS,
    Q5_VARIANTS,
    Q6_VARIANTS,
    Q7_VARIANTS,
    Q8_VARIANTS,
    Q9_VARIANTS,
    Q10_VARIANTS,
    Q11_VARIANTS,
    Q12_VARIANTS,
    Q13_VARIANTS,
    Q14_VARIANTS,
    Q15_VARIANTS,
    Q16_VARIANTS,
    Q17_VARIANTS,
    Q18_VARIANTS,
    Q19_VARIANTS,
    Q20_VARIANTS,
    Q21_VARIANTS,
    Q22_VARIANTS,
    VariantGenerator,
)


class TPCHavocQueryManager(TPCHQueries):
    """TPC-Havoc query manager extending TPC-H functionality."""

    def __init__(self, query_dir: Optional[str] = None) -> None:
        """Initialize TPC-Havoc query manager.

        Args:
            query_dir: Directory with TPC-H query templates.
                      If None, loads from package resources.
        """
        super().__init__()
        self.variant_generators = self._initialize_variant_generators()

    def _initialize_variant_generators(self) -> dict[int, dict[int, VariantGenerator]]:
        """Initialize variant generators for all queries."""
        return {
            1: Q1_VARIANTS,
            2: Q2_VARIANTS,
            3: Q3_VARIANTS,
            4: Q4_VARIANTS,
            5: Q5_VARIANTS,
            6: Q6_VARIANTS,
            7: Q7_VARIANTS,
            8: Q8_VARIANTS,
            9: Q9_VARIANTS,
            10: Q10_VARIANTS,
            11: Q11_VARIANTS,
            12: Q12_VARIANTS,
            13: Q13_VARIANTS,
            14: Q14_VARIANTS,
            15: Q15_VARIANTS,
            16: Q16_VARIANTS,
            17: Q17_VARIANTS,
            18: Q18_VARIANTS,
            19: Q19_VARIANTS,
            20: Q20_VARIANTS,
            21: Q21_VARIANTS,
            22: Q22_VARIANTS,
        }

    def get_query_variant(
        self,
        query_id: int,
        variant_id: int,
        params: Optional[dict[str, Any]] = None,
        *,
        scale_factor: float = 1.0,
    ) -> str:
        """Get a specific query variant.

        Args:
            query_id: The query ID (1-22)
            variant_id: The variant ID (1-10)
            params: Optional parameter values to use
            scale_factor: Scale factor for scale-dependent substitution values

        Returns:
            The variant query string

        Raises:
            ValueError: If the query_id or variant_id is invalid
        """
        if query_id not in self.variant_generators:
            raise ValueError(f"Query variants not implemented for query {query_id}")

        if variant_id not in self.variant_generators[query_id]:
            raise ValueError(f"Invalid variant ID: {variant_id}. Must be between 1 and 10.")

        variant_generator = self.variant_generators[query_id][variant_id]
        base_query = self.get_query(query_id)
        # Scale-dependent substitutions are defaults, so explicit caller params
        # can never suppress them and leak a raw {token} into the SQL.
        merged = {**(self._variant_scale_params(query_id, scale_factor) or {}), **(params or {})}
        return variant_generator.generate(base_query, merged or None)

    @staticmethod
    def _variant_scale_params(query_id: int, scale_factor: float) -> Optional[dict[str, Any]]:
        """Scale-dependent substitution values for variant SQL templates.

        Canonical TPC-H Q11 divides the 0.0001 value-fraction threshold by the
        scale factor (qgen renders it as a 10-decimal literal); the Q11 variants
        carry a ``{q11_fraction}`` token so they scale the same way.
        """
        if query_id == 11:
            return {"q11_fraction": f"{0.0001 / scale_factor:.10f}"}
        return None

    def get_all_variants(self, query_id: int, *, scale_factor: float = 1.0) -> dict[int, str]:
        """Get all variants for a specific query.

        Args:
            query_id: The query ID (1-22)
            scale_factor: Scale factor for scale-dependent substitution values

        Returns:
            Dictionary mapping variant IDs to query strings

        Raises:
            ValueError: If the query_id is invalid or not implemented
        """
        if query_id not in self.variant_generators:
            raise ValueError(f"Query variants not implemented for query {query_id}")

        return {
            variant_id: self.get_query_variant(query_id, variant_id, scale_factor=scale_factor)
            for variant_id in self.variant_generators[query_id]
        }

    def get_variant_description(self, query_id: int, variant_id: int) -> str:
        """Get description of a specific variant.

        Args:
            query_id: The query ID (1-22)
            variant_id: The variant ID (1-10)

        Returns:
            Human-readable description of the variant

        Raises:
            ValueError: If the query_id or variant_id is invalid
        """
        if query_id not in self.variant_generators:
            raise ValueError(f"Query variants not implemented for query {query_id}")

        if variant_id not in self.variant_generators[query_id]:
            raise ValueError(f"Invalid variant ID: {variant_id}. Must be between 1 and 10.")

        return self.variant_generators[query_id][variant_id].get_description()

    def get_implemented_queries(self) -> list[int]:
        """Get list of query IDs that have variants implemented.

        Returns:
            List of query IDs with implemented variants
        """
        return list(self.variant_generators.keys())

    def get_parameterized_query_variant(
        self, query_id: int, variant_id: int, params: Optional[dict[str, Any]] = None
    ) -> str:
        """Get a parameterized TPC-Havoc query variant.

        Args:
            query_id: The query ID (1-22)
            variant_id: The variant ID (1-10)
            params: Optional parameter values to use
                   If None, random parameters will be generated

        Returns:
            The parameterized variant query string

        Raises:
            ValueError: If the query_id or variant_id is invalid
        """
        if query_id not in self.variant_generators:
            raise ValueError(f"Query variants not implemented for query {query_id}")

        if variant_id not in self.variant_generators[query_id]:
            raise ValueError(f"Invalid variant ID: {variant_id}. Must be between 1 and 10.")

        # If no params provided, generate random ones using the base TPC-H logic
        if params is None:
            params = self._generate_random_params(query_id)

        variant_generator = self.variant_generators[query_id][variant_id]
        base_query = self.get_query(query_id)
        return variant_generator.generate(base_query, params)

    def get_all_variants_info(self, query_id: int) -> dict[int, dict[str, str | int]]:
        """Get information about all variants for a specific query.

        Args:
            query_id: The query ID (1-22)

        Returns:
            Dictionary mapping variant IDs to variant info (description, etc.)

        Raises:
            ValueError: If the query_id is invalid or not implemented
        """
        if query_id not in self.variant_generators:
            raise ValueError(f"Query variants not implemented for query {query_id}")

        return {
            variant_id: {
                "description": generator.get_description(),
                "variant_id": variant_id,
            }
            for variant_id, generator in self.variant_generators[query_id].items()
        }

    def get_all_queries(self, **kwargs) -> dict[str, str]:
        """Get all TPC-Havoc queries including all variants.

        This method overrides the parent to return all variants as regular queries.
        Query keys are in the format "Q_VID" (e.g., "1_v1", "1_v2", etc.)

        Args:
            **kwargs: Additional arguments passed to query generation
                (``scale_factor`` is used for scale-dependent substitution values)

        Returns:
            Dictionary mapping query IDs to query strings for all variants
        """
        all_queries = {}
        scale_factor = kwargs.get("scale_factor", 1.0)

        # Add all variants as regular queries
        for query_id in self.variant_generators:
            for variant_id in self.variant_generators[query_id]:
                query_key = f"{query_id}_v{variant_id}"
                try:
                    all_queries[query_key] = self.get_query_variant(query_id, variant_id, scale_factor=scale_factor)
                except Exception:
                    # Skip variants that fail to generate
                    continue

        return all_queries

    def get_query(
        self,
        query_id,
        *,
        seed: Optional[int] = None,
        scale_factor: float = 1.0,
        **kwargs,
    ) -> str:
        """Get a TPC-Havoc query by ID.

        This method is overridden to handle both regular query IDs (1-22) and
        variant query IDs in the format "Q_VID" (e.g., "1_v1", "1_v2").

        Args:
            query_id: Query ID as int (1-22) or string ("1_v1", "1_v2", etc.)
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations
            **kwargs: Additional arguments for backward compatibility

        Returns:
            The query string

        Raises:
            ValueError: If the query_id format is invalid
        """
        # Handle variant query IDs (e.g., "1_v1", "1_v2")
        if isinstance(query_id, str) and "_v" in query_id:
            try:
                parts = query_id.split("_v")
                if len(parts) != 2:
                    raise ValueError(f"Invalid variant query ID format: {query_id}")

                base_query_id = int(parts[0])
                variant_id = int(parts[1])

                # Generate parameters if needed
                params = kwargs.get("params") or self._generate_random_params(base_query_id, seed, scale_factor)
                return self.get_query_variant(base_query_id, variant_id, params, scale_factor=scale_factor)
            except (ValueError, IndexError) as e:
                raise ValueError(f"Invalid variant query ID format: {query_id}") from e

        # Handle regular query IDs (fallback to parent implementation)
        return super().get_query(query_id, seed=seed, scale_factor=scale_factor)

    def _generate_random_params(
        self, query_id: int, seed: Optional[int] = None, scale_factor: float = 1.0
    ) -> Optional[dict[str, Any]]:
        """Generate random parameters for a query.

        Args:
            query_id: The query ID
            seed: Optional seed for reproducible parameters
            scale_factor: Scale factor for parameter generation

        Returns:
            Dictionary of parameters or None
        """
        # For now, return None to use default parameterization
        # This supports TPC-H parameter generation
        return None
