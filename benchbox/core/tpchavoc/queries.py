# Copyright 2026 Joe Harris / BenchBox Project

# This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

# Licensed under the MIT License. See LICENSE file in the project root for details.

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
    def __init__(self, query_dir: Optional[str] = None) -> None:
        super().__init__()
        self.variant_generators = self._initialize_variant_generators()

    def _initialize_variant_generators(self) -> dict[int, dict[int, VariantGenerator]]:
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
        if query_id not in self.variant_generators:
            raise ValueError(f"Query variants not implemented for query {query_id}")

        if variant_id not in self.variant_generators[query_id]:
            raise ValueError(f"Invalid variant ID: {variant_id}. Must be between 1 and 10.")

        variant_generator = self.variant_generators[query_id][variant_id]
        base_query = self.get_query(query_id)
        merged = {**(self._variant_scale_params(query_id, scale_factor) or {}), **(params or {})}
        return variant_generator.generate(base_query, merged or None)

    @staticmethod
    def _variant_scale_params(query_id: int, scale_factor: float) -> Optional[dict[str, Any]]:
        if query_id == 11:
            return {"q11_fraction": f"{0.0001 / scale_factor:.10f}"}
        return None

    def get_all_variants(self, query_id: int, *, scale_factor: float = 1.0) -> dict[int, str]:
        if query_id not in self.variant_generators:
            raise ValueError(f"Query variants not implemented for query {query_id}")

        return {
            variant_id: self.get_query_variant(query_id, variant_id, scale_factor=scale_factor)
            for variant_id in self.variant_generators[query_id]
        }

    def get_variant_description(self, query_id: int, variant_id: int) -> str:
        if query_id not in self.variant_generators:
            raise ValueError(f"Query variants not implemented for query {query_id}")

        if variant_id not in self.variant_generators[query_id]:
            raise ValueError(f"Invalid variant ID: {variant_id}. Must be between 1 and 10.")

        return self.variant_generators[query_id][variant_id].get_description()

    def get_implemented_queries(self) -> list[int]:
        return list(self.variant_generators.keys())

    def get_parameterized_query_variant(
        self, query_id: int, variant_id: int, params: Optional[dict[str, Any]] = None, *, scale_factor: float = 1.0
    ) -> str:
        if query_id not in self.variant_generators:
            raise ValueError(f"Query variants not implemented for query {query_id}")

        if variant_id not in self.variant_generators[query_id]:
            raise ValueError(f"Invalid variant ID: {variant_id}. Must be between 1 and 10.")

        if params is None:
            params = self._generate_random_params(query_id)

        merged = {**(self._variant_scale_params(query_id, scale_factor) or {}), **(params or {})}

        variant_generator = self.variant_generators[query_id][variant_id]
        base_query = self.get_query(query_id)
        return variant_generator.generate(base_query, merged or None)

    def get_all_variants_info(self, query_id: int) -> dict[int, dict[str, str | int]]:
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
        all_queries = {}
        scale_factor = kwargs.get("scale_factor", 1.0)

        for query_id in self.variant_generators:
            for variant_id in self.variant_generators[query_id]:
                query_key = f"{query_id}_v{variant_id}"
                try:
                    all_queries[query_key] = self.get_query_variant(query_id, variant_id, scale_factor=scale_factor)
                except Exception:
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
        if isinstance(query_id, str) and "_v" in query_id:
            try:
                parts = query_id.split("_v")
                if len(parts) != 2:
                    raise ValueError(f"Invalid variant query ID format: {query_id}")

                base_query_id = int(parts[0])
                variant_id = int(parts[1])

                params = kwargs.get("params") or self._generate_random_params(base_query_id, seed, scale_factor)
                return self.get_query_variant(base_query_id, variant_id, params, scale_factor=scale_factor)
            except (ValueError, IndexError) as e:
                raise ValueError(f"Invalid variant query ID format: {query_id}") from e

        return super().get_query(query_id, seed=seed, scale_factor=scale_factor)

    def _generate_random_params(
        self, query_id: int, seed: Optional[int] = None, scale_factor: float = 1.0
    ) -> Optional[dict[str, Any]]:
        return None
