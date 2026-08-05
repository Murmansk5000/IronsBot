from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ironsbot"
CORE = PACKAGE / "core"
SERVICES = PACKAGE / "services"
RENDERING = SERVICES / "seer" / "rendering"
RUNTIME = PACKAGE / "runtime"
APPLICATION_RESOURCES = PACKAGE / "app" / "resources.py"
COMMAND_CATALOG = CORE / "command_catalog.py"
SEER_REQUEST_ACTOR_METHODS = {
    "player_request_protection.py": {
        "PlayerRequestProtectionService": ("run",),
    },
    "rank_admin.py": {
        "RankAdminService": ("cache_batch", "page_refresh", "cache_refresh"),
    },
    "rank_page_refresh.py": {
        "RankPageRefreshService": ("refresh",),
    },
    "local_rank.py": {
        "LocalRankService": ("refresh",),
    },
    "rank_queries.py": {
        "RankQueryService": ("list", "score", "player"),
    },
}
SEER_REQUEST_CONVERSATION_METHODS = {
    "player_service.py": {
        "PlayerDetailService": ("start_background_refresh",),
        "PlayerService": (
            "query",
            "bind_player",
            "start_background_refresh",
            "shortcut",
        ),
    },
    "rank_queries.py": {
        "RankQueryService": ("list", "score", "player"),
    },
}
AI_REQUEST_IDENTITY_METHODS = {
    "ai/service.py": {
        "AiService": ("chat_reply", "classify_intent"),
    },
}
BILIBILI_REQUEST_IDENTITY_METHODS = {
    "bilibili/service.py": {
        "BilibiliService": ("query_dynamic_menu",),
    },
    "bilibili/targets.py": {
        "BiliTargetService": ("query_uids",),
    },
}
BILIBILI_LEGACY_DELIVERY_IMPORTS = ("ironsbot.core.messaging",)
LEGACY_FEATURE_POLICY_METHODS = frozenset(
    {
        "group_has_feature",
        "is_group_feature_allowed",
        "is_private_feature_allowed",
        "user_has_feature",
        "users_for_feature",
        "groups_for_feature",
        "users_with_superusers",
        "is_conversation_blocked",
    }
)

TRANSITIONAL_RENDERER_PERSISTENCE_MODULES = frozenset()
FORBIDDEN_TRANSPORT_IMPORT_PREFIXES = (
    "nonebot",
    "onebot",
)
FORBIDDEN_RENDERER_PERSISTENCE_PREFIXES = (
    "sqlalchemy",
    "sqlmodel",
    "sqlite3",
)
RETIRED_RUNTIME_NAMES = (
    "PluginDefinition",
    "MatcherRegistry",
)


class MissingArchitectureTargetMethodError(AssertionError):
    def __init__(
        self,
        *,
        class_name: str,
        method_name: str,
        path: Path,
    ) -> None:
        super().__init__(
            f"missing method {class_name}.{method_name} in {path.relative_to(ROOT)}"
        )


class MissingArchitectureTargetClassError(AssertionError):
    def __init__(self, *, class_name: str, path: Path) -> None:
        super().__init__(f"missing class {class_name} in {path.relative_to(ROOT)}")


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


def _method_argument_names(
    path: Path,
    *,
    class_name: str,
    method_name: str,
) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for method in node.body:
            if isinstance(method, (ast.AsyncFunctionDef, ast.FunctionDef)) and (
                method.name == method_name
            ):
                return {
                    argument.arg
                    for argument in (
                        *method.args.posonlyargs,
                        *method.args.args,
                        *method.args.kwonlyargs,
                    )
                }
    raise MissingArchitectureTargetMethodError(
        class_name=class_name,
        method_name=method_name,
        path=path,
    )


