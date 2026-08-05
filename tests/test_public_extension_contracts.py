from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "ironsbot" / "extensions" / "contracts.py"


def test_public_extension_contracts_do_not_depend_on_application_or_plugins() -> None:
    tree = ast.parse(CONTRACTS.read_text(encoding="utf-8"), filename=str(CONTRACTS))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not {
        module
        for module in imports
        if module.startswith(("ironsbot.app", "ironsbot.plugins"))
    }
