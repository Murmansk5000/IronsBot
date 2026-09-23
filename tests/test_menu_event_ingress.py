from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot, Message, MessageSegment
from nonebot.exception import IgnoredException
from nonebot.matcher import matchers
from nonebot.message import handle_event

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.response_admission import ResponseAdmissionDecision
from ironsbot.integrations.onebot.ingress_policy import OneBotIngressPolicy
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import (
    install_portable_menu_router,
    make_portable_query_handler,
)
from ironsbot.integrations.onebot.prompt_sessions import PromptSessionManager
from ironsbot.integrations.onebot.self_commands import (
    SelfCommandAdapter,
    SelfCommandGate,
)
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.integrations.onebot.matcher_contracts import CommandCooldown


@pytest.fixture
def ingress(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=None)
        driver = nonebot.get_driver()
    saved = dict(matchers.items())
    matchers.clear()
    sends: list[dict[str, Any]] = []

    async def api(_adapter: Adapter, bot: Bot, api: str, **data: Any) -> object:
        assert api in {"send_msg", "send_group_msg"}
        sends.append({"bot": bot.self_id, **data})
        return {"message_id": len(sends) + 100}

    monkeypatch.setattr(Adapter, "_call_api", api)
    adapter = Adapter(driver)
    sessions = PortableQuerySessions()
    cooldown = Mock()
    cooldown.admit.return_value = ResponseAdmissionDecision(allowed=True)
    factory = MatcherFactory(
        cast("CommandCooldown", cooldown), SimpleNamespace(), PromptSessionManager()
    )
    features = FeatureService({}, {}, frozenset())
    install_portable_menu_router(factory, sessions, features)
    selected: list[tuple[str, int]] = []
    gate = asyncio.Event()
    gate.set()

    async def select(value: int, ctx: MessageInputContext) -> OutboundMessage:
        selected.append((ctx.message.actor.id, value))
        return OutboundMessage.from_text(f"result:{value}")

    async def query(text: str, context: MessageInputContext) -> OutboundMessage:
        del text
        await gate.wait()
        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=tuple(range(1, 8)),
                select=select,
                prompt=OutboundMessage.from_text("menu"),
                shareable=True,
                keep_open=True,
                can_select=lambda _value, responder: (
                    responder.message.actor.id != "103"
                ),
            ),
        )

    command = factory.on_fullmatch(
        "菜单", policy=CommandPolicy.command("test.menu"), block=True
    )
    command.append_handler(make_portable_query_handler(query, sessions))
    try:
        yield SimpleNamespace(
            bots=(Bot(adapter, "1"), Bot(adapter, "2")),
            sessions=sessions,
            sends=sends,
            selected=selected,
            gate=gate,
        )
    finally:
        matchers.clear()
        matchers.update(saved)


def _reply(text: str, *, user: int, anchor: int, shape: str = "metadata", bot: int = 1):
    message = MessageSegment.at(bot) + Message(text)
    event = group_message_event(text, user_id=user, self_id=bot, message=message)
    if shape == "metadata":
        return group_message_event(
            text,
            user_id=user,
            self_id=bot,
            message=message,
            reply_sender_user_id=bot,
            reply_message_id=anchor,
        )
    quoted = MessageSegment.reply(anchor) + message
    if shape == "message":
        event.message = quoted
    else:
        event.original_message = quoted
    return event


