"""Retired foundation owners after the completed architecture migration."""
import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ironsbot"
RETIRED_FOUNDATION_MODULES = (
    "ironsbot.integrations.seer_data.db",
    "ironsbot.plugins.db_sync.config",
    "ironsbot.plugins.db_sync.formatting",
    "ironsbot.plugins.db_sync.github_actions",
    "ironsbot.plugins.db_sync.manager",
    "ironsbot.plugins.db_sync.remote_build",
    "ironsbot.plugins.db_sync.service",
    "ironsbot.plugins.db_sync.storage",
    "ironsbot.plugins.headless_seer.as3bytearray",
    "ironsbot.plugins.headless_seer.client",
    "ironsbot.plugins.headless_seer.command_id",
    "ironsbot.plugins.headless_seer.config",
    "ironsbot.plugins.headless_seer.core",
    "ironsbot.plugins.headless_seer.decrypt",
    "ironsbot.plugins.headless_seer.exception",
    "ironsbot.plugins.headless_seer.game",
    "ironsbot.plugins.headless_seer.manager",
    "ironsbot.plugins.headless_seer.packet",
    "ironsbot.plugins.headless_seer.packets",
    "ironsbot.plugins.headless_seer.type_hint",
    "ironsbot.plugins.headless_seer.utils",
    "ironsbot.plugins.seer.query.commands.upstream_queries",
    "ironsbot.plugins.seer_data.config",
    "ironsbot.plugins.seer_data.db",
    "ironsbot.plugins.seer_data.image",
    "ironsbot.plugins.seer_data.orm",
    "ironsbot.services.seer.client",
    "ironsbot.services.seer.rank_service",
)


def _resolved_imports(path: Path) -> set[str]:
    parts = path.relative_to(ROOT).with_suffix("").parts
    package = ".".join(parts[:-1])
    modules: set[str] = set()
    for node in ast.walk(
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)),
    ):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = (
                resolve_name("." * node.level + (node.module or ""), package)
                if node.level
                else node.module
            )
            if module:
                modules.add(module)
                modules.update(
                    f"{module}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
    return modules


def test_retired_foundation_sources_do_not_return() -> None:
    assert [
        path.relative_to(ROOT).as_posix()
        for module in RETIRED_FOUNDATION_MODULES
        for path in (
            ROOT.joinpath(*module.split(".")).with_suffix(".py"),
            ROOT.joinpath(*module.split("."), "__init__.py"),
        )
        if path.exists()
    ] == []


def test_production_does_not_import_retired_foundation_owners() -> None:
    assert [
        f"{path.relative_to(ROOT).as_posix()} imports {module}"
        for path in sorted(PACKAGE.rglob("*.py"))
        for module in _resolved_imports(path)
        if any(
            module == retired or module.startswith(f"{retired}.")
            for retired in RETIRED_FOUNDATION_MODULES
        )
    ] == []
