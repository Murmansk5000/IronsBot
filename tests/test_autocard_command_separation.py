from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.player_references import PlayerReferenceChoice
from ironsbot.services.portable_new_content_commands import (
    build_portable_new_content_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import deliver_portable_reply
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.data_query_commands import NEW_CONTENT_COMMAND_SPECS
from ironsbot.services.seer.new_content import NewContentCategoryState, NewContentItem
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_commands import is_query_input_syntax
from ironsbot.services.seer.rank_catalog import RANK_COMMAND_MAP, rank_command_names
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from tests.test_player_reference_ownership import _runtime
from tests.test_portable_new_content_commands import (
    _context,
    _features,
    _MenuRenderer,
    _resources,
    _snapshot,
)

PLAYER_ID = 123456
SELECTED_PLAYER_ID = 700002


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "text,owner",
    [
        ("群星卡牌98", "seer.autocard.query"),
        ("卡牌98", "seer.autocard.query"),
        ("群星角色98", "seer.autocard.query"),
        ("群星芯片98", "seer.autocard.query"),
        ("战斗芯片98", "seer.autocard.query"),
        ("强化芯片98", "seer.autocard.query"),
        ("芯片98", "seer.autocard.query"),
        ("群星场地沧岚", "seer.autocard.sanctuary"),
        ("场地沧岚", "seer.autocard.sanctuary"),
        ("圣域沧岚", "seer.autocard.sanctuary"),
        ("祝印潮涌", "seer.autocard.sanctuary"),
        ("新增卡牌", "seer.data.new_autocard_card"),
        ("新增群星", "seer.data.new_autocard"),
        ("群星牌123456", "seer.player.default"),
        ("群星之巅榜8602分", "rank.global_collection"),
        ("群星榜8612分", "rank.global_collection"),
        ("群星之巅榜10000名", "rank.global_collection"),
        ("群星榜", "rank.global_collection"),
        ("群星牌百强榜", "rank.global_collection"),
        ("样本群星积分榜", "rank.sample_collection"),
        ("机器人群星积分榜", "rank.sample_collection"),
    ],
)
def test_full_catalog_has_single_owner(
    platform: Platform, text: str, owner: str
) -> None:
    resolver = PlayerIdResolver(lambda *_: None, Mock())
    actor = ActorRef(platform, "caller")
    context = CommandContext(actor, ConversationRef(platform, "private", actor.id))
    contracts = (
        *seer_command_contracts(resolver),
        *rank_help_command_contracts(resolver),
    )
    assert [c.id for c in contracts if c.matches_direct_input(context, text)] == [owner]


@pytest.mark.parametrize(
    "text",
    [
        "群星牌榜",
        "群星牌榜8602分",
        "样本群星牌积分榜",
        "机器人群星牌积分榜",
        "群星牌场地沧岚",
        "群星牌圣域沧岚",
        "群星牌芯片98",
        "查询群星牌布布种子",
        "布布种子群星牌",
        "新增群星牌",
        "每周群星牌角色",
        "本周群星牌圣域",
        "更新群星牌卡牌",
    ],
)
@pytest.mark.asyncio
async def test_retired_commands_are_silent_without_ai_or_business_work(
    text: str,
) -> None:
    context = _input(Platform.QQ_OFFICIAL, text)
    runtime = _runtime(
        context,
        PlayerIdResolver(lambda *_: PLAYER_ID, lambda _: PLAYER_ID),
        enabled=True,
    )
    assert is_query_input_syntax(text)
    assert await runtime.router.dispatch(context) is None
    runtime.service.shortcut.assert_not_awaited()
    runtime.rank.prepare_player.assert_not_awaited()
    runtime.cooldown.admit.assert_not_called()


def test_sample_names_and_weekly_aliases_do_not_reintroduce_retired_names() -> None:
    assert rank_command_names("global", "群星牌")[0] == "群星之巅榜"
    assert rank_command_names("local", "群星牌")[0] == "样本群星积分榜"
    assert "群星牌榜" not in RANK_COMMAND_MAP
    assert not any(
        "群星牌" in name
        for name, (kind, key) in RANK_COMMAND_MAP.items()
        if kind == "local" and key == "群星牌"
    )
    specs = [
        spec
        for spec in NEW_CONTENT_COMMAND_SPECS
        if spec.command_id.startswith("seer.data.new_autocard")
    ]
    assert not any("群星牌" in command for spec in specs for command in spec.commands)


