from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ironsbot"
CORE = PACKAGE / "core"
SERVICES = PACKAGE / "services"
RENDERING = SERVICES / "seer" / "rendering"

# Phase 4 removes these lookup modules by passing prepared view models into
# renderers. This register prevents the known debt from spreading beforehand.
TRANSITIONAL_RENDERER_PERSISTENCE_MODULES = frozenset(
    {
        "custom_pet_info.py",
        "custom_pet_soulmark_icons.py",
        "custom_pet_special_effects.py",
    }
)
FORBIDDEN_TRANSPORT_IMPORT_PREFIXES = (
    "nonebot",
    "onebot",
)
FORBIDDEN_RENDERER_PERSISTENCE_PREFIXES = (
    "sqlalchemy",
    "sqlmodel",
    "sqlite3",
)


def _module(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _package(path: Path) -> str:
    module = _module(path)
    return module if path.name == "__init__.py" else module.rsplit(".", 1)[0]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative = "." * node.level + (node.module or "")
                modules.add(resolve_name(relative, _package(path)))
            elif node.module:
                modules.add(node.module)
    return modules


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def test_core_and_services_do_not_import_adapter_transport_types() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()} imports {module}"
        for directory in (CORE, SERVICES)
        for path in _python_files(directory)
        for module in _imports(path)
        if module.startswith(FORBIDDEN_TRANSPORT_IMPORT_PREFIXES)
    ]

    assert offenders == []


def test_renderer_persistence_debt_cannot_spread_before_phase_four() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()} imports {module}"
        for path in _python_files(RENDERING)
        for module in _imports(path)
        if module.startswith(FORBIDDEN_RENDERER_PERSISTENCE_PREFIXES)
        and path.name not in TRANSITIONAL_RENDERER_PERSISTENCE_MODULES
    ]

    assert offenders == []


def test_renderer_transition_allowlist_is_exact_and_documented() -> None:
    current = {
        path.name
        for path in _python_files(RENDERING)
        if any(
            module.startswith(FORBIDDEN_RENDERER_PERSISTENCE_PREFIXES)
            for module in _imports(path)
        )
    }

    assert current == TRANSITIONAL_RENDERER_PERSISTENCE_MODULES
