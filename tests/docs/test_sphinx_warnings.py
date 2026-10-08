import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.stress,
]


def test_sphinx_build_specific_warning_types():
    docs_dir = Path(__file__).parent.parent.parent / "docs"

    tmpdir = tempfile.mkdtemp()
    try:
        build_dir = Path(tmpdir) / "_build/html"

        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "sphinx",
                "-b",
                "html",
                str(docs_dir),
                str(build_dir),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        output = result.stderr + result.stdout

        problematic_patterns = {
            "autodoc import failures": "failed to import",
            "nonexisting documents": "toctree contains reference to nonexisting document",
            "unknown documents": "unknown document:",
            "broken references": "undefined label:",
        }

        errors = []
        for name, pattern in problematic_patterns.items():
            count = output.lower().count(pattern.lower())
            if count > 0:
                errors.append(f"{name}: {count} occurrences of '{pattern}'")

        orphan_pattern = "document isn't included in any toctree"
        orphan_lines = [line for line in output.split("\n") if orphan_pattern.lower() in line.lower()]
        unexpected_orphans = [line for line in orphan_lines if "_tags/" not in line and "blog/index" not in line]
        if unexpected_orphans:
            errors.append(
                f"orphaned documents: {len(unexpected_orphans)} unexpected orphaned pages:\n"
                + "\n".join(f"  - {line}" for line in unexpected_orphans)
            )

        if errors:
            pytest.fail("Found problematic warnings:\n" + "\n".join(errors))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_sphinx_build_specific_warning_types()
    print("All Sphinx warning tests passed!")
