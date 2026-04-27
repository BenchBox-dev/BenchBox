"""
Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from setuptools import find_packages, setup

setup(
    name="benchbox",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pytest>=6.0.0",
        "pytest-cov>=2.10.0",
        "pytest-mock>=3.3.0",
    ],
    python_requires=">=3.10",
)
