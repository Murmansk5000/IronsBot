from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.portable_commands import PortableCommandRouter

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation


def operation_router(
    operation: PortableOperation,
    context: MessageInputContext,
    sessions: PortableQuerySessions | None = None,
) -> PortableCommandRouter:
    features = FeatureService({}, {}, frozenset())
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="test",
                commands=(
                    CommandContract(
                        id="test.query",
                        plugin_id="test",
                        section="test",
                        examples=(context.text,),
                        description="query",
                        category=RequestCategory.OTHER_NETWORK,
                    ),
                ),
            ),
        ),
        known_features=(),
    )
    return PortableCommandRouter(
        catalog,
        {"test.query": operation},
        features,
        ai=cast("Any", None),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
