import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ironsbot"
PLUGINS = PACKAGE / "plugins"
SERVICES = PACKAGE / "services"
SEER_RENDERING = SERVICES / "seer" / "rendering"
SERVICE_PACKAGES = frozenset(
    {
        "activity",
        "ai",
        "bilibili",
        "identity",
        "messaging",
        "operations",
        "seer",
        "team",
    }
)
FORBIDDEN_SERVICE_IMPORTS = (
    "httpx",
    "ironsbot.app",
    "ironsbot.plugins",
    "ironsbot.runtime",
    "nonebot",
)
ALLOWED_SERVICE_INTEGRATIONS = ("ironsbot.integrations.seer_data",)
ALLOWED_LAYER_IMPORTS = {
    "core": frozenset({"core"}),
    "config": frozenset({"config", "core"}),
    "runtime": frozenset({"core", "runtime"}),
}
ALLOWED_CROSS_LAYER_IMPORTS = {
    "config": frozenset({"ironsbot.services.identity.player_accounts"}),
}
LOWER_LAYERS = ("config", "integrations", "services")
DRIVER_HOOKS = {
    "on_startup",
    "on_shutdown",
    "on_bot_connect",
    "on_bot_disconnect",
}
LIFECYCLE_PATH = PACKAGE / "app" / "lifecycle.py"
SQLITE_PATH = PACKAGE / "integrations" / "storage" / "sqlite.py"
SCHEDULER_PATH = PACKAGE / "integrations" / "scheduler" / "facade.py"
SCHEDULER_PLUGIN_PATH = PACKAGE / "plugins" / "onebot" / "scheduler" / "__init__.py"
FORBIDDEN_RENDERER_IMPORTS = (
    "aiohttp",
    "httpx",
    "requests",
    "sqlalchemy",
    "sqlite3",
    "sqlmodel",
)
FORBIDDEN_RENDERER_CALLS = {
    "open",
    "read_bytes",
    "read_text",
    "write_bytes",
    "write_text",
}


def _files(root: Path = PACKAGE) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _module(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _package(path: Path) -> str:
    module = _module(path)
    return module if path.name == "__init__.py" else module.rsplit(".", 1)[0]


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative = "." * node.level + (node.module or "")
                modules.add(resolve_name(relative, _package(path)))
            elif node.module:
                modules.add(node.module)
    return modules


def _layer(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "ironsbot" else None


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _call_name(node: ast.Call) -> str | None:
    return (
        node.func.attr
        if isinstance(node.func, ast.Attribute)
        else node.func.id
        if isinstance(node.func, ast.Name)
        else None
    )


def _calls() -> list[tuple[Path, ast.Call]]:
    return [
        (path, node)
        for path in _files()
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call)
    ]


def test_layers_follow_dependency_direction() -> None:
    offenders = [
        f"{_relative(path)} imports {module}"
        for owner, allowed in ALLOWED_LAYER_IMPORTS.items()
        for path in _files(PACKAGE / owner)
        for module in _imports(path)
        if (layer := _layer(module)) is not None
        and layer not in allowed
        and module not in ALLOWED_CROSS_LAYER_IMPORTS.get(owner, ())
    ]
    assert offenders == []


def test_lower_layers_do_not_reference_plugins() -> None:
    offenders = [
        _relative(path)
        for layer in LOWER_LAYERS
        for path in _files(PACKAGE / layer)
        if "ironsbot.plugins" in path.read_text(encoding="utf-8-sig")
    ]
    assert offenders == []


def test_legacy_identity_migration_is_only_reachable_from_offline_tools() -> None:
    offline = {
        "ironsbot.state_migration",
        "ironsbot.state_migration_cli",
        "ironsbot.platform_state_migration",
        "ironsbot.integrations.storage.platform_state_schema",
    }
    offenders = [
        f"{_relative(path)} imports {module}"
        for path in _files()
        if _module(path) not in offline
        for module in _imports(path)
        if module in offline
    ]
    assert offenders == []


def test_services_do_not_import_framework_or_outer_layers() -> None:
    offenders = [
        f"{_relative(path)} imports {module}"
        for path in _files(SERVICES)
        for module in _imports(path)
        if module.startswith(FORBIDDEN_SERVICE_IMPORTS)
        or (
            module.startswith("ironsbot.integrations")
            and not module.startswith(ALLOWED_SERVICE_INTEGRATIONS)
        )
    ]
    assert offenders == []


def test_pure_seer_renderers_do_not_access_data_transport_or_files() -> None:
    """Keep renderer inputs as prepared documents instead of live dependencies."""
    import_offenders = [
        f"{_relative(path)} imports {module}"
        for path in _files(SEER_RENDERING)
        for module in _imports(path)
        if module.startswith(FORBIDDEN_RENDERER_IMPORTS)
    ]
    call_offenders = [
        f"{_relative(path)}:{node.lineno}"
        for path in _files(SEER_RENDERING)
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call) and _call_name(node) in FORBIDDEN_RENDERER_CALLS
    ]
    assert [*import_offenders, *call_offenders] == []


