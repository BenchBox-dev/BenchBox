"""ASCII chart visualizations for terminal display.

Compatibility shim - all chart implementations live in the ``textcharts``
standalone library. This package re-exports them under the original
``benchbox.core.visualization.ascii`` import paths.
"""

from textcharts import *  # noqa: F401, F403
from textcharts import __all__ as _textcharts_all

# Re-export the textcharts __all__ so `from benchbox.core.visualization.ascii import *` works
__all__ = list(_textcharts_all)
