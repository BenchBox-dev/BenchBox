# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from abc import ABC, abstractmethod
from typing import Any

import numpy as np


class SkewDistribution(ABC):
    @abstractmethod
    def sample(self, size: int, rng: np.random.Generator) -> np.ndarray:
        pass

    @abstractmethod
    def get_skew_factor(self) -> float:
        pass

    @abstractmethod
    def get_description(self) -> str:
        pass

    def map_to_range(self, samples: np.ndarray, min_val: int, max_val: int) -> np.ndarray:
        return np.floor(samples * (max_val - min_val + 1) + min_val).astype(np.int64)


class ZipfianDistribution(SkewDistribution):
    def __init__(self, s: float = 1.0, num_elements: int = 1000):
        if s < 0:
            raise ValueError(f"Zipf exponent must be non-negative, got {s}")
        if num_elements < 1:
            raise ValueError(f"num_elements must be positive, got {num_elements}")

        self.s = s
        self.num_elements = num_elements

        self._harmonic = self._compute_harmonic()

    def _compute_harmonic(self) -> float:
        ranks = np.arange(1, self.num_elements + 1, dtype=np.float64)
        return np.sum(1.0 / np.power(ranks, self.s))

    def sample(self, size: int, rng: np.random.Generator) -> np.ndarray:
        if self.s == 0:
            return rng.random(size)

        u = rng.random(size)
        ranks = np.zeros(size, dtype=np.float64)

        cumsum = 0.0
        cdf = np.zeros(self.num_elements)
        for k in range(1, self.num_elements + 1):
            cumsum += 1.0 / (k**self.s * self._harmonic)
            cdf[k - 1] = cumsum

        for i in range(size):
            rank = np.searchsorted(cdf, u[i])
            ranks[i] = rank / self.num_elements

        return ranks

    def get_skew_factor(self) -> float:
        return min(self.s / 2.0, 1.0)

    def get_description(self) -> str:
        return f"Zipfian(s={self.s}, N={self.num_elements})"


class NormalDistribution(SkewDistribution):
    def __init__(self, mean: float = 0.5, std: float = 0.15):
        if not 0 <= mean <= 1:
            raise ValueError(f"mean must be in [0, 1], got {mean}")
        if std <= 0:
            raise ValueError(f"std must be positive, got {std}")

        self.mean = mean
        self.std = std

    def sample(self, size: int, rng: np.random.Generator) -> np.ndarray:
        samples = rng.normal(self.mean, self.std, size)
        return np.clip(samples, 0, 1)

    def get_skew_factor(self) -> float:
        return max(0, 1 - self.std / 0.5)

    def get_description(self) -> str:
        return f"Normal(μ={self.mean}, σ={self.std})"


class ExponentialDistribution(SkewDistribution):
    def __init__(self, rate: float = 3.0):
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")

        self.rate = rate

    def sample(self, size: int, rng: np.random.Generator) -> np.ndarray:
        samples = rng.exponential(1.0 / self.rate, size)
        normalized = samples / (samples + 1)
        return normalized

    def get_skew_factor(self) -> float:
        return min(self.rate / 5.0, 1.0)

    def get_description(self) -> str:
        return f"Exponential(λ={self.rate})"


class UniformDistribution(SkewDistribution):
    def sample(self, size: int, rng: np.random.Generator) -> np.ndarray:
        return rng.random(size)

    def get_skew_factor(self) -> float:
        return 0.0

    def get_description(self) -> str:
        return "Uniform"


def create_distribution(dist_type: str, **params: Any) -> SkewDistribution:
    dist_type = dist_type.lower()

    if dist_type == "zipfian":
        return ZipfianDistribution(**params)
    elif dist_type == "normal":
        return NormalDistribution(**params)
    elif dist_type == "exponential":
        return ExponentialDistribution(**params)
    elif dist_type == "uniform":
        return UniformDistribution()
    else:
        raise ValueError(f"Unknown distribution type: {dist_type}. Valid types: zipfian, normal, exponential, uniform")
