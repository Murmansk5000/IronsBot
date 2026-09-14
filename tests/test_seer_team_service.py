from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.config.models.seer import TeamQueryConfig
from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.portable_seer_commands import build_portable_team_query_operation
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_commands import team_query_input_matcher
from ironsbot.services.seer.team import (
    SeerTeamQueryService,
    TeamBossActivityStatus,
    TeamQueryActor,
    format_team_info,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.team.resource import TeamResourceService

TEAM_ID = 123456


def _actor(user_id: int = 1) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def _group(group_id: int = 456) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


@dataclass(frozen=True)
class TeamInfo:
    name: str = "测试战队"
    team_id: int = TEAM_ID
    leader: int = 654321
    member_count: int = 42
    new_team_level: int = 9
    score: int = 777
    tech_center_level: int = 3
    bonus_center_level: int = 4
    res_center_level: int = 5
    total_boss_dmg: int = 196
    interest: int = 1
    join_flag: int = 2
    visit_flag: int = 3
    team_func_disalbed: int = 0
    drawing_uint: int = 123
    logo_bg: int = 11
    logo_icon: int = 22
    logo_color: int = 33
    txt_color: int = 44
    logo_word: str = "T"
    slogan: str = "一起冲"
    notice: str = "今晚集合"


class FakeOperations:
    @contextmanager
    def track(self, *_args: object, **_kwargs: object) -> Iterator[None]:
        yield


class FakeGame:
    user_id = 10001
    operations = FakeOperations()

    def __init__(self, result: TeamInfo | Exception) -> None:
        self._result = result

    async def get_team_info(self, _team_id: int) -> TeamInfo:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeHeadless:
    def __init__(self, result: TeamInfo | Exception) -> None:
        self.game = FakeGame(result)
        self.available = False

    def get_game(self) -> FakeGame:
        return self.game

    async def mark_available(self, **_kwargs: object) -> None:
        self.available = True

    async def mark_unavailable(self, *_args: object, **_kwargs: object) -> None:
        return None


class FakeTeamResource:
    def __init__(self) -> None:
        self.offered = False

    def offer_subscription(self, **_kwargs: object) -> str:
        self.offered = True
        return "订阅提示"


def _service(
    result: TeamInfo | Exception = TeamInfo(),
) -> tuple[SeerTeamQueryService, FakeHeadless, FakeTeamResource]:
    headless = FakeHeadless(result)
    team_resource = FakeTeamResource()
    service = SeerTeamQueryService(
        TeamQueryConfig(),
        cast("HeadlessService", headless),
        lambda _code: None,
        cast("TeamResourceService", team_resource),
    )
    return service, headless, team_resource


def test_team_service_parses_unique_ids_before_validation() -> None:
    service, _headless, _resource = _service()

    assert service.parse_team_ids("战队123456 99 123456 2000000001 654321") == (
        123456,
        99,
        2000000001,
        654321,
    )


def _query_context(
    text: str, mentions: tuple[ActorRef, ...] = ()
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            Platform.ONEBOT,
            _actor(),
            _group(),
            "event-id",
            text=text,
            direct_mentions=mentions,
        ),
        mentions_bot=False,
    )


