from __future__ import annotations

from unittest.mock import Mock

import pytest

from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.plugins.onebot.ai import _capture_ai_prompt
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.rank_catalog import RANK_COMMAND_MAP
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, LOCAL_RANKS
from tests.helpers.onebot_events import private_message_event

_ACTOR = ActorRef(Platform.ONEBOT, "100")
_GROUP = ConversationRef(Platform.ONEBOT, "group", "200")
_PRIVATE = ConversationRef(Platform.ONEBOT, "private", _ACTOR.id)


@pytest.fixture
def catalog() -> CommandCatalog:
    resolver = PlayerIdResolver(
        lambda reference, conversation: (
            123456
            if reference == "公开示例"
            or (reference == "本群示例" and conversation == _GROUP)
            else None
        ),
        Mock(side_effect=AssertionError("recognition must not load bindings")),
        privileged_reference_lookup=lambda reference, _conversation: (
            123456 if reference in {"公开示例", "本群示例", "管理示例"} else None
        ),
        is_privileged_actor=lambda actor: actor.id == "101",
    )
    result = CommandCatalog()
    result.load(
        (
            PluginContribution(
                id="rank_help", commands=rank_help_command_contracts(resolver)
            ),
        ),
        known_features={"seer_rank"},
    )
    return result


def _features(*, superuser: bool = False, enabled: bool = True) -> FeatureService:
    allowed = frozenset({"seer_rank", "ai_chat"} if enabled else {"ai_chat"})
    return FeatureService(
        {_GROUP: allowed},
        {_ACTOR: allowed},
        frozenset({_ACTOR}) if superuser else frozenset(),
    )


@pytest.mark.parametrize("alias,rank", RANK_COMMAND_MAP.items())
@pytest.mark.parametrize("suffix", ["", "15名", "第2页", "21-40"])
def test_rank_alias_and_window_are_owned_by_exactly_the_right_section(
    catalog: CommandCatalog, alias: str, rank: tuple[str, str], suffix: str
) -> None:
    kind, key = rank
    peak = (
        GLOBAL_RANKS[key].peak_season_sub_key
        if kind == "global"
        else LOCAL_RANKS[key].season_limited
    )
    category = "global" if kind == "global" else "sample"
    expected = f"rank.{category}_{'peak' if peak else 'collection'}"
    context = CommandContext(_ACTOR, _PRIVATE)
    text = alias + suffix
    matches = [
        command.id
        for command in catalog.available_for_context(context, _features())
        if command.matches_direct_input(context, text)
    ]
    assert matches == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "专家榜15名",
        "群星榜3149分",
        "成就榜5000点",
        "狂野榜圣皇36星",
        "成就榜123456",
        "成就榜26",
        "排行榜帮助",
        "有哪些榜单",
        "可用榜单",
    ],
)
def test_ai_leaves_valid_rank_commands_to_the_catalog(
    catalog: CommandCatalog, text: str
) -> None:
    assert not _capture_ai_prompt(
        private_message_event(text, user_id=int(_ACTOR.id)), {}, _features(), catalog
    )


@pytest.mark.parametrize(
    "text",
    [
        "专家榜是什么",
        "专家榜第0页",
        "皮肤榜100-1",
        "样本群星牌榜3149分",
        "样本成就榜123456",
        "群星牌榜未知玩家",
        "/专家榜",
        "榜单情况",
        "刷新样本",
        "榜单显示 20",
        "刷新榜单 图鉴榜",
        "缓存榜单 图鉴榜 1-100",
    ],
)
def test_invalid_or_missing_prefix_input_is_not_claimed(
    catalog: CommandCatalog, text: str
) -> None:
    assert not catalog.claims_direct_input(
        CommandContext(_ACTOR, _GROUP, "owner"), _features(superuser=True), text
    )


@pytest.mark.parametrize(
    "text",
    [
        "/样本状态",
        "/刷新样本",
        "/榜单状态",
        "/榜单状态群星榜",
        "/刷新榜单专家榜",
        "/缓存排行图鉴榜20到40",
    ],
)
def test_cache_management_ownership_requires_superuser(
    catalog: CommandCatalog, text: str
) -> None:
    context = CommandContext(_ACTOR, _GROUP, "owner")
    assert catalog.claims_direct_input(context, _features(superuser=True), text)
    assert not catalog.claims_direct_input(context, _features(), text)


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
def test_display_management_respects_group_role_and_private_scope(
    catalog: CommandCatalog, role: str
) -> None:
    text = "/榜单默认数量30"
    assert catalog.claims_direct_input(
        CommandContext(_ACTOR, _GROUP, role), _features(), text
    ) is (role != "member")
    assert not catalog.claims_direct_input(
        CommandContext(_ACTOR, _PRIVATE), _features(superuser=True), text
    )


def test_disabled_rank_feature_does_not_claim_parameterized_queries(
    catalog: CommandCatalog,
) -> None:
    assert not catalog.claims_direct_input(
        CommandContext(_ACTOR, _PRIVATE), _features(enabled=False), "专家榜15名"
    )


@pytest.mark.parametrize("prefix", ["群星牌榜", "成就榜", "专家榜"])
@pytest.mark.parametrize(
    "reference,group,privileged,expected",
    [
        ("公开示例", False, False, True),
        ("本群示例", True, False, True),
        ("本群示例", False, False, False),
        ("管理示例", False, True, True),
        ("管理示例", False, False, False),
        ("未知别名", True, True, False),
    ],
)
def test_rank_player_alias_ownership_uses_actor_and_conversation(  # noqa: PLR0913
    catalog: CommandCatalog,
    prefix: str,
    reference: str,
    *,
    group: bool,
    privileged: bool,
    expected: bool,
) -> None:
    actor = ActorRef(Platform.ONEBOT, "101") if privileged else _ACTOR
    conversation = (
        _GROUP if group else ConversationRef(Platform.ONEBOT, "private", actor.id)
    )
    features = FeatureService(
        {_GROUP: frozenset({"seer_rank"})},
        {actor: frozenset({"seer_rank"})},
        frozenset({actor}) if privileged else frozenset(),
    )
    assert (
        catalog.claims_direct_input(
            CommandContext(actor, conversation), features, prefix + reference
        )
        is expected
    )
