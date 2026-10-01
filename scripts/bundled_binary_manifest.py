"""Generate or check the manifest of the shipped bundled-generator tree."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchbox.utils.binary_manifest import DEFAULT_ROOT, MANIFEST_NAME, build_binary_manifest, verify_binary_tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            payload = build_binary_manifest(args.root)
            destination = args.root / MANIFEST_NAME
            if destination.is_symlink():
                raise ValueError("refusing to overwrite a manifest symlink")
            destination.write_bytes(payload)
        verify_binary_tree(args.root)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Bundled binary manifest failed: {exc}\n")
    print("Bundled binary manifest is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
