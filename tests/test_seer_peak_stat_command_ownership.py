from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import nonebot
import pytest
from nonebot.rule import fullmatch

from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.features import Feature
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.plugins.onebot.ai import _capture_ai_prompt
from ironsbot.services.seer import rank_list_parsing
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.countermark_stat_rank_messages import (
    build_countermark_stat_rank_message,
)
from ironsbot.services.seer.countermark_stat_rank_parsing import (
    parse_countermark_stat_rank_command,
)
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.peak import (
    PEAK_EXPERT_POOL_COMMANDS,
    PEAK_MASTER_POOL_COMMANDS,
    PEAK_PET_RANK_COMMANDS,
    PEAK_POOL_COMMANDS,
    PEAK_SUIT_RANK_COMMANDS,
    PEAK_TITLE_RANK_COMMANDS,
    PEAK_VOTE_COMMANDS,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.rank_catalog import RANK_COMMAND_MAP
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.rule import Rule

    from ironsbot.integrations.onebot.matchers import CommandPolicy


def _group() -> Mock:
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    group = Mock()
    group.features = FeatureService({}, {_ACTOR: _FEATURES}, frozenset())
    return group


_ACTOR = ActorRef(Platform.ONEBOT, "100")
_PRIVATE = ConversationRef(Platform.ONEBOT, "private", _ACTOR.id)
_FEATURES = frozenset(
    {"seer_peak", "seer_pet", "seer_mintmark", "seer_rank", "seer_data", "ai_chat"}
)


@pytest.fixture
def catalog() -> CommandCatalog:
    resolver = PlayerIdResolver(lambda _text, _conversation: None, lambda _actor: None)
    result = CommandCatalog()
    result.load(
        (
            PluginContribution(
                id="seer_query", commands=seer_command_contracts(resolver)
            ),
            PluginContribution(
                id="rank_help", commands=rank_help_command_contracts(resolver)
            ),
        ),
        known_features={feature.value for feature in Feature},
    )
    return result


@pytest.mark.parametrize(
    "text,expected",
    [
        ("限制池", "seer.peak.query"),
        ("巅峰专家池", "seer.peak.query"),
        ("大师池", "seer.peak.query"),
        ("竞技池票选", "seer.peak.query"),
        ("专家套装榜", "seer.peak.rank"),
        ("竞技称号榜", "seer.peak.rank"),
        ("狂野精灵总榜", "seer.peak.rank"),
        ("五角刻印速度榜", "seer.mintmark.rank"),
        ("刻印双防体排行榜", "seer.mintmark.rank"),
        ("刻印攻榜", "seer.mintmark.rank"),
        ("赛季时间", "seer.data.query"),
        ("新增内容", "seer.data.new_content"),
        ("竞技池变化", "seer.data.new_peak_pool"),
        ("专家池变化", "seer.data.new_peak_expert_pool"),
        ("大师池变化", "seer.data.new_peak_master_pool"),
        ("巅峰环境变化", "seer.data.peak_environment_changes"),
    ],
)
def test_non_example_peak_and_stat_commands_are_owned(
    catalog: CommandCatalog, text: str, expected: str
) -> None:
    features = FeatureService({}, {_ACTOR: _FEATURES}, frozenset())
    context = CommandContext(_ACTOR, _PRIVATE)
    assert [
        command.id
        for command in catalog.available_for_context(context, features)
        if command.matches_direct_input(context, text)
    ] == [expected]
    assert not _capture_ai_prompt(
        private_message_event(text, user_id=100), {}, features, catalog
    )


@pytest.mark.parametrize(
    "index,commands",
    tuple(
        enumerate(
            (
                PEAK_POOL_COMMANDS,
                PEAK_EXPERT_POOL_COMMANDS,
                PEAK_MASTER_POOL_COMMANDS,
                PEAK_VOTE_COMMANDS,
                PEAK_SUIT_RANK_COMMANDS,
                PEAK_TITLE_RANK_COMMANDS,
                PEAK_PET_RANK_COMMANDS,
            )
        )
    ),
)
@pytest.mark.asyncio
async def test_every_peak_alias_matches_installed_rule_and_catalog(
    catalog: CommandCatalog, index: int, commands: tuple[str, ...]
) -> None:
    group = _group()
    from ironsbot.plugins.onebot.seer.query.commands import peak_queries

    peak_queries.install(group)
    call = group.on_fullmatch.call_args_list[index]
    assert call.args[0] == commands
    policy = cast("CommandPolicy", call.kwargs["policy"])
    rule = fullmatch(commands) & cast("Rule", call.kwargs["rule"])
    context = CommandContext(_ACTOR, _PRIVATE)
    features = group.features
    disabled = FeatureService({}, {_ACTOR: frozenset({"ai_chat"})}, frozenset())
    for text in commands:
        assert await rule(
            cast("Bot", None), private_message_event(text, user_id=100), {}
        )
        assert (
            tuple(
                c.id
                for c in catalog.available_for_context(context, features)
                if c.matches_direct_input(context, text)
            )
            == policy.help_ids
        )
        assert not catalog.claims_direct_input(context, disabled, text)
        assert not _capture_ai_prompt(
            private_message_event(text, user_id=100), {}, features, catalog
        )
        for invalid in (f"/{text}", f"{text}是什么", f" {text}", " ".join(text)):
            assert not await rule(
                cast("Bot", None), private_message_event(invalid, user_id=100), {}
            )
            assert not catalog.claims_direct_input(context, features, invalid)


@pytest.mark.parametrize("alias", RANK_COMMAND_MAP)
def test_collection_and_player_rank_aliases_do_not_become_stat_commands(
    alias: str,
) -> None:
    assert rank_list_parsing.parse_rank_list_command(alias) is not None
    assert parse_countermark_stat_rank_command(alias) is None


def test_new_rank_alias_is_excluded_without_editing_a_stat_keyword_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "测试刻印收藏榜"
    monkeypatch.setitem(
        rank_list_parsing._NORMALIZED_COMMANDS, text, ("global", "刻印图鉴")
    )
    assert rank_list_parsing.parse_rank_list_command(text) is not None
    assert parse_countermark_stat_rank_command(text) is None


@pytest.mark.parametrize("text", ["２角刻印攻击排行", "刻印双防体排行榜", "刻印攻榜"])
@pytest.mark.asyncio
async def test_stat_matcher_uses_the_shared_parser(
    catalog: CommandCatalog, text: str
) -> None:
    group = _group()
    from ironsbot.plugins.onebot.seer.query.commands import countermark_stat_rank

    countermark_stat_rank.install(group)
    rule = cast("Rule", group.on_message.call_args.kwargs["rule"])
    state = {}
    assert await rule(
        cast("Bot", None), private_message_event(text, user_id=100), state
    )
    parsed = parse_countermark_stat_rank_command(text)
    assert parsed is not None
    assert state == {}
    assert catalog.claims_direct_input(
        CommandContext(_ACTOR, _PRIVATE), group.features, text
    )
    if text == "刻印攻榜":
        assert parsed.stat is None
        assert "需要指定属性" in build_countermark_stat_rank_message(parsed, [])


@pytest.mark.parametrize(
    "text", ["攻击榜", "看看限制池怎么样", "巅峰投票说明", "刻印V9"]
)
def test_unrelated_input_is_not_claimed_by_peak_or_stat_sections(
    catalog: CommandCatalog, text: str
) -> None:
    context = CommandContext(_ACTOR, _PRIVATE)
    features = FeatureService({}, {_ACTOR: _FEATURES}, frozenset())
    expected_ids = {"seer.peak.query", "seer.peak.rank", "seer.mintmark.rank"}
    candidates = [
        c
        for c in catalog.available_for_context(context, features)
        if c.id in expected_ids
    ]
    assert {c.id for c in candidates} == expected_ids
    assert not any(c.matches_direct_input(context, text) for c in candidates)


@pytest.mark.parametrize(
    "index,commands",
    tuple(
        enumerate(
            (
                WEEKLY_PREVIEW_COMMANDS,
                DATA_VERSION_COMMANDS,
                SEASON_COUNTDOWN_COMMANDS,
            )
        )
    ),
)
@pytest.mark.asyncio
async def test_data_aliases_share_installed_syntax(
    catalog: CommandCatalog, index: int, commands: tuple[str, ...]
) -> None:
    group = _group()
    from ironsbot.plugins.onebot.seer.query.commands import data_queries

    data_queries.install(group)
    call = group.on_fullmatch.call_args_list[index]
    assert call.args[0] == commands
    rule = fullmatch(commands) & cast("Rule", call.kwargs["rule"])
    context = CommandContext(_ACTOR, _PRIVATE)
    for text in commands:
        assert await rule(
            cast("Bot", None), private_message_event(text, user_id=100), {}
        )
        assert [
            c.id
            for c in catalog.available_for_context(context, group.features)
            if c.matches_direct_input(context, text)
        ] == ["seer.data.query"]
