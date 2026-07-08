import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYER_ROOTS = (
    ROOT / "ironsbot" / "config",
    ROOT / "ironsbot" / "integrations",
    ROOT / "ironsbot" / "services",
    ROOT / "ironsbot" / "shared",
)


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_non_plugin_layers_do_not_import_plugins() -> None:
    offenders: list[str] = []
    for root in LAYER_ROOTS:
        for path in root.rglob("*.py"):
            offenders.extend(
                f"{path.relative_to(ROOT).as_posix()} imports {module}"
                for module in _imported_modules(path)
                if module == "ironsbot.plugins"
                or module.startswith("ironsbot.plugins.")
            )

    assert offenders == []
