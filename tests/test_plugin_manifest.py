from types import SimpleNamespace
from pathlib import Path

import tomli

from ironsbot.app.bootstrap import load_manifest_plugins, run_runtime_setups
from ironsbot.app.plugin_manifest import (
    RUNTIME_SETUP_CALLS,
    iter_plugin_modules,
    validate_plugin_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_validates() -> None:
    validate_plugin_manifest()
    assert RUNTIME_SETUP_CALLS


def test_bootstrap_loads_manifest_order() -> None:
    loaded_modules: list[str] = []

    def load_plugin(module: str) -> object:
        loaded_modules.append(module)
        return object()

    assert load_manifest_plugins(load_plugin) == iter_plugin_modules()
    assert tuple(loaded_modules) == iter_plugin_modules()


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
        return SimpleNamespace(setup=lambda: called.append("setup"))

    assert run_runtime_setups(
        ("example.runtime:setup",),
        module_importer=import_module,
    ) == ("example.runtime:setup",)
    assert called == ["setup"]
