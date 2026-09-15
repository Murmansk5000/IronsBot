from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ironsbot"
TRANSPORT_ROOTS = (
    PACKAGE / "integrations" / "onebot",
    PACKAGE / "integrations" / "qq_official",
    PACKAGE / "plugins" / "onebot",
)
BUSINESS_ROOTS = (PACKAGE / "services", PACKAGE / "extensions")
LOGGER_METHODS = frozenset({"debug", "info", "warning", "error", "exception"})
TRANSPORT_REFERENCE_NAMES = frozenset(
    {
        "actor",
        "conversation",
        "event_session_id",
        "group_id",
        "message_id",
        "sender_id",
        "self_id",
        "user_id",
    }
)
BUSINESS_REFERENCE_NAMES = frozenset({"actor", "conversation"})


def _logger_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logger"
        and node.func.attr in LOGGER_METHODS
    ]


def _is_direct_reference(node: ast.AST, names: frozenset[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute):
        return node.attr in names or (
            node.attr == "id"
            and isinstance(node.value, ast.Name)
            and node.value.id in names
        )
    if isinstance(node, ast.FormattedValue):
        return _is_direct_reference(node.value, names)
    if isinstance(node, ast.JoinedStr):
        return any(_is_direct_reference(value, names) for value in node.values)
    return False


def _violations(root: Path, names: frozenset[str]) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        violations.extend(
            f"{path.relative_to(ROOT)}:{call.lineno}"
            for call in _logger_calls(path)
            if any(_is_direct_reference(argument, names) for argument in call.args)
        )
    return violations


def test_transport_ids_are_not_logged_directly() -> None:
    violations = [
        *(
            violation
            for root in TRANSPORT_ROOTS
            for violation in _violations(root, TRANSPORT_REFERENCE_NAMES)
        ),
        *(
            violation
            for root in BUSINESS_ROOTS
            for violation in _violations(root, BUSINESS_REFERENCE_NAMES)
        ),
    ]

    assert violations == []