def _class_field_names(path: Path, *, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        return {
            statement.target.id
            for statement in node.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        }
    raise MissingArchitectureTargetClassError(class_name=class_name, path=path)


def _class_method_names(path: Path, *, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        return {
            method.name
            for method in node.body
            if isinstance(method, (ast.AsyncFunctionDef, ast.FunctionDef))
        }
    raise MissingArchitectureTargetClassError(class_name=class_name, path=path)


def _legacy_feature_policy_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in LEGACY_FEATURE_POLICY_METHODS
    }


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


def test_seer_request_services_use_actor_refs_not_onebot_user_ids() -> None:
    for filename, classes in SEER_REQUEST_ACTOR_METHODS.items():
        path = SERVICES / "seer" / filename
        for class_name, method_names in classes.items():
            for method_name in method_names:
                arguments = _method_argument_names(
                    path,
                    class_name=class_name,
                    method_name=method_name,
                )
                assert "actor" in arguments
                assert "user_id" not in arguments


def test_seer_request_services_use_conversation_refs_not_group_ids() -> None:
    for filename, classes in SEER_REQUEST_CONVERSATION_METHODS.items():
        path = SERVICES / "seer" / filename
        for class_name, method_names in classes.items():
            for method_name in method_names:
                arguments = _method_argument_names(
                    path,
                    class_name=class_name,
                    method_name=method_name,
                )
                assert "conversation" in arguments
                assert "group_id" not in arguments


def test_ai_request_services_use_platform_identity_refs() -> None:
    for relative_filename, classes in AI_REQUEST_IDENTITY_METHODS.items():
        path = SERVICES / relative_filename
        for class_name, method_names in classes.items():
            for method_name in method_names:
                arguments = _method_argument_names(
                    path,
                    class_name=class_name,
                    method_name=method_name,
                )
                assert "actor" in arguments
                assert "conversation" in arguments
                assert "user_id" not in arguments
                assert "group_id" not in arguments


def test_bilibili_query_services_use_platform_identity_refs() -> None:
    for relative_filename, classes in BILIBILI_REQUEST_IDENTITY_METHODS.items():
        path = SERVICES / relative_filename
        for class_name, method_names in classes.items():
            for method_name in method_names:
                arguments = _method_argument_names(
                    path,
                    class_name=class_name,
                    method_name=method_name,
                )
                assert "actor" in arguments
                assert "conversation" in arguments
                assert "user_id" not in arguments
                assert "group_id" not in arguments


def test_bilibili_services_do_not_own_legacy_delivery_types() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()} imports {module}"
        for path in _python_files(SERVICES / "bilibili")
        for module in _imports(path)
        if module.startswith(BILIBILI_LEGACY_DELIVERY_IMPORTS)
    ]

    assert offenders == []


def test_command_catalog_context_and_policy_stay_platform_neutral() -> None:
    path = COMMAND_CATALOG
    context_fields = _class_field_names(path, class_name="CommandContext")
    policy_methods = _class_method_names(path, class_name="CommandFeaturePolicy")

    assert {"actor", "conversation"} <= context_fields
    assert {"user_id", "group_id"}.isdisjoint(context_fields)
    assert {
        "is_actor_superuser",
        "conversation_has_feature",
        "is_feature_allowed",
    } <= policy_methods
    assert {
        "is_superuser",
        "group_has_feature",
        "is_group_feature_allowed",
        "is_private_feature_allowed",
    }.isdisjoint(policy_methods)


def test_inbound_blacklist_policy_uses_typed_identity_refs() -> None:
    methods = _class_method_names(
        CORE / "feature_policy.py",
        class_name="FeatureService",
    )

    assert "is_message_blocked" in methods
    assert "is_conversation_blocked" not in methods


def test_runtime_callers_do_not_use_legacy_numeric_feature_policy() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}: {method}"
        for directory in (
            PACKAGE / "app",
            PACKAGE / "integrations",
            PACKAGE / "plugins",
            RUNTIME,
        )
        for path in _python_files(directory)
        for method in sorted(_legacy_feature_policy_calls(path))
    ]

    assert offenders == []


def test_runtime_does_not_reintroduce_retired_plugin_or_matcher_registries() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()} mentions {retired_name}"
        for path in _python_files(PACKAGE)
        for retired_name in RETIRED_RUNTIME_NAMES
        if retired_name in path.read_text(encoding="utf-8-sig")
    ]

    assert offenders == []


def test_plugin_resources_do_not_expose_legacy_onebot_delivery() -> None:
    fields = _class_field_names(
        APPLICATION_RESOURCES,
        class_name="ApplicationResources",
    )

    assert {"delivery", "outbound", "push_message_limiter"}.isdisjoint(fields)


def test_runtime_does_not_reintroduce_command_contract_modules() -> None:
    assert not (RUNTIME / "commands.py").exists()
    assert not (RUNTIME / "player_reference_commands.py").exists()