def test_core_does_not_import_the_nonebot_framework() -> None:
    offenders = [
        f"{_relative(path)} imports {module}"
        for path in _files(PACKAGE / "core")
        for module in _imports(path)
        if module.startswith("nonebot")
    ]
    assert offenders == []


def test_runtime_does_not_import_onebot_adapter_contracts() -> None:
    offenders = [
        f"{_relative(path)} imports {module}"
        for path in _files(PACKAGE / "runtime")
        for module in _imports(path)
        if module.startswith(
            ("nonebot.adapters.onebot", "ironsbot.integrations.onebot")
        )
    ]
    assert offenders == []


def test_plugins_do_not_import_other_plugins() -> None:
    offenders: list[str] = []
    for path in _files(PLUGINS):
        owner = path.relative_to(PLUGINS).parts[0]
        for module in _imports(path):
            parts = module.split(".")
            if parts[:2] == ["ironsbot", "plugins"] and parts[2:3] != [owner]:
                offenders.append(f"{_relative(path)} imports {module}")
    assert offenders == []


def test_plugins_only_import_matching_platform_integrations() -> None:
    offenders = [
        f"{_relative(path)} imports {module}"
        for path in _files(PLUGINS)
        for module in _imports(path)
        if module.startswith("ironsbot.integrations")
        and not (
            path.relative_to(PLUGINS).parts[:1] == ("onebot",)
            and module.startswith("ironsbot.integrations.onebot")
        )
    ]
    assert offenders == []


def test_services_use_target_packages() -> None:
    packages = {
        path.relative_to(SERVICES).parts[0]
        for path in _files(SERVICES)
        if path.parent != SERVICES
    }
    assert packages == SERVICE_PACKAGES


def test_plugins_do_not_require_internal_plugins() -> None:
    offenders = [
        f"{_relative(path)}:{node.lineno}"
        for path, node in _calls()
        if _call_name(node) == "require"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and node.args[0].value.startswith("ironsbot.plugins.")
    ]
    assert offenders == []


def test_production_has_no_star_imports_or_historical_modules() -> None:
    star_imports = [
        f"{_relative(path)}:{node.lineno}"
        for path in _files()
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ImportFrom)
        and any(alias.name == "*" for alias in node.names)
    ]
    historical = [
        _relative(path) for path in _files() if path.stem.startswith("upstream_")
    ]
    explicit_exports = [
        f"{_relative(path)}:{node.lineno}"
        for path in _files()
        for node in ast.walk(_tree(path))
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
    ]
    assert [*star_imports, *historical, *explicit_exports] == []


def test_only_lifecycle_registers_driver_hooks() -> None:
    offenders = [
        f"{_relative(path)}:{node.lineno}"
        for path, node in _calls()
        if path != LIFECYCLE_PATH and _call_name(node) in DRIVER_HOOKS
    ]
    assert offenders == []


def test_only_task_owner_creates_background_tasks() -> None:
    offenders = [
        f"{_relative(path)}:{node.lineno}"
        for path, node in _calls()
        if path != LIFECYCLE_PATH
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
        and node.func.attr == "create_task"
    ]
    assert offenders == []


def test_sqlite_connections_use_storage_database() -> None:
    offenders = [
        f"{_relative(path)}:{node.lineno}"
        for path, node in _calls()
        if path != SQLITE_PATH
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sqlite3"
    ]
    assert offenders == []


def test_scheduler_changes_use_scheduler_facade() -> None:
    offenders = [
        f"{_relative(path)} imports {module}"
        for path in _files()
        if path not in {SCHEDULER_PATH, SCHEDULER_PLUGIN_PATH}
        for module in _imports(path)
        if "apscheduler" in module
    ]
    assert offenders == []
