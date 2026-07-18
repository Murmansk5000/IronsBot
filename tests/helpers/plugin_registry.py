from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ironsbot.app.registry import build_plugin_registry
from ironsbot.config.models.app import AppConfig
from ironsbot.config.models.secrets import CredentialsConfig, SecretsConfig
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.services.operations.headless import HeadlessService
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from ironsbot.runtime.plugins import PluginDefinition
    from ironsbot.services.activity.service import ActivityService


async def _noop_shutdown() -> None:
    return


def build_test_plugin_registry() -> tuple[PluginDefinition, ...]:
    config = AppConfig()
    runtime = build_test_runtime(
        feature_config=config.feature,
    )
    return build_plugin_registry(
        config=config,
        features=runtime.features,
        delivery=runtime.delivery,
        admin_notices=runtime.admin_notices,
        activity_service=cast("ActivityService", object()),
        headless=HeadlessService(
            ClientManager(),
            CredentialsConfig(),
            config.runtime.headless,
            config.runtime.headless_notice,
            runtime.admin_notices,
        ),
        secrets=SecretsConfig(),
        shutdown_activity=_noop_shutdown,
    )
