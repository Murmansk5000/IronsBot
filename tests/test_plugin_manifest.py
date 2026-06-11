from ironsbot.app.bootstrap import load_manifest_plugins
from ironsbot.app.plugin_manifest import (
    iter_plugin_modules,
    validate_plugin_manifest,
)


def test_plugin_manifest_validates() -> None:
    validate_plugin_manifest()


def test_bootstrap_loads_manifest_order() -> None:
    loaded_modules: list[str] = []

    def load_plugin(module: str) -> object:
        loaded_modules.append(module)
        return object()

    assert load_manifest_plugins(load_plugin) == iter_plugin_modules()
    assert tuple(loaded_modules) == iter_plugin_modules()
