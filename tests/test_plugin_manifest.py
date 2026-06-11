import ast
from pathlib import Path

import pytest

from ironsbot.app.plugin_manifest import (
    iter_plugin_modules,
    validate_plugin_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def _string_tuple(node: ast.expr) -> tuple[str, ...]:
    if not isinstance(node, ast.Tuple):
        pytest.fail("bot.py plugin constants must remain tuple literals")

    modules: list[str] = []
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            pytest.fail("bot.py plugin constants must contain only string literals")
        modules.append(item.value)
    return tuple(modules)


def _bot_tuple(name: str) -> tuple[str, ...]:
    tree = ast.parse((ROOT / "bot.py").read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            continue
        return _string_tuple(node.value)
    pytest.fail(f"{name} not found in bot.py")


def test_plugin_manifest_validates() -> None:
    validate_plugin_manifest()


def test_plugin_manifest_mirrors_bot_load_order() -> None:
    expected = (
        *_bot_tuple("EXTERNAL_PLUGINS"),
        *_bot_tuple("CUSTOM_CORE_PLUGINS"),
        *_bot_tuple("INFRASTRUCTURE_PLUGINS"),
        *_bot_tuple("CUSTOM_PLUGINS"),
    )

    assert iter_plugin_modules() == expected