def _resolver() -> PlayerIdResolver:
    return PlayerIdResolver(
        lambda reference, _conversation: (
            int(reference)
            if reference.isdecimal()
            else {"alias12": 700001}.get(reference)
        ),
        lambda _actor: 700002,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "mentions", "player_id"),
    [
        ("战队123456", (), None),
        ("查询战队信息123456 654321", (), None),
        ("战队米米号700001", (), 700001),
        ("战队alias12", (), 700001),
        ("战队", (_actor(2),), 700002),
    ],
)
async def test_team_command_shares_player_resolver_without_reinterpreting_team_ids(
    text: str,
    mentions: tuple[ActorRef, ...],
    player_id: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, headless, _ = _service()
    lookup = AsyncMock(return_value=SimpleNamespace(team_id=TEAM_ID))
    monkeypatch.setattr(headless.game, "get_user_info", lookup, raising=False)
    context = _query_context(text, mentions)
    resolver = _resolver()
    matches = team_query_input_matcher(resolver.has_known_reference)
    assert matches(text, command_context_from_input(context))
    operation = build_portable_team_query_operation(
        service,
        FeatureService({}, {}, frozenset({_actor()})),
        resolver,
    )

    result = await operation(text, context)

    assert isinstance(result, OutboundMessage)
    part = result.parts[0]
    assert isinstance(part, TextPart)
    assert "测试战队" in part.text
    if player_id is None:
        lookup.assert_not_awaited()
    else:
        lookup.assert_awaited_once_with(player_id)


@pytest.mark.parametrize(
    "text", ["战队", "战队是什么", "战队陌生别名12", "战队订阅", "专家榜"]
)
def test_team_command_does_not_claim_subscription_or_unknown_alias(text: str) -> None:
    matcher = team_query_input_matcher(_resolver().has_known_reference)
    assert not matcher(text, command_context_from_input(_query_context(text)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "mentions"),
    [
        ("战队alias12", (_actor(2),)),
        ("战队123456", (_actor(2),)),
        ("战队", (_actor(2), _actor(3))),
    ],
)
async def test_team_reference_conflicts_do_not_query_game(
    text: str,
    mentions: tuple[ActorRef, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, headless, _ = _service()
    query = AsyncMock()
    monkeypatch.setattr(headless.game, "get_team_info", query)
    lookup = AsyncMock()
    monkeypatch.setattr(headless.game, "get_user_info", lookup, raising=False)
    operation = build_portable_team_query_operation(
        service,
        FeatureService({}, {}, frozenset({_actor()})),
        _resolver(),
    )

    result = await operation(text, _query_context(text, mentions))

    assert isinstance(result, OutboundMessage)
    part = result.parts[0]
    assert isinstance(part, TextPart)
    assert "不能同时使用" in part.text or "只 @ 一名成员" in part.text
    lookup.assert_not_awaited()
    query.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("team_id", [0, None, -1])
async def test_player_without_team_is_not_queried_as_team_zero(
    team_id: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, headless, _ = _service()
    monkeypatch.setattr(
        headless.game,
        "get_user_info",
        AsyncMock(return_value=SimpleNamespace(team_id=team_id)),
        raising=False,
    )
    query = AsyncMock()
    monkeypatch.setattr(headless.game, "get_team_info", query)

    result = await service.query_player_team(
        700001, TeamQueryActor(_actor(), _group(), can_manage=False)
    )

    assert "当前未加入战队" in result
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_player_team_timeout_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    service, headless, _ = _service()
    monkeypatch.setattr(
        headless.game,
        "get_user_info",
        AsyncMock(side_effect=TimeoutError()),
        raising=False,
    )

    result = await service.lookup_player_team(
        700001, TeamQueryActor(_actor(), _group(), can_manage=False)
    )

    assert result.team_id is None
    assert result.error is not None and "所属战队查询超时" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        NotLoggedInError(),
        DisconnectedError(),
        SocketRecvError(SimpleNamespace(result=101105)),
    ],
)
async def test_player_team_failure_is_not_reported_as_no_team(
    error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, headless, _ = _service()
    monkeypatch.setattr(
        headless.game, "get_user_info", AsyncMock(side_effect=error), raising=False
    )
    result = await service.lookup_player_team(
        700001, TeamQueryActor(_actor(), _group(), can_manage=False)
    )
    assert result.team_id is None
    assert result.error and "700001" in result.error
    assert "未加入战队" not in result.error
    assert not headless.available


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["战队123456", "战队米米号700001", "战队alias12"])
async def test_team_query_rechecks_permission_before_game_access(text: str) -> None:
    service, headless, _ = _service()
    operation = build_portable_team_query_operation(
        service, FeatureService({}, {}, frozenset()), _resolver()
    )
    result = await operation(text, _query_context(text))
    assert isinstance(result, OutboundMessage)
    part = result.parts[0]
    assert isinstance(part, TextPart)
    assert "未对你开放" in part.text
    assert not headless.available


@pytest.mark.asyncio
async def test_team_service_queries_and_formats_enabled_sections() -> None:
    service, headless, resource = _service()

    message = await service.query(
        (TEAM_ID,),
        TeamQueryActor(actor=_actor(), conversation=None, can_manage=False),
    )

    assert "【战队信息：测试战队】" in message
    assert "战队ID：123456" in message
    assert "战队等级：9" in message
    assert "战队资源：777" in message
    assert "战队 Boss：剩余能量 4/200｜活动状态：暂无法确认" in message
    assert "标语：一起冲" in message
    assert "公告：今晚集合" in message
    assert "【文本】" not in message
    assert "【设施等级】" not in message
    assert headless.available
    assert not resource.offered


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        (0, "剩余能量 200/200"),
        (196, "剩余能量 4/200"),
        (200, "剩余能量 0/200"),
        (-1, "能量数据异常（已削减能量：-1）"),
        (201, "能量数据异常（已削减能量：201）"),
    ],
)
def test_team_boss_energy_display(damage: int, expected: str) -> None:
    info = TeamInfo(total_boss_dmg=damage)
    message = format_team_info(
        info,
        {"basic", "resource", "facilities"},
        include_boss=True,
    )

    assert f"战队 Boss：{expected}｜活动状态：暂无法确认" in message
    assert message.count("战队 Boss：") == 1
    assert "战队Boss总伤害" not in message
    assert "战队 Boss：" not in format_team_info(info, {"basic"})


