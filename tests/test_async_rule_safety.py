from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ironsbot"


def _hidden_async_rule_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    async_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }
    hidden: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Rule"
            and node.args
            and isinstance(node.args[0], ast.Lambda)
        ):
            continue
        called = {
            call.func.id
            for call in ast.walk(node.args[0].body)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
        hidden.extend(
            f"{path.relative_to(ROOT.parent)}:{node.lineno}: {name}"
            for name in sorted(called & async_names)
        )
    return hidden


def test_rule_lambdas_do_not_hide_module_async_predicates() -> None:
    hidden = [
        item
        for path in ROOT.rglob("*.py")
        for item in _hidden_async_rule_calls(path)
    ]

    assert hidden == []