def _input(platform: Platform, text: str, message_id: str = "1") -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "caller"),
            ConversationRef(platform, "group", "group"),
            message_id,
            text,
        ),
        mentions_bot=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "first,second",
    [("群星牌123456", "群星榜123456"), ("群星之巅榜示例", "群星牌123456")],
)
async def test_player_aliases_share_business_action_and_completed_cooldown(
    platform: Platform, first: str, second: str
) -> None:
    context = _input(platform, first)
    resolver = PlayerIdResolver(
        lambda ref, _group: PLAYER_ID if ref in {"示例", "123456"} else None,
        lambda _: PLAYER_ID,
    )
    runtime = _runtime(context, resolver, enabled=True)
    reply = await runtime.router.dispatch(context)
    assert reply is not None
    await deliver_portable_reply(
        reply, AsyncMock(return_value=SendResult(delivered=True, message_id="receipt"))
    )
    runtime.service.shortcut.assert_awaited_once()
    args = runtime.service.shortcut.call_args.args
    assert args[0].kind == "autocard" and args[0].player_id == PLAYER_ID
    runtime.rank.prepare_player.assert_not_awaited()
    again = await runtime.router.dispatch(_input(platform, second, "2"))
    assert again is not None
    assert "重复" in "".join(
        part.text for part in again.message.parts if isinstance(part, TextPart)
    )
    runtime.service.shortcut.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "features,text,allowed",
    [
        (frozenset({"seer_rank"}), "群星榜123456", True),
        (frozenset({"seer_rank"}), "群星牌123456", False),
        (frozenset({"seer_player"}), "群星牌123456", True),
        (frozenset({"seer_player"}), "群星榜123456", False),
    ],
)
async def test_shared_player_path_preserves_entry_feature(
    features: frozenset[str], text: str, *, allowed: bool
) -> None:
    context = _input(Platform.QQ_OFFICIAL, text)
    runtime = _runtime(
        context,
        PlayerIdResolver(
            lambda ref, _group: PLAYER_ID if ref == "123456" else None,
            lambda _: PLAYER_ID,
        ),
        enabled=True,
        granted_features=features,
    )
    reply = await runtime.router.dispatch(context)
    if allowed:
        assert reply is not None
        await deliver_portable_reply(
            reply,
            AsyncMock(return_value=SendResult(delivered=True, message_id="receipt")),
        )
        runtime.service.shortcut.assert_awaited_once()
    else:
        assert reply is None
        runtime.service.shortcut.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command_id,text,category",
    [
        ("seer.data.new_autocard_card", "新增卡牌", "autocard_card"),
        ("seer.data.new_autocard_role", "新增群星角色", "autocard_role"),
        ("seer.data.new_autocard_chip", "新增群星芯片", "autocard_chip"),
        (
            "seer.data.new_autocard_sanctuary_effect",
            "新增群星场地",
            "autocard_sanctuary_effect",
        ),
    ],
)
async def test_weekly_categories_are_scoped(
    command_id: str, text: str, category: str
) -> None:
    categories = (
        "autocard_card",
        "autocard_role",
        "autocard_chip",
        "autocard_sanctuary_effect",
    )
    snapshot = replace(
        _snapshot(),
        items=tuple(
            NewContentItem(kind, index, "示例", index, {}, "added")
            for index, kind in enumerate(categories)
        ),
        category_states=tuple(
            NewContentCategoryState(kind, comparison_ready=True, reason="ready")
            for kind in categories
        ),
    )
    renderer = _MenuRenderer()
    operations = build_portable_new_content_operations(
        _resources(snapshot, renderer),
        PortableQuerySessions(),
        _features("seer_data", "seer_autocard"),
    )
    await operations[command_id](text, _context(text))
    assert renderer.calls == [((category,), category)]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "prefix", ["群星牌", "群星榜", "群星之巅榜", "群星百强榜", "群星牌百强榜"]
)
async def test_player_rank_aliases_share_ambiguous_target_menu(
    platform: Platform, prefix: str
) -> None:
    context = _input(platform, f"{prefix}玩家")
    resolver = PlayerIdResolver(
        lambda *_: None,
        lambda _: PLAYER_ID,
        reference_search=lambda *_: (
            PlayerReferenceChoice(700001, "玩家甲"),
            PlayerReferenceChoice(SELECTED_PLAYER_ID, "玩家乙"),
        ),
    )
    runtime = _runtime(context, resolver, enabled=True)
    reply = await runtime.router.dispatch(context)
    assert reply is not None and reply.message.prompt is not None
    runtime.service.shortcut.assert_not_awaited()
    await deliver_portable_reply(
        reply, AsyncMock(return_value=SendResult(delivered=True, message_id="menu"))
    )
    selected = await runtime.sessions.select("2", context, allow_deferred=True)
    assert selected is not None
    await deliver_portable_reply(
        selected,
        AsyncMock(return_value=SendResult(delivered=True, message_id="result")),
    )
    runtime.service.shortcut.assert_awaited_once()
    assert runtime.service.shortcut.call_args.args[0].player_id == SELECTED_PLAYER_ID
    runtime.rank.prepare_player.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("bound", [False, True])
async def test_rank_member_target_uses_shared_player_flow(
    platform: Platform, *, bound: bool
) -> None:
    context = _input(platform, "群星榜")
    member = ActorRef(platform, "member")
    context = replace(
        context, message=replace(context.message, direct_mentions=(member,))
    )
    resolver = PlayerIdResolver(
        lambda *_: None, lambda actor: PLAYER_ID if bound or actor != member else None
    )
    runtime = _runtime(context, resolver, enabled=True)
    reply = await runtime.router.dispatch(context)
    assert reply is not None
    await deliver_portable_reply(
        reply, AsyncMock(return_value=SendResult(delivered=True, message_id="result"))
    )
    if bound:
        runtime.service.shortcut.assert_awaited_once()
        assert runtime.service.shortcut.call_args.args[0].player_id == PLAYER_ID
    else:
        runtime.service.shortcut.assert_not_awaited()
        assert "未绑定" in "".join(
            part.text for part in reply.message.parts if isinstance(part, TextPart)
        )
    runtime.rank.prepare_player.assert_not_awaited()
