"""TPC-DS Distribution File Parser

This module provides functionality to parse TPC-DS distribution files (.dst)
that define weighted distributions for parameter generation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import re
from pathlib import Path
from typing import Any, Optional

from benchbox.utils.printing import emit


class TPCDSDistribution:
    """Represents a single TPC-DS distribution from a .dst file."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.types: list[str] = []
        self.weights: int = 0
        self.weight_names: list[str] = []
        self.entries: list[dict[str, Any]] = []

    def add_entry(self, value: str, weights: list[float]) -> None:
        """Add an entry to the distribution with its weights."""
        if len(weights) != self.weights:
            raise ValueError(f"Weight count mismatch: expected {self.weights}, got {len(weights)}")

        entry = {"value": value, "weights": weights}
        self.entries.append(entry)

    def get_weighted_entries(self, weight_set: int = 0) -> list[tuple[str, float]]:
        """Get entries with their weights for a specific weight set."""
        if weight_set >= self.weights:
            raise ValueError(f"Invalid weight set {weight_set}, max is {self.weights - 1}")

        return [(entry["value"], entry["weights"][weight_set]) for entry in self.entries]

    def __repr__(self) -> str:
        return f"TPCDSDistribution(name='{self.name}', entries={len(self.entries)})"


class TPCDSDistributionParser:
    """Parser for TPC-DS distribution files (.dst)."""

    def __init__(self) -> None:
        self.distributions: dict[str, TPCDSDistribution] = {}

    @staticmethod
    def _clean_lines(content: str) -> list[str]:
        """Strip comments and blank lines from a .dst file body."""
        cleaned: list[str] = []
        for raw in content.split("\n"):
            if "--" in raw:
                raw = raw[: raw.index("--")]
            line = raw.strip()
            if line:
                cleaned.append(line)
        return cleaned

    @staticmethod
    def _handle_create(line: str, distributions: dict[str, TPCDSDistribution]) -> Optional[TPCDSDistribution]:
        """Handle `create <name>;` - returns the new current distribution or None."""
        match = re.match(r"create\s+(\w+);?", line)
        if not match:
            return None
        dist_name = match.group(1)
        current_dist = TPCDSDistribution(dist_name)
        distributions[dist_name] = current_dist
        return current_dist

    @staticmethod
    def _handle_set_types(line: str, current_dist: Optional[TPCDSDistribution]) -> None:
        if current_dist is None:
            return
        match = re.match(r"set\s+types\s*=\s*\(([^)]+)\);?", line)
        if match:
            current_dist.types = [t.strip() for t in match.group(1).split(",")]

    @staticmethod
    def _handle_set_weights(line: str, current_dist: Optional[TPCDSDistribution]) -> None:
        if current_dist is None:
            return
        match = re.match(r"set\s+weights\s*=\s*(\d+);?", line)
        if match:
            current_dist.weights = int(match.group(1))

    @staticmethod
    def _handle_set_names(line: str, current_dist: Optional[TPCDSDistribution]) -> None:
        if current_dist is None:
            return
        match = re.match(r"set\s+names\s*=\s*\(([^)]+)\);?", line)
        if not match:
            return
        names: list[str] = []
        for raw_name in match.group(1).split(","):
            name = raw_name.strip()
            if ":" in name:
                name = name.split(":")[0]
            names.append(name)
        current_dist.weight_names = names

    def _handle_add(self, line: str, current_dist: Optional[TPCDSDistribution]) -> None:
        if current_dist is None:
            return
        paren_content = self._extract_parentheses_content(line)
        if not paren_content:
            return
        parts = self._parse_add_statement(paren_content)
        if not parts:
            return
        value, weights = parts
        current_dist.add_entry(value, weights)

    def parse_file(self, file_path: Path) -> dict[str, TPCDSDistribution]:
        """Parse a single .dst file and return distributions."""
        distributions: dict[str, TPCDSDistribution] = {}

        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        current_dist: Optional[TPCDSDistribution] = None
        for line in self._clean_lines(content):
            if line.startswith("create "):
                current_dist = self._handle_create(line, distributions) or current_dist
            elif line.startswith("set types"):
                self._handle_set_types(line, current_dist)
            elif line.startswith("set weights"):
                self._handle_set_weights(line, current_dist)
            elif line.startswith("set names"):
                self._handle_set_names(line, current_dist)
            elif line.startswith("add ("):
                self._handle_add(line, current_dist)

        return distributions

    def _extract_parentheses_content(self, line: str) -> Optional[str]:
        """Extract content between parentheses, handling nested parentheses."""
        start = line.find("(")
        if start == -1:
            return None

        paren_count = 0
        for i in range(start, len(line)):
            if line[i] == "(":
                paren_count += 1
            elif line[i] == ")":
                paren_count -= 1
                if paren_count == 0:
                    return line[start + 1 : i]

        return None

    def _parse_add_statement(self, content: str) -> Optional[tuple[str, list[float]]]:
        """Parse the content of an add statement."""
        # Handle quoted strings with colons: "Midway":212, 1, 1, 0, 0, 600
        if content.startswith('"') and '":' in content:
            # Find the end of the quoted value
            end_quote = content.find('"', 1)
            if end_quote == -1:
                return None

            value = content[1:end_quote]
            weights_str = content[end_quote + 2 :]  # Skip ":

            # Parse weights
            try:
                weights = [float(w.strip()) for w in weights_str.split(",")]
                return value, weights
            except ValueError:
                return None

        # Handle simple format: value, weight1, weight2, ...
        parts = [p.strip() for p in content.split(",")]
        if len(parts) >= 2:
            value = parts[0].strip('"')
            try:
                weights = [float(w) for w in parts[1:]]
                return value, weights
            except ValueError:
                return None

        return None

    def parse_directory(self, directory_path: Path) -> dict[str, TPCDSDistribution]:
        """Parse all .dst files in a directory."""
        all_distributions = {}

        for dst_file in directory_path.glob("*.dst"):
            try:
                distributions = self.parse_file(dst_file)
                all_distributions.update(distributions)
            except Exception as e:
                emit(f"Warning: Failed to parse {dst_file}: {e}")

        return all_distributions

    def load_tpcds_distributions(self, tpcds_tools_path: Path) -> dict[str, TPCDSDistribution]:
        """Load all standard TPC-DS distributions from the tools directory."""
        return self.parse_directory(tpcds_tools_path)


if __name__ == "__main__":  # pragma: no cover
    # Test the parser
    parser = TPCDSDistributionParser()

    # Test with a sample file
    import os
    import tempfile

    sample_dst_content = """--
-- Sample distribution file
--
create cities;
set types = (varchar);
set weights = 6;
set names = (name:usgs, uniform, large, medium, small, unified);
add ("Midway":212, 1, 1, 0, 0, 600);
add ("Fairview":199, 1, 1, 0, 0, 600);
add ("Oak Grove":160, 1, 1, 0, 0, 600);
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".dst", delete=False, encoding="utf-8") as f:  # pragma: no cover
        f.write(sample_dst_content)
        temp_file = f.name

    try:
        distributions = parser.parse_file(Path(temp_file))  # pragma: no cover
        for name, dist in distributions.items():  # pragma: no cover
            emit(f"Distribution: {name}")
            emit(f"  Types: {dist.types}")
            emit(f"  Weights: {dist.weights}")
            emit(f"  Weight names: {dist.weight_names}")
            emit(f"  Entries: {len(dist.entries)}")
            for entry in dist.entries[:3]:  # Show first 3 entries
                emit(f"    {entry['value']}: {entry['weights']}")
    finally:  # pragma: no cover
        os.unlink(temp_file)
