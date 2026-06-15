# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Any

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from ironsbot.app.plugin_manifest import (
    RUNTIME_SETUP_CALLS,
    iter_plugin_modules,
    validate_plugin_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class BootstrapState:
    driver: Any
    app: Any
    loaded_plugins: tuple[str, ...]
    runtime_setups: tuple[str, ...]


class RuntimeSetupError(TypeError):
    @classmethod
    def not_callable(cls, setup_ref: str) -> RuntimeSetupError:
        return cls(f"runtime setup is not callable: {setup_ref}")


def configure_third_party_logging() -> None:
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def load_manifest_plugins(
    load_plugin: Callable[[str], object] | None = None,
) -> tuple[str, ...]:
    validate_plugin_manifest()
    modules = iter_plugin_modules()
    plugin_loader = load_plugin or nonebot.load_plugin

    for module in modules:
        plugin_loader(module)

    return modules


def _load_runtime_setup(
    setup_ref: str,
    *,
    module_importer: Callable[[str], Any],
) -> Callable[[], object]:
    module_name, _separator, function_name = setup_ref.partition(":")
    module = module_importer(module_name)
    setup = getattr(module, function_name)
    if not callable(setup):
        raise RuntimeSetupError.not_callable(setup_ref)
    return setup


def run_runtime_setups(
    setup_refs: tuple[str, ...] | None = None,
    *,
    module_importer: Callable[[str], Any] = import_module,
) -> tuple[str, ...]:
    validate_plugin_manifest()
    refs = RUNTIME_SETUP_CALLS if setup_refs is None else setup_refs

    for setup_ref in refs:
        _load_runtime_setup(
            setup_ref,
            module_importer=module_importer,
        )()

    return refs


def bootstrap() -> BootstrapState:
    configure_third_party_logging()
    nonebot.init()

    driver = nonebot.get_driver()
    driver.register_adapter(ONEBOT_V11Adapter)

    app = nonebot.get_asgi()
    loaded_plugins = load_manifest_plugins()
    runtime_setups = run_runtime_setups()
    return BootstrapState(
        driver=driver,
        app=app,
        loaded_plugins=loaded_plugins,
        runtime_setups=runtime_setups,
    )


__all__ = [
    "BootstrapState",
    "RuntimeSetupError",
    "bootstrap",
    "load_manifest_plugins",
    "run_runtime_setups",
]
