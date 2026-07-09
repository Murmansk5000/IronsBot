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
PLUGIN_OWNER_PARTS = 3
SCHEDULER_JOB_METHODS = {"add_job", "get_jobs", "remove_job"}
SQLITE_HELPER_PATH = PACKAGE_ROOT / "shared" / "sqlite.py"
RUNTIME_JOBS_PATH = PACKAGE_ROOT / "shared" / "runtime" / "jobs.py"


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _parse_python(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _module_name_for_path(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_name_for_path(path: Path) -> str:
    module_name = _module_name_for_path(path)
    if path.name == "__init__.py":
        return module_name
    return module_name.rsplit(".", 1)[0]


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module

    package_parts = _package_name_for_path(path).split(".")
    if node.level > len(package_parts):
        return None

    base_parts = package_parts[: len(package_parts) - node.level + 1]
    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(base_parts)


def _imported_modules(path: Path) -> set[str]:
    tree = _parse_python(path)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module_name = _resolve_import_from(path, node)
            if module_name is None:
                continue
            modules.add(module_name)
            modules.update(
                f"{module_name}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            )
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


def _plugin_reference_offenders() -> list[str]:
    return [
        path.relative_to(ROOT).as_posix()
        for root in LAYER_ROOTS
        for path in root.rglob("*.py")
        if "ironsbot.plugins" in path.read_text(encoding="utf-8-sig")
    ]


def test_lower_layers_do_not_reference_plugin_modules() -> None:
    assert _plugin_reference_offenders() == []


def _plugin_owner(path: Path) -> str:
    relative_parts = path.relative_to(PLUGIN_ROOT).parts
    return f"ironsbot.plugins.{relative_parts[0]}"


def _imported_plugin_owner(module_name: str) -> str | None:
    parts = module_name.split(".")
    if parts[:2] != ["ironsbot", "plugins"]:
        return None
    if len(parts) < PLUGIN_OWNER_PARTS:
        return "ironsbot.plugins"
    return ".".join(parts[:PLUGIN_OWNER_PARTS])


def _plugin_cross_import_offenders() -> list[str]:
    offenders: list[str] = []
    for path in PLUGIN_ROOT.rglob("*.py"):
        owner = _plugin_owner(path)
        for module_name in _imported_modules(path):
            imported_owner = _imported_plugin_owner(module_name)
            if imported_owner is not None and imported_owner != owner:
                offenders.append(
                    f"{path.relative_to(ROOT).as_posix()} imports {module_name}"
                )
    return offenders


def test_plugins_do_not_import_other_plugins() -> None:
    assert _plugin_cross_import_offenders() == []


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
            "ironsbot.integrations.seer_data.db",
            "ironsbot.plugins.db_sync.manager",
            "ironsbot.services.seer.local_rank",
            "ironsbot.services.seer.rank_service",
            "ironsbot.services.seer.client",
        }
    ) == []


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _sqlite_connect_offenders() -> list[str]:
    offenders: list[str] = []
    for path in _python_files(PACKAGE_ROOT):
        if path == SQLITE_HELPER_PATH:
            continue
        tree = _parse_python(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "connect"
                and isinstance(func.value, ast.Name)
                and func.value.id == "sqlite3"
            ):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    return offenders


def test_sqlite_connections_go_through_shared_helper() -> None:
    assert _sqlite_connect_offenders() == []


def _direct_scheduler_job_call_offenders() -> list[str]:
    offenders: list[str] = []
    for path in _python_files(PACKAGE_ROOT):
        if path == RUNTIME_JOBS_PATH:
            continue
        tree = _parse_python(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = _call_name(node)
            if call_name in SCHEDULER_JOB_METHODS:
                offenders.append(
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno} calls "
                    f"{call_name}"
                )
    return offenders


def test_scheduler_job_changes_go_through_runtime_jobs() -> None:
    assert _direct_scheduler_job_call_offenders() == []
