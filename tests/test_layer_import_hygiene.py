import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "ironsbot"
PLUGIN_ROOT = PACKAGE_ROOT / "plugins"
LAYER_ROOTS = (
    ROOT / "ironsbot" / "config",
    ROOT / "ironsbot" / "integrations",
    ROOT / "ironsbot" / "services",
    ROOT / "ironsbot" / "shared",
)


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _parse_python(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _imported_modules(path: Path) -> set[str]:
    tree = _parse_python(path)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _plugin_import_offenders() -> list[str]:
    return [
        f"{path.relative_to(ROOT).as_posix()} imports {module_name}"
        for root in LAYER_ROOTS
        for path in root.rglob("*.py")
        for module_name in _imported_modules(path)
        if module_name == "ironsbot.plugins"
        or module_name.startswith("ironsbot.plugins.")
    ]


def test_lower_layers_do_not_import_plugins() -> None:
    assert _plugin_import_offenders() == []


def _plugin_absolute_import_offenders() -> list[str]:
    return [
        f"{path.relative_to(ROOT).as_posix()} imports {module_name}"
        for path in PLUGIN_ROOT.rglob("*.py")
        for module_name in _imported_modules(path)
        if module_name == "ironsbot.plugins"
        or module_name.startswith("ironsbot.plugins.")
    ]


def test_plugins_do_not_absolute_import_other_plugins() -> None:
    assert _plugin_absolute_import_offenders() == []


def _star_import_offenders() -> list[str]:
    offenders: list[str] = []
    for path in _python_files(PACKAGE_ROOT):
        tree = _parse_python(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "*" for alias in node.names
            ):
                module_name = node.module or "."
                offenders.append(
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno} "
                    f"imports * from {module_name}"
                )
    return offenders


def test_production_code_does_not_use_star_imports() -> None:
    assert _star_import_offenders() == []


def _forbidden_module_import_offenders(forbidden_modules: set[str]) -> list[str]:
    return [
        f"{path.relative_to(ROOT).as_posix()} imports {module_name}"
        for path in _python_files(PACKAGE_ROOT)
        for module_name in _imported_modules(path)
        if module_name in forbidden_modules
    ]


def test_production_code_uses_current_foundation_modules() -> None:
    assert _forbidden_module_import_offenders(
        {
            "ironsbot.services.seer.client",
        }
    ) == []
