from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from benchbox.platforms.clickhouse import _dependencies as dependencies

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_import_chdb_restores_cwd_when_native_load_fails(tmp_path):

    original_cwd = os.getcwd()
    package_dir = tmp_path / "site-packages" / "chdb"
    package_dir.mkdir(parents=True)

    def failing_import(module_name: str):
        assert module_name == "chdb"
        os.chdir(package_dir)
        raise ImportError("mis-aligned LINKEDIT string pool")

    with patch.object(dependencies.importlib, "import_module", side_effect=failing_import):
        with pytest.raises(ImportError, match="mis-aligned LINKEDIT"):
            dependencies.import_chdb()

    assert os.getcwd() == original_cwd
