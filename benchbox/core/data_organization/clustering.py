from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa
import pyarrow.compute as pc

_Z_ORDER_KEY_COLUMN = "__benchbox_z_order_key__"
_HILBERT_KEY_COLUMN = "__benchbox_hilbert_key__"


def z_order_key(values: list[int], bits: int = 32) -> int:
    if bits <= 0:
        raise ValueError(f"bits must be positive, got {bits}")

    key = 0
    for bit in range(bits):
        for dim, value in enumerate(values):
            bit_value = (value >> bit) & 1
            key |= bit_value << (bit * len(values) + dim)
    return key


@dataclass
class ZOrderClusterer:
    bits: int = 32

    def cluster_table(self, table: pa.Table, cluster_columns: list[str]) -> pa.Table:
        if not cluster_columns:
            raise ValueError("cluster_columns cannot be empty")

        missing = [col for col in cluster_columns if col not in table.column_names]
        if missing:
            raise ValueError(f"Cluster columns not found in table: {missing}")

        keys: list[int] = []
        for row_idx in range(table.num_rows):
            row_values: list[int] = []
            for col in cluster_columns:
                scalar = table[col][row_idx]
                if not scalar.is_valid:
                    row_values.append(0)
                    continue
                as_py = scalar.as_py()
                if isinstance(as_py, bool):
                    row_values.append(int(as_py))
                elif isinstance(as_py, int):
                    row_values.append(as_py)
                else:
                    raise TypeError(
                        f"Z-order currently supports integer/boolean columns only. "
                        f"Column '{col}' had value type {type(as_py).__name__}."
                    )
            keys.append(z_order_key(row_values, bits=self.bits))

        keyed = table.append_column(_Z_ORDER_KEY_COLUMN, pa.array(keys, type=pa.uint64()))
        indices = pc.sort_indices(keyed, sort_keys=[(_Z_ORDER_KEY_COLUMN, "ascending")])
        return keyed.take(indices).drop([_Z_ORDER_KEY_COLUMN])


def hilbert_index_2d(x: int, y: int, bits: int = 16) -> int:
    if bits <= 0:
        raise ValueError(f"bits must be positive, got {bits}")
    n = 1 << bits
    if x < 0 or y < 0 or x >= n or y >= n:
        raise ValueError(f"x and y must be in [0, {n}) for bits={bits}")

    def _rot(size: int, x0: int, y0: int, rx: int, ry: int) -> tuple[int, int]:
        if ry == 0:
            if rx == 1:
                x0 = size - 1 - x0
                y0 = size - 1 - y0
            x0, y0 = y0, x0
        return x0, y0

    d = 0
    s = n // 2
    xx, yy = x, y
    while s > 0:
        rx = 1 if (xx & s) else 0
        ry = 1 if (yy & s) else 0
        d += s * s * ((3 * rx) ^ ry)
        xx, yy = _rot(s, xx, yy, rx, ry)
        s //= 2
    return d


@dataclass
class HilbertClusterer:
    bits: int = 16

    def cluster_table(self, table: pa.Table, cluster_columns: list[str]) -> pa.Table:
        if len(cluster_columns) != 2:
            raise ValueError("Hilbert clustering currently requires exactly 2 cluster columns")

        missing = [col for col in cluster_columns if col not in table.column_names]
        if missing:
            raise ValueError(f"Cluster columns not found in table: {missing}")

        n = 1 << self.bits
        keys: list[int] = []
        for row_idx in range(table.num_rows):
            coords: list[int] = []
            for col in cluster_columns:
                scalar = table[col][row_idx]
                if not scalar.is_valid:
                    coords.append(0)
                    continue
                value = scalar.as_py()
                if isinstance(value, bool):
                    coords.append(int(value))
                elif isinstance(value, int):
                    coords.append(max(0, min(value, n - 1)))
                else:
                    raise TypeError(
                        f"Hilbert clustering currently supports integer/boolean columns only. "
                        f"Column '{col}' had value type {type(value).__name__}."
                    )

            keys.append(hilbert_index_2d(coords[0], coords[1], bits=self.bits))

        keyed = table.append_column(_HILBERT_KEY_COLUMN, pa.array(keys, type=pa.uint64()))
        indices = pc.sort_indices(keyed, sort_keys=[(_HILBERT_KEY_COLUMN, "ascending")])
        return keyed.take(indices).drop([_HILBERT_KEY_COLUMN])
