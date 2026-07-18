from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ironsbot.app.registry import build_plugin_registry
from ironsbot.config.models.app import AppConfig

if TYPE_CHECKING:
    from ironsbot.runtime.plugins import PluginDefinition
    from ironsbot.services.activity.service import ActivityService


async def _noop_shutdown() -> None:
    return


def build_test_plugin_registry() -> tuple[PluginDefinition, ...]:
    return build_plugin_registry(
        config=AppConfig(),
        activity_service=cast("ActivityService", object()),
        shutdown_activity=_noop_shutdown,
    )
