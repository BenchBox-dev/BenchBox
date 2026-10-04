from pathlib import Path

import pytest

from benchbox.core.tpcds_obt.query_conversion import TEMPLATE_DIR, TemplateLoader
from benchbox.utils.tpc_compilation import get_tpc_templates_dir

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_template_dir_matches_shared_tpcds_resolver() -> None:
    assert get_tpc_templates_dir("tpc-ds") / "query_templates" == TEMPLATE_DIR
    assert TEMPLATE_DIR.exists()
    assert (TEMPLATE_DIR / "query3.tpl").exists()


def test_template_loader_without_sources_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    real_exists = Path.exists

    def _exists(self: Path) -> bool:
        if "_sources" in str(self):
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", _exists)
    loader = TemplateLoader(3)
    assert loader.template_dir == TEMPLATE_DIR
    assert loader.body_sql
