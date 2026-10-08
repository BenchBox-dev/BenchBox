from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    "VisualizationDependencyError": "exceptions",
    "VisualizationError": "exceptions",
    "export_ascii": "exporters",
    "render_ascii_chart": "exporters",
    "PostRunSummary": "post_run_summary",
    "generate_post_run_summary": "post_run_summary",
    "NormalizedQuery": "result_plotter",
    "NormalizedResult": "result_plotter",
    "ResultPlotter": "result_plotter",
    "ChartTemplate": "templates",
    "get_template": "templates",
    "list_templates": "templates",
    "slugify": "utils",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is not None:
        module = importlib.import_module(f"{__name__}.{module_name}")
        value = getattr(module, name)
        globals()[name] = value
        return value

    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    globals()[name] = module
    return module


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
