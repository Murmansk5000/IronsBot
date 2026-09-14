from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    Bot,  # noqa: TC002 - NoneBot resolves it at runtime
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.context import build_notice_source, command_context
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.plugin_visibility import feature_help_visible
from ironsbot.integrations.onebot.replies import finish_message_sequence
from ironsbot.services.ai.actions import AiIntentActionExecutor
from ironsbot.services.ai.command_contracts import ai_intent_command_contracts

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.promotions import PromotionCatalog
    from ironsbot.services.ai.input_routing import AiInputRoutingService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.team.resource import TeamResourceService

ACTION_KEY = "_ai_intent_action"
ACTION_SOURCE_CONTEXT_KEY = "_ai_intent_source_context"

__plugin_meta__ = PluginMetadata(
    name="AI意图分析",
    description="按配置识别简短意图，并触发对应回复或功能。",
    usage="发送已配置关键词触发相应意图动作。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


@dataclass(frozen=True, slots=True)
class AiIntentDependencies:
    """OneBot dependencies needed by the configured AI action adapter."""

    service: AiService
    executor: AiIntentActionExecutor
    input_routing: AiInputRoutingService


def _resolve_action_command_id(
    _event: MessageEvent,
    state: T_State,
) -> str:
    action = state.get(ACTION_KEY)
    action_id = str(getattr(action, "id", "")).strip()
    return f"ai_intent.{action_id}" if action_id else "ai_intent"


def install(
    registry: MatcherFactory,
    dependencies: AiIntentDependencies,
    command_help_ids: tuple[str, ...],
) -> None:
    if not command_help_ids:
        return

    async def match_action(
        bot: Bot,
        event: MessageEvent,
        state: T_State,
    ) -> bool:
        text = event.get_plaintext().strip()
        input_context = message_input_context(event)
        if not dependencies.input_routing.decide(
            input_context,
            command_context(event),
        ).try_intent:
            return False
        message = input_context.message
        source_context = await build_notice_source(
            event,
            text,
            bot=bot,
        )
        action = await dependencies.service.classify_intent(
            text,
            actor=message.actor,
            conversation=message.conversation,
            source_context=source_context,
        )
        if action is None:
            return False
        state[ACTION_KEY] = action
        state[ACTION_SOURCE_CONTEXT_KEY] = source_context
        return True

    async def handle_action(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        action = state[ACTION_KEY]
        messages = await dependencies.executor.execute(
            action,
            event.get_plaintext(),
            source_context=str(state.get(ACTION_SOURCE_CONTEXT_KEY, "") or "") or None,
        )
        if not messages:
            return
        await finish_message_sequence(
            matcher,
            tuple(render_onebot_outbound_message(message) for message in messages),
            event=event,
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command(
            _resolve_action_command_id,
            help_ids=command_help_ids,
        ),
        rule=Rule(match_action),
        priority=registry.priority("ai_intent"),
        block=True,
    )
    matcher.append_handler(handle_action)


def plugin_contribution(  # noqa: PLR0913 - plugin dependencies stay explicit
    *,
    settings: Settings,
    service: AiService,
    features: FeatureService,
    promotions: PromotionCatalog,
    team_resource: TeamResourceService,
    input_routing: AiInputRoutingService,
) -> PluginContribution:
    """Declare configured intent actions and their natural-language matcher."""

    enabled = bool(settings.ai.api_key.strip()) and settings.ai.intent_actions_enabled
    command_contracts = ai_intent_command_contracts(settings)
    return PluginContribution(
        id="ai_intent",
        features=frozenset(
            {
                Feature.AI_INTENT,
                Feature.AI_INTENT_TEAM_RECOMMEND,
                Feature.AI_INTENT_FIRE_MANUAL,
            }
        ),
        help=HelpEntry(
            name="AI意图分析",
            description="按配置识别简短意图，并触发对应回复或功能。",
            group="ai",
            order=20,
            visible=partial(
                feature_help_visible,
                features=features,
                feature="ai_intent",
                enabled=enabled,
            ),
        ),
        commands=command_contracts,
        install=partial(
            install,
            dependencies=AiIntentDependencies(
                service=service,
                executor=AiIntentActionExecutor(
                    service,
                    promotions,
                    team_resource,
                ),
                input_routing=input_routing,
            ),
            command_help_ids=tuple(command.id for command in command_contracts),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            settings=context.settings,
            service=context.resources.ai,
            features=context.resources.features,
            promotions=context.resources.promotions,
            team_resource=context.resources.team_resource,
            input_routing=context.resources.ai_input_routing,
        ),
    )
