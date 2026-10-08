#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import sys


def main():
    print("=" * 60)
    print("DEPRECATED: validate_streaming_imports.py")
    print("=" * 60)
    print()
    print("This file has been moved to:")
    print("  tests/utilities/tpcdi_import_validator.py")
    print()
    print("Please update your scripts to use the new location.")
    print()
    print("To run the validator:")
    print("  python tests/utilities/tpcdi_import_validator.py")
    print()
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
