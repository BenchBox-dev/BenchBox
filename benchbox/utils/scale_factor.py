# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.


def format_scale_factor(scale_factor: float) -> str:
    if scale_factor >= 1:
        if scale_factor == int(scale_factor):
            return f"sf{int(scale_factor)}"
        else:
            str_val = f"{scale_factor}".replace(".", "")
            return f"sf{str_val}"
    else:
        decimal_str = f"{scale_factor:.10f}".rstrip("0")
        if "." in decimal_str:
            after_decimal = decimal_str.split(".")[1]
            return f"sf0{after_decimal}"
        else:
            return "sf0"


def format_benchmark_name(benchmark_name: str, scale_factor: float) -> str:
    sf_str = format_scale_factor(scale_factor)
    return f"{benchmark_name}_{sf_str}"


def format_data_directory(benchmark_name: str, scale_factor: float) -> str:
    sf_str = format_scale_factor(scale_factor)
    return f"{benchmark_name}_{sf_str}_data"


def format_schema_name(benchmark_name: str, scale_factor: float) -> str:
    sf_str = format_scale_factor(scale_factor)
    return f"{benchmark_name}_{sf_str}"
