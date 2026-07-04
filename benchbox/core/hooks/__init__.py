"""Benchmark and platform CLI-option hook registries.

Relocated out of the ``benchbox.cli`` package (see
``_project/TODO/main/planning/relocate-cli-hook-registries.yaml``). These are
dependency-free, data-holding registries that let benchmarks and platform
adapters expose CLI option hooks (``--benchmark-option K=V`` /
``--platform-option K=V``) without ``benchbox.core``/``benchbox.platforms``
importing "up" into ``benchbox.cli``.

The former CLI-package module locations remain as back-compat re-export
shims pointing at this package (see the sibling modules of the same name
under ``benchbox/cli/``).
"""
