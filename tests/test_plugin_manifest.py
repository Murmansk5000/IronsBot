from pathlib import Path

import tomli

from ironsbot.app.bootstrap import load_manifest_plugins, run_runtime_setups
from ironsbot.app.feature_modules import iter_feature_module_prefixes
from ironsbot.app.plugin_manifest import (
    RUNTIME_SETUP_CALLS,
    iter_plugin_modules,
    validate_plugin_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


class RuntimeModule:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def setup(self) -> None:
        self._calls.append("setup")


def test_plugin_manifest_validates() -> None:
    validate_plugin_manifest()
    assert RUNTIME_SETUP_CALLS


def test_manifest_covers_feature_visibility_modules() -> None:
    modules = iter_plugin_modules()

    for module_prefix in iter_feature_module_prefixes():
        assert any(
            loaded_module == module_prefix
            or loaded_module.startswith(f"{module_prefix}.")
            or module_prefix.startswith(f"{loaded_module}.")
            for loaded_module in modules
        ), module_prefix


def test_bootstrap_loads_manifest_order() -> None:
    loaded_modules: list[str] = []

    def load_plugin(module: str) -> object:
        loaded_modules.append(module)
        return object()

    assert load_manifest_plugins(load_plugin) == iter_plugin_modules()
    assert tuple(loaded_modules) == iter_plugin_modules()


def test_manifest_loads_foundation_plugins_before_dependents() -> None:
    modules = iter_plugin_modules()

    assert modules.index("ironsbot.plugins.db_sync") < modules.index(
        "ironsbot.plugins.seer_data"
    )
    assert modules.index("ironsbot.plugins.http_client") < modules.index(
        "ironsbot.plugins.seer_data"
    )
    assert modules.index("ironsbot.plugins.seer_data") < modules.index(
        "ironsbot.plugins.activity"
    )


def test_pyproject_does_not_define_plugin_loading_lists() -> None:
    pyproject = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    nonebot_config = pyproject["tool"]["nonebot"]

    assert nonebot_config.get("plugin_dirs") == []
    assert nonebot_config.get("builtin_plugins") == []
    assert "plugins" not in nonebot_config


def test_runtime_setups_run_manifest_refs() -> None:
    called: list[str] = []

    def import_module(module_name: str) -> object:
        assert module_name == "example.runtime"
        return RuntimeModule(called)

    assert run_runtime_setups(
        ("example.runtime:setup",),
        module_importer=import_module,
    ) == ("example.runtime:setup",)
    assert called == ["setup"]