@pytest.mark.parametrize(
    ("status", "label"),
    [
        (TeamBossActivityStatus.OPEN, "开启"),
        (TeamBossActivityStatus.CLOSED, "关闭"),
        (TeamBossActivityStatus.UNKNOWN, "暂无法确认"),
    ],
)
def test_team_boss_activity_status_is_explicit(
    status: TeamBossActivityStatus,
    label: str,
) -> None:
    message = format_team_info(
        TeamInfo(),
        {"resource"},
        include_boss=True,
        boss_activity_status=status,
    )

    assert f"活动状态：{label}" in message


def test_team_resource_format_does_not_include_active_query_details() -> None:
    message = format_team_info(TeamInfo(), {"basic", "resource"})

    assert "战队 Boss：" not in message
    assert "标语：" not in message
    assert "公告：" not in message


@pytest.mark.asyncio
async def test_team_service_rejects_more_than_three_ids_without_querying() -> None:
    service, headless, _resource = _service()

    message = await service.query(
        (123456, 234567, 345678, 456789),
        TeamQueryActor(actor=_actor(), conversation=None, can_manage=False),
    )

    assert "一次最多查询 3 个战队" in message
    assert not headless.available


@pytest.mark.asyncio
async def test_team_service_adds_subscription_prompt_for_group_manager() -> None:
    service, _headless, resource = _service()

    message = await service.query(
        (TEAM_ID,),
        TeamQueryActor(actor=_actor(), conversation=_group(), can_manage=True),
    )

    assert message.endswith("订阅提示")
    assert resource.offered


@pytest.mark.asyncio
async def test_team_service_formats_timeout() -> None:
    service, _headless, _resource = _service(TimeoutError())

    assert (
        await service.query(
            (TEAM_ID,),
            TeamQueryActor(actor=_actor(), conversation=None, can_manage=False),
        )
        == "❌ 战队 123456 查询超时，请稍后再试。"
    )


@pytest.mark.asyncio
async def test_team_service_rejects_invalid_id_before_io() -> None:
    service, headless, _resource = _service()

    message = await service.query(
        (1,),
        TeamQueryActor(actor=_actor(), conversation=_group(), can_manage=True),
    )

    assert "100000 ~ 2000000000" in message
    assert not headless.available
