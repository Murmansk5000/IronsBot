from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.messaging import (
    CommandCooldownConfig,
    CommandCooldownWindowConfig,
)
from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import SendResult
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.player_references import PlayerReferenceChoice
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_rank_commands import build_portable_rank_operations
from ironsbot.services.portable_reply import deliver_portable_reply
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from ironsbot.services.seer.rank_queries import RankPlayerPreparedReply


def _runtime(
    platform: Platform, *, candidates: bool, scope: Literal["group", "private"]
) -> SimpleNamespace:
    actor = ActorRef(platform, "caller")
    conversation = ConversationRef(
        platform, scope, "group" if scope == "group" else actor.id
    )
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            actor,
            conversation,
            "1",
            "成就榜示例" if candidates else "成就榜700001",
        ),
        mentions_bot=True,
    )
    features = FeatureService(
        {conversation: frozenset({"seer_rank"})},
        {actor: frozenset({"seer_rank"})},
        frozenset(),
    )
    resolver = PlayerIdResolver(
        lambda reference, _group: int(reference) if reference.isdecimal() else None,
        lambda _actor: None,
        reference_search=lambda *_: (
            PlayerReferenceChoice(700001, "示例甲"),
            PlayerReferenceChoice(700002, "示例乙"),
        ),
    )
    sessions = PortableQuerySessions()
    config = CommandCooldownConfig(
        enabled=True,
        windows=[CommandCooldownWindowConfig(window_seconds=60, max_requests=1)],
    )
    requests = Mock(wraps=InFlightRequestService(features, config))
    cooldown = Mock(wraps=CommandCooldownService(config, features))
    sessions.interactions.request_service = requests
    sessions.interactions.cooldown = cooldown
    charged = Mock()
    service = Mock(
        default_limit=Mock(return_value=10),
        prepare_player=AsyncMock(
            return_value=RankPlayerPreparedReply("player result", on_delivered=charged)
        ),
    )
    operations = build_portable_rank_operations(
        service, resolver, sessions, AsyncMock(), features
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="rank_help",
                commands=tuple(
                    command
                    for command in rank_help_command_contracts(resolver)
                    if command.id in operations
                ),
            ),
        ),
        known_features=("seer_rank",),
    )
    router = PortableCommandRouter(
        catalog,
        operations,
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    return SimpleNamespace(
        context=context,
        router=router,
        requests=requests,
        cooldown=cooldown,
        service=service,
        charged=charged,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("scope", ["group", "private"])
@pytest.mark.parametrize("candidates", [False, True])
@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "business_failure",
        "delivery_failure",
        "exception",
        "cancelled",
        "receipt_callback_failure",
    ],
)
async def test_rank_player_uses_common_admission_and_delivery_settlement(
    platform: Platform,
    outcome: str,
    scope: Literal["group", "private"],
    *,
    candidates: bool,
) -> None:
    runtime = _runtime(platform, candidates=candidates, scope=scope)
    _inject_failure(runtime, outcome)

    context = runtime.context
    if candidates:
        prompt = await runtime.router.dispatch(context)
        assert prompt is not None and prompt.message.prompt is not None
        await deliver_portable_reply(
            prompt,
            AsyncMock(return_value=SendResult(delivered=True, message_id="menu")),
        )
        context = MessageInputContext(
            IncomingMessageRef(
                platform, context.message.actor, context.message.conversation, "2", "2"
            ),
            mentions_bot=False,
        )
        runtime.requests.reset_mock()
        runtime.cooldown.reset_mock()
    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await runtime.router.dispatch(context)
    else:
        reply = await runtime.router.dispatch(context)
        assert reply is not None
        runtime.requests.finish.assert_not_called()
        runtime.cooldown.finish.assert_not_called()
        send = AsyncMock(
            return_value=SendResult(
                delivered=outcome != "delivery_failure",
                message_id=None if outcome == "delivery_failure" else "receipt",
                error_code="rejected" if outcome == "delivery_failure" else None,
            )
        )
        if outcome == "receipt_callback_failure":
            with pytest.raises(RuntimeError, match="quota receipt failed"):
                await deliver_portable_reply(reply, send)
        else:
            await deliver_portable_reply(reply, send)
    runtime.service.prepare_player.assert_awaited_once()
    runtime.requests.admit.assert_called_once()
    runtime.cooldown.admit.assert_called_once()
    request = runtime.requests.admit.call_args.kwargs["request"]
    assert request.action.id == "seer.rank.player.成就点数"
    assert request.target.key == ("700002" if candidates else "700001")
    assert (
        runtime.cooldown.admit.call_args.kwargs["command_id"]
        == request.action.cooldown_key
    )
    if outcome == "success":
        runtime.requests.finish.assert_called_once()
        runtime.cooldown.finish.assert_called_once()
        runtime.requests.release.assert_not_called()
        runtime.cooldown.release.assert_not_called()
        runtime.charged.assert_called_once()
    else:
        runtime.requests.finish.assert_not_called()
        runtime.cooldown.finish.assert_not_called()
        runtime.requests.release.assert_called_once()
        runtime.cooldown.release.assert_called_once()
    if outcome in {"delivery_failure", "exception", "cancelled"}:
        runtime.charged.assert_not_called()
    if outcome != "success":
        await _assert_failed_request_can_retry(runtime, context, request.target.key)


def _inject_failure(runtime: SimpleNamespace, outcome: str) -> None:
    if outcome == "business_failure":
        runtime.service.prepare_player.return_value = RankPlayerPreparedReply(
            "query failed", request_succeeded=False
        )
    elif outcome in {"exception", "cancelled"}:
        runtime.service.prepare_player.side_effect = (
            RuntimeError("query failed")
            if outcome == "exception"
            else asyncio.CancelledError()
        )
    elif outcome == "receipt_callback_failure":
        runtime.charged.side_effect = RuntimeError("quota receipt failed")


async def _assert_failed_request_can_retry(
    runtime: SimpleNamespace, context: MessageInputContext, player_key: str
) -> None:
    previous_calls = runtime.service.prepare_player.await_count
    runtime.service.prepare_player.side_effect = None
    runtime.charged.side_effect = None
    runtime.charged.reset_mock()
    runtime.service.prepare_player.return_value = RankPlayerPreparedReply(
        "recovered", on_delivered=runtime.charged
    )
    retry = MessageInputContext(
        IncomingMessageRef(
            context.message.platform,
            context.message.actor,
            context.message.conversation,
            "3",
            f"成就榜{player_key}",
        ),
        mentions_bot=True,
    )
    recovered = await runtime.router.dispatch(retry)
    assert recovered is not None
    assert await deliver_portable_reply(
        recovered,
        AsyncMock(return_value=SendResult(delivered=True, message_id="retry")),
    )
    assert runtime.service.prepare_player.await_count == previous_calls + 1
    runtime.requests.finish.assert_called_once()
    runtime.cooldown.finish.assert_called_once()
    runtime.charged.assert_called_once()
