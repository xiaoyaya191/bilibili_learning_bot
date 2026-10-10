import shutil
import subprocess
from pathlib import Path
import pytest


def test_permission_ui_delayed_load_and_save_verification():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required for permission UI regression")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([node, str(root / "tests/permission_ui_regression.cjs"),
                    str(root / "assets/js/action-permissions.js")], check=True, timeout=20)
