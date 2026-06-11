from types import SimpleNamespace

from ironsbot.app.bootstrap import load_manifest_plugins, run_runtime_setups
from ironsbot.app.plugin_manifest import (
    RUNTIME_SETUP_CALLS,
    iter_plugin_modules,
    validate_plugin_manifest,
)


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
