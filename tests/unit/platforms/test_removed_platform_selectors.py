"""Migration errors for platform selectors removed from BenchBox."""

import pytest

from benchbox.platforms.adapter_factory import get_adapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.parametrize("selector", ["modin", "modin-df"])
def test_removed_modin_selectors_name_supported_replacements(selector: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        get_adapter(selector)

    message = str(exc_info.value)
    assert "removed" in message
    assert "pandas-df" in message
    assert "dask-df" in message