@pytest.mark.asyncio
async def test_prefixed_self_menu_selection_cancel_and_replay(
    ingress: SimpleNamespace,
) -> None:
    policy = OneBotIngressPolicy(
        messages_enabled=True,
        self_commands=SelfCommandGate(
            SelfCommandsConfig(enabled=True, prefixes=["demo "])
        ),
    )

    async def deliver(text: str, message_id: int) -> None:
        data = group_message_event(text, user_id=1, message_id=message_id).model_dump()
        data["post_type"] = "message_sent"
        event = SelfCommandAdapter.json_to_event(data)
        assert event is not None
        await policy.process(event)
        await handle_event(ingress.bots[0], event)

    await deliver("demo 菜单", -10)
    assert len(ingress.sends) == 1
    with pytest.raises(IgnoredException):
        await deliver("1", -11)
    await deliver("demo 1", -12)
    with pytest.raises(IgnoredException):
        await deliver("demo 1", -12)
    await deliver("demo 2", -13)
    await deliver("demo 0", -14)
    assert ingress.selected == [("1", 1), ("1", 2)]
    assert not ingress.sessions.has_active_session(
        message_input_context(group_message_event(user_id=1))
    )
    for sent in ingress.sends:
        assert not any(part.type == "at" for part in sent["message"])


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["metadata", "message", "original"])
async def test_real_event_cross_member_sessions_are_independent(
    ingress: SimpleNamespace, shape: str
) -> None:
    bot = ingress.bots[0]
    await handle_event(bot, group_message_event("菜单", user_id=101))
    assert len(ingress.sends) == 1
    await handle_event(bot, group_message_event("1", user_id=101))
    await handle_event(bot, _reply("2", user=102, anchor=101, shape=shape))
    await handle_event(bot, group_message_event("3", user_id=102))
    await handle_event(bot, group_message_event("0", user_id=101))
    await handle_event(bot, group_message_event("7", user_id=102))
    assert ingress.selected == [("101", 1), ("102", 2), ("102", 3), ("102", 7)]
    assert not ingress.sessions.has_active_session(
        message_input_context(group_message_event(user_id=101))
    )
    assert ingress.sessions.has_active_session(
        message_input_context(group_message_event(user_id=102))
    )
    for sent in ingress.sends[2:4]:
        assert MessageSegment.at(102) in sent["message"]


@pytest.mark.asyncio
async def test_quotes_cannot_cross_bot_or_result_and_denial_keeps_own_menu(
    ingress: SimpleNamespace,
) -> None:
    first, second = ingress.bots
    await handle_event(first, group_message_event("菜单", user_id=101))
    await handle_event(second, group_message_event("菜单", user_id=101, self_id=2))
    await handle_event(first, group_message_event("菜单", user_id=103))
    own = ingress.sessions.active_prompt(
        message_input_context(group_message_event(user_id=103))
    )
    await handle_event(first, _reply("1", user=103, anchor=101))
    assert (
        ingress.sessions.active_prompt(
            message_input_context(group_message_event(user_id=103))
        )
        == own
    )
    await handle_event(second, _reply("1", user=102, anchor=101, bot=2))
    await handle_event(first, _reply("1", user=101, anchor=999))
    await handle_event(first, group_message_event("1", user_id=101))
    await handle_event(first, _reply("2", user=101, anchor=105))
    assert ingress.selected == [("101", 1)]


@pytest.mark.asyncio
async def test_early_seven_is_queued_fifo_and_new_command_replaces_menu(
    ingress: SimpleNamespace,
) -> None:
    bot = ingress.bots[0]
    ingress.gate.clear()
    opening = asyncio.create_task(
        handle_event(bot, group_message_event("菜单", user_id=101))
    )
    for _ in range(100):
        if ingress.sessions.recognizes_response(
            "7", message_input_context(group_message_event(user_id=101))
        ):
            break
        await asyncio.sleep(0)
    selections = []
    for index in (1, 2, 3, 7):
        selections.append(
            asyncio.create_task(
                handle_event(bot, group_message_event(str(index), user_id=101))
            )
        )
        await asyncio.sleep(0)
    ingress.gate.set()
    await asyncio.gather(opening, *selections)
    assert ingress.selected == [("101", index) for index in (1, 2, 3, 7)]
    await handle_event(bot, group_message_event("菜单", user_id=101))
    await handle_event(bot, _reply("1", user=101, anchor=101))
    assert ingress.selected == [("101", index) for index in (1, 2, 3, 7)]
