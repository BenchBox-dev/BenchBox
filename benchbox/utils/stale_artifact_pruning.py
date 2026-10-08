from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from glob import escape as glob_escape
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableArtifactPattern:
    single_suffix: str
    raw_shard_glob_template: str
    compressed_shard_glob_template: str
    shard_regex_template: str


def _collect_shards(target_dir: Path, shard_glob: str, shard_pattern: re.Pattern[str]) -> list[Path]:
    return [path for path in target_dir.glob(shard_glob) if path.is_file() and shard_pattern.fullmatch(path.name)]


def prune_stale_table_artifacts(
    *,
    target_dir: Path,
    table_names: list[str] | tuple[str, ...],
    pattern: TableArtifactPattern,
    compression_extensions: list[str] | tuple[str, ...],
    use_compression: bool,
    expect_sharded: bool,
) -> list[Path]:
    removed: list[Path] = []
    for table_name in table_names:
        removed_for_table = 0
        safe_table_for_glob = glob_escape(table_name)
        shard_pattern = re.compile(pattern.shard_regex_template.format(table=re.escape(table_name)))
        raw_single = target_dir / f"{table_name}{pattern.single_suffix}"
        raw_shards = _collect_shards(
            target_dir,
            pattern.raw_shard_glob_template.format(table=safe_table_for_glob),
            shard_pattern,
        )

        compressed_single: list[Path] = []
        compressed_shards: list[Path] = []
        for ext in compression_extensions:
            single = target_dir / f"{table_name}{pattern.single_suffix}{ext}"
            if single.is_file():
                compressed_single.append(single)
            compressed_shards.extend(
                _collect_shards(
                    target_dir,
                    pattern.compressed_shard_glob_template.format(table=safe_table_for_glob, ext=glob_escape(ext)),
                    shard_pattern,
                )
            )

        to_remove: list[Path] = []
        if use_compression:
            to_remove.extend(raw_shards)
            if raw_single.is_file():
                to_remove.append(raw_single)
            if compressed_single and compressed_shards:
                if expect_sharded:
                    to_remove.extend(compressed_single)
                else:
                    to_remove.extend(compressed_shards)
        else:
            to_remove.extend(compressed_single)
            to_remove.extend(compressed_shards)
            if raw_single.is_file() and raw_shards:
                if expect_sharded:
                    to_remove.append(raw_single)
                else:
                    to_remove.extend(raw_shards)

        for candidate in to_remove:
            if not candidate.is_file():
                continue
            try:
                candidate.unlink()
                removed.append(candidate)
                removed_for_table += 1
            except OSError:
                logger.warning("Failed to remove stale artifact: %s", candidate, exc_info=True)
                continue
        if removed_for_table:
            logger.debug("Removed %d stale artifacts for table %s in %s", removed_for_table, table_name, target_dir)

    return removed
