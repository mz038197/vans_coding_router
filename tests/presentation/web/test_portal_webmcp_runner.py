import shutil
import subprocess
from pathlib import Path

import pytest


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is required for browser contract tests")
def test_portal_webmcp_browser_contracts():
    test_file = Path(__file__).with_name("test_portal_webmcp.mjs")
    completed = subprocess.run(
        [NODE, "--test", str(test_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
