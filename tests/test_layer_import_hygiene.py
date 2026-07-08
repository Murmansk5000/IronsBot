import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYER_ROOTS = (
    ROOT / "ironsbot" / "config",
    ROOT / "ironsbot" / "integrations",
    ROOT / "ironsbot" / "services",
    ROOT / "ironsbot" / "shared",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
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
